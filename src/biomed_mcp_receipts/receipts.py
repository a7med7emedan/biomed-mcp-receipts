"""Receipts: one tamper-evident line per check, plus an RO-Crate per run.

Each receipt carries the full request and response, their hashes, the oracle's URL, release and
body hash, and the scores. ``chain`` is SHA-256 over the previous chain value and this receipt's
own hash, so editing or deleting any line breaks every line after it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .models import CheckRecord

GENESIS = "0" * 64
PROCESS_RUN_CRATE = "https://w3id.org/ro/wfrun/process/0.6"
RO_CRATE = "https://w3id.org/ro/crate/1.1"


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReceiptWriter:
    """Writes one run's receipts. A new run starts a fresh file; ``resume`` continues a chain."""

    def __init__(self, path: Path, resume: bool = False) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prev = GENESIS
        self.count = 0
        if resume and self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    self.prev = json.loads(line)["chain"]
                    self.count += 1
        else:
            self.path.write_text("")

    def write(self, record: CheckRecord, server: dict[str, Any]) -> dict[str, Any]:
        body = record.model_dump(mode="json")
        body["server"] = server
        body["bench_version"] = __version__
        body["written_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        if record.call is not None:
            body["request_sha256"] = sha256(canonical(record.call.model_dump(mode="json")))
        if record.result is not None and record.result.payload is not None:
            body["response_sha256"] = sha256(canonical(record.result.payload))
        own = sha256(canonical(body))
        body["receipt_sha256"] = own
        body["prev_chain"] = self.prev
        body["chain"] = sha256((self.prev + own).encode())
        self.prev = body["chain"]
        self.count += 1
        with self.path.open("a") as fh:
            fh.write(json.dumps(body, sort_keys=True, ensure_ascii=False) + "\n")
        return body


def read_receipts(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify(
    path: Path, expected_head: str | None = None, expected_count: int | None = None
) -> tuple[bool, list[str]]:
    """Recompute every hash. Returns (ok, problems).

    The chain alone cannot notice lines cut from the end, so a run also records its final chain
    value and receipt count in results.json; pass them here to catch truncation.
    """
    problems: list[str] = []
    prev = GENESIS
    receipts = read_receipts(path)
    if expected_count is not None and len(receipts) != expected_count:
        problems.append(f"expected {expected_count} receipts, found {len(receipts)}: lines were added or cut")
    for n, receipt in enumerate(receipts, start=1):
        body = {k: v for k, v in receipt.items() if k not in {"receipt_sha256", "prev_chain", "chain"}}
        own = sha256(canonical(body))
        if own != receipt.get("receipt_sha256"):
            problems.append(f"line {n} ({receipt.get('check_id')}): content changed after it was written")
        if receipt.get("prev_chain") != prev:
            problems.append(
                f"line {n} ({receipt.get('check_id')}): chain broken, a line was removed or reordered"
            )
        expected = sha256((prev + receipt.get("receipt_sha256", "")).encode())
        if receipt.get("chain") != expected:
            problems.append(f"line {n} ({receipt.get('check_id')}): chain value wrong")
        prev = receipt.get("chain", "")
    if expected_head is not None and prev != expected_head:
        problems.append(
            "final chain value differs from the one recorded for this run: lines were cut or added"
        )
    return not problems, problems


def write_crate(run_dir: Path) -> Path:
    """Describe a run as an RO-Crate following the Process Run Crate profile.

    Each check is a CreateAction: the server under test is its instrument, the request its
    object, and the receipts file its result.
    """
    receipts = read_receipts(run_dir / "receipts.jsonl")
    run_id = receipts[0]["run_id"] if receipts else run_dir.name
    bench_id = "https://github.com/a7med7emedan/biomed-mcp-receipts"
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": [{"@id": RO_CRATE}],
            "about": {"@id": "./"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": f"biomed-mcp-receipts run {run_id}",
            "description": (
                "Checks of biomedical MCP servers against primary sources, with one receipt per check."
            ),
            "datePublished": datetime.now(UTC).date().isoformat(),
            "license": {"@id": "https://spdx.org/licenses/Apache-2.0"},
            "conformsTo": [{"@id": PROCESS_RUN_CRATE}],
            "hasPart": [
                {"@id": f}
                for f in ("receipts.jsonl", "results.json", "summary.md", "cassettes/")
                if (run_dir / f).exists()
            ],
            "mentions": [],
        },
        {"@id": PROCESS_RUN_CRATE, "@type": "CreativeWork", "name": "Process Run Crate", "version": "0.6"},
        {
            "@id": bench_id,
            "@type": "SoftwareApplication",
            "name": "biomed-mcp-receipts",
            "softwareVersion": __version__,
        },
    ]
    for f in ("receipts.jsonl", "results.json", "summary.md"):
        if (run_dir / f).exists():
            entity: dict[str, Any] = {"@id": f, "@type": "File", "sha256": sha256((run_dir / f).read_bytes())}
            if f == "receipts.jsonl" and receipts:
                entity["description"] = (
                    f"{len(receipts)} hash-chained receipts; final chain {receipts[-1]['chain']}"
                )
            graph.append(entity)
    if (run_dir / "cassettes").is_dir():
        graph.append(
            {
                "@id": "cassettes/",
                "@type": "Dataset",
                "name": "Primary-source responses recorded during the run",
                "description": "Replay with: bmr run --oracle replay --cassettes <this folder>",
            }
        )
    servers: dict[str, dict[str, Any]] = {}
    for r in receipts:
        s = r.get("server") or {}
        sid = f"#server-{r['server_id']}"
        servers.setdefault(
            sid,
            {
                "@id": sid,
                "@type": "SoftwareApplication",
                "name": s.get("name") or r["server_id"],
                "softwareVersion": s.get("version", ""),
                "url": s.get("repo", ""),
            },
        )
        action_id = f"#check-{r['check_id']}"
        graph[1]["mentions"].append({"@id": action_id})
        action: dict[str, Any] = {
            "@id": action_id,
            "@type": "CreateAction",
            "name": f"{r['server_id']} / {r['task_id']}",
            "instrument": {"@id": sid},
            "agent": {"@id": bench_id},
            "result": {"@id": "receipts.jsonl"},
            "identifier": r.get("receipt_sha256"),
            "endTime": r.get("written_at"),
        }
        if r.get("call"):
            action["object"] = {"@id": f"#request-{r['check_id']}"}
            graph.append(
                {
                    "@id": f"#request-{r['check_id']}",
                    "@type": "PropertyValue",
                    "name": r["call"]["name"],
                    "value": json.dumps(r["call"]["arguments"], sort_keys=True),
                }
            )
        graph.append(action)
    graph.extend(servers.values())
    path = run_dir / "ro-crate-metadata.json"
    path.write_text(json.dumps({"@context": f"{RO_CRATE}/context", "@graph": graph}, indent=1))
    return path
