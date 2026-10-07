"""Run every task against every server, ask the oracle, score, and write receipts."""

from __future__ import annotations

import contextlib
import json
import os
import statistics
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters, types

from . import DIMENSIONS, __version__, scorers
from .adapters import get_adapter
from .models import CheckRecord, OracleAnswer, RawResult, Score, ServerSpec, Task, ToolCall
from .oracles import Oracles
from .receipts import ReceiptWriter, canonical, sha256

PUBLISHING_NOTE = (
    "Scores for third-party servers are shared privately with each maintainer, "
    "with 14 days to respond, before they are published."
)


async def _skip_client_validation(name: str, result: types.CallToolResult) -> None:
    """The SDK client rejects results that break their own outputSchema.

    The bench must see those results to score them, so validation moves to the schema scorer.
    """


def _text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


@contextlib.asynccontextmanager
async def session(target: Any, timeout_s: float) -> AsyncIterator[Client]:
    """A properly scoped MCP session.

    Each check gets its own session, so a call that hangs or crashes the server cannot leak
    into the next check. Request timeouts use the SDK's own per-request limit, which raises a
    clean MCPError instead of cancelling the client's internal tasks.
    """
    async with Client(target, read_timeout_seconds=timeout_s) as client:
        client.session.validate_tool_result = _skip_client_validation  # type: ignore[method-assign]
        yield client


async def invoke(client: Client, call: ToolCall, timeout_s: float) -> RawResult:
    start = time.perf_counter()
    try:
        result = await client.call_tool(call.name, call.arguments, read_timeout_seconds=timeout_s)
    except Exception as exc:  # a clean protocol error is a valid answer to a bad input
        return RawResult(
            ok=False,
            error=f"{type(exc).__name__}: {exc}"[:2000],
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    return RawResult(
        ok=True,
        is_error=bool(result.is_error),
        text=_text(result),
        structured=result.structured_content,
        payload=result.model_dump(mode="json", by_alias=True, exclude_none=True),
        latency_ms=(time.perf_counter() - start) * 1000,
    )


async def call_twice(target: Any, call: ToolCall, timeout_s: float) -> tuple[RawResult, RawResult]:
    """Two identical calls in one fresh session. A session that fails to open or close is recorded."""
    first: RawResult | None = None
    second: RawResult | None = None
    try:
        async with session(target, timeout_s) as client:
            first = await invoke(client, call, timeout_s)
            second = await invoke(client, call, timeout_s)
    except Exception as exc:
        failure = RawResult(ok=False, error=f"session failed: {type(exc).__name__}: {exc}"[:2000])
        first = first or failure
        second = second or failure
    assert first is not None and second is not None
    return first, second


@dataclass
class ServerOutcome:
    spec: ServerSpec
    meta: dict[str, Any] = field(default_factory=dict)
    conformance: Score | None = None
    conformance_checks: list[dict[str, Any]] = field(default_factory=list)
    records: list[CheckRecord] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        dims: dict[str, dict[str, Any]] = {}
        for dim in DIMENSIONS:
            if dim == "conformance":
                values = (
                    [self.conformance.value]
                    if self.conformance and self.conformance.value is not None
                    else []
                )
            else:
                values = [
                    s.value
                    for r in self.records
                    for s in r.scores
                    if s.dimension == dim and s.value is not None
                ]
            dims[dim] = {"mean": round(sum(values) / len(values), 3) if values else None, "n": len(values)}
        calls = [r for r in self.records if r.task_id != "conformance"]
        latencies = sorted(r.result.latency_ms for r in calls if r.result and r.result.ok)
        failed = [
            r.task_id
            for r in calls
            if r.expect == "record" and r.result is not None and (not r.result.ok or r.result.is_error)
        ]
        latency = {}
        if latencies:
            latency = {
                "p50": round(statistics.median(latencies), 1),
                "p95": round(latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))], 1),
            }
        return {
            "meta": self.meta,
            "error": self.error,
            "dimensions": dims,
            "latency_ms": latency,
            "failed_record_calls": failed,
            "conformance_checks": self.conformance_checks,
            "checks": [
                {"task_id": r.task_id, "scores": [s.model_dump() for s in r.scores]} for r in self.records
            ],
        }


def stdio_target(spec: ServerSpec) -> StdioServerParameters:
    # "python" means this interpreter, which works under pipx, uv tool and systems with only python3.
    command = sys.executable if spec.command in ("python", "python3") else spec.command
    return StdioServerParameters(command=command, args=spec.args, env={**os.environ, **spec.env})


async def run_server(
    spec: ServerSpec,
    tasks: list[Task],
    oracles: Oracles,
    writer: ReceiptWriter,
    run_id: str,
    target: Any = None,
) -> ServerOutcome:
    """Score one server. ``target`` overrides the stdio launch (tests pass an in-process server)."""
    outcome = ServerOutcome(spec=spec)
    adapter = get_adapter(spec.adapter)
    target = target if target is not None else stdio_target(spec)
    try:
        async with session(target, spec.timeout_s) as client:
            tools = (await client.list_tools()).tools
            tools_again = (await client.list_tools(cache_mode="bypass")).tools
            info = client.server_info
            protocol = client.protocol_version
        tool_dump = [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]
        outcome.meta = {
            "id": spec.id,
            "name": getattr(info, "name", None),
            "version": getattr(info, "version", None),
            "pinned_version": spec.version,
            "package": spec.package,
            "repo": spec.repo,
            "licence": spec.licence,
            "protocol": protocol,
            "tools_sha256": sha256(canonical(sorted(tool_dump, key=lambda t: t["name"]))),
        }
        outcome.conformance, outcome.conformance_checks = scorers.conformance(tools, tools_again, info)
        conf_record = CheckRecord(
            run_id=run_id,
            check_id=f"{spec.id}/conformance",
            server_id=spec.id,
            task_id="conformance",
            capability="tools/list",
            result=RawResult(ok=True, payload={"tools": tool_dump, "checks": outcome.conformance_checks}),
            scores=[outcome.conformance],
        )
        writer.write(conf_record, outcome.meta)
        outcome.records.append(conf_record)
        by_name = {t.name: t for t in tools}

        for task in tasks:
            if task.capability not in spec.capabilities:
                continue
            call = adapter(task)
            first, second = await call_twice(target, call, spec.timeout_s)
            oracle: OracleAnswer | None = None
            oracle_note = ""
            try:
                oracle = await oracles.answer(task)
            except Exception as exc:
                oracle_note = f"oracle unavailable: {type(exc).__name__}: {exc}"[:300]
            scores = [
                scorers.schema(by_name.get(call.name), first),
                scorers.correctness(task, first, oracle),
                scorers.freshness(task, first, oracle),
                scorers.attribution(task, first),
                scorers.robustness(task, first),
                scorers.stability(task, first, second),
            ]
            if oracle_note:
                scores = [
                    s
                    if s.dimension not in {"correctness", "freshness"}
                    else Score(dimension=s.dimension, value=None, detail=oracle_note)
                    for s in scores
                ]
            record = CheckRecord(
                run_id=run_id,
                check_id=f"{spec.id}/{task.id}",
                server_id=spec.id,
                task_id=task.id,
                capability=task.capability,
                expect=task.expect,
                call=call,
                result=first,
                repeat_result=second,
                oracle=oracle,
                scores=scores,
            )
            writer.write(record, outcome.meta)
            outcome.records.append(record)
    except Exception as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"[:1000]
    return outcome


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _fmt(cell: dict[str, Any]) -> str:
    return "–" if cell["mean"] is None else f"{cell['mean']:.2f} (n={cell['n']})"


def summary_markdown(results: dict[str, Any]) -> str:
    lines = [
        f"# biomed-mcp-receipts run {results['run_id']}",
        "",
        f"Oracle mode: {results['oracle_mode']}. Bench {results['bench_version']}. "
        "Scores run 0 to 1 per dimension; – means the dimension did not apply.",
        "",
        "| Server | Version | " + " | ".join(d.capitalize() for d in DIMENSIONS) + " | p50 ms |",
        "| --- | --- | " + " | ".join("---" for _ in DIMENSIONS) + " | --- |",
    ]
    for sid, s in results["servers"].items():
        meta = s.get("meta") or {}
        if s.get("error") and not s["checks"]:
            lines.append(f"| {sid} | {meta.get('pinned_version', '')} | failed to run: {s['error'][:80]} |")
            continue
        cells = " | ".join(_fmt(s["dimensions"][d]) for d in DIMENSIONS)
        lines.append(
            f"| {sid} | {meta.get('version') or meta.get('pinned_version', '')} | {cells} | "
            f"{s['latency_ms'].get('p50', '–')} |"
        )
    for sid, s in results["servers"].items():
        failed = s.get("failed_record_calls") or []
        if failed:
            lines.append(
                f"- {sid}: {len(failed)} lookup(s) returned an error instead of an answer "
                f"({', '.join(failed)}). Read their receipts before trusting this row."
            )
    lines += ["", PUBLISHING_NOTE, ""]
    return "\n".join(lines)


async def run(
    specs: list[ServerSpec],
    tasks_for: dict[str, list[Task]],
    oracles_for: dict[str, Oracles],
    out_dir: Path,
    oracle_mode: str,
    targets: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or new_run_id()
    run_dir = out_dir / run_id
    writer = ReceiptWriter(run_dir / "receipts.jsonl")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    outcomes: dict[str, ServerOutcome] = {}
    try:
        for spec in specs:
            target = (targets or {}).get(spec.id)
            outcomes[spec.id] = await run_server(
                spec, tasks_for[spec.id], oracles_for[spec.id], writer, run_id, target
            )
    finally:
        for o in {id(o): o for o in oracles_for.values()}.values():
            await o.aclose()
    results = {
        "run_id": run_id,
        "bench_version": __version__,
        "oracle_mode": oracle_mode,
        "started": started,
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        "servers": {sid: o.summary() for sid, o in outcomes.items()},
        "receipts": {"count": writer.count, "head": writer.prev},
    }
    (run_dir / "results.json").write_text(json.dumps(results, indent=1, default=str))
    (run_dir / "summary.md").write_text(summary_markdown(results))
    results["run_dir"] = str(run_dir)
    return results
