"""Command line: bmr run | demo | verify | crate | report | servers | tasks."""

from __future__ import annotations

import functools
import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

import anyio
import typer

from . import DIMENSIONS, __version__
from .config import available_tasksets, load_servers, load_tasks
from .fixtures import build_world_cassettes
from .models import ServerSpec, Task
from .oracles import OracleHTTP, Oracles
from .planted import FAULTS, build_server
from .receipts import verify as verify_receipts
from .receipts import write_crate
from .runner import new_run_id
from .runner import run as run_bench

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Check biomedical MCP servers against primary sources, with a receipt per check.",
)


def _world_oracles(tmp: Path) -> Oracles:
    cassettes = tmp / "world-cassettes"
    build_world_cassettes(cassettes)
    return Oracles(OracleHTTP(mode="replay", cassette_dir=cassettes))


@app.command()
def version() -> None:
    """Print the bench version."""
    typer.echo(__version__)


@app.command()
def servers(config: Annotated[Path | None, typer.Option(help="servers.yaml to use")] = None) -> None:
    """List the pinned servers under test."""
    for s in load_servers(config).values():
        typer.echo(f"{s.id:16} {s.package} {s.version:10} {', '.join(s.capabilities)}")


@app.command()
def tasks() -> None:
    """List the task sets and their tasks."""
    for name in available_tasksets():
        typer.echo(f"[{name}]")
        for t in load_tasks(name):
            typer.echo(f"  {t.id:32} {t.capability:18} expect={t.expect}")


@app.command()
def run(
    server: Annotated[
        list[str] | None, typer.Option("--server", "-s", help="server id; repeat; default all")
    ] = None,
    oracle: Annotated[str, typer.Option(help="live | record | replay")] = "live",
    cassettes: Annotated[
        Path | None,
        typer.Option(help="cassettes to replay; when recording, defaults to <out>/<run-id>/cassettes"),
    ] = None,
    out: Annotated[Path, typer.Option(help="where runs are written")] = Path("runs"),
    config: Annotated[Path | None, typer.Option(help="servers.yaml to use")] = None,
    crate: Annotated[bool, typer.Option(help="also write an RO-Crate for the run")] = True,
) -> None:
    """Run the bench. The planted server always uses its own synthetic world in replay mode."""
    if oracle not in ("live", "record", "replay"):
        raise typer.BadParameter("oracle must be live, record or replay")
    specs_all = load_servers(config)
    chosen = server or list(specs_all)
    unknown = set(chosen) - set(specs_all)
    if unknown:
        raise typer.BadParameter(f"unknown server(s): {sorted(unknown)}")
    specs = [specs_all[s] for s in chosen]
    run_id = new_run_id()
    needs_real_oracle = any(s.taskset != "planted" for s in specs)
    if oracle == "record" and cassettes is None:
        cassettes = out / run_id / "cassettes"  # each run keeps its own evidence
    if oracle == "replay" and cassettes is None and needs_real_oracle:
        raise typer.BadParameter("replay needs --cassettes, for example runs/<run-id>/cassettes")
    with tempfile.TemporaryDirectory() as tmp:
        world = _world_oracles(Path(tmp))
        real = Oracles(OracleHTTP(mode=oracle, cassette_dir=cassettes))  # type: ignore[arg-type]
        oracles_for = {s.id: (world if s.taskset == "planted" else real) for s in specs}
        tasks_for = {s.id: load_tasks(s.taskset) for s in specs}
        results = anyio.run(
            functools.partial(run_bench, specs, tasks_for, oracles_for, out, oracle, run_id=run_id)
        )
    run_dir = Path(results["run_dir"])
    if crate:
        write_crate(run_dir)
    typer.echo((run_dir / "summary.md").read_text())
    typer.echo(f"Run written to {run_dir}")
    failed = [sid for sid, s in results["servers"].items() if s.get("error")]
    if failed:
        typer.echo(f"Servers that failed to run: {', '.join(failed)}", err=True)


def demo_matrix(out: Path) -> dict[str, Any]:
    """Run the planted server clean and with each fault; report which dimensions dropped below 1."""
    planted = load_servers()["planted"]
    planted_tasks: list[Task] = load_tasks("planted")
    rows: dict[str, Any] = {}

    async def go() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for fault in ["none", *FAULTS]:
                faults = set() if fault == "none" else {fault}
                spec = ServerSpec(**{**planted.model_dump(), "id": f"planted-{fault}"})
                results = await run_bench(
                    [spec],
                    {spec.id: planted_tasks},
                    {spec.id: _world_oracles(Path(tmp))},
                    out,
                    "replay",
                    targets={spec.id: build_server(faults)},
                    run_id=f"demo-{fault}",
                )
                dims = results["servers"][spec.id]["dimensions"]
                rows[fault] = {
                    "expected": FAULTS.get(fault),
                    "failed": sorted(
                        d for d in DIMENSIONS if dims[d]["mean"] is not None and dims[d]["mean"] < 1
                    ),
                    "run_dir": results["run_dir"],
                }

    anyio.run(go)
    return rows


@app.command()
def demo(out: Annotated[Path, typer.Option(help="where demo runs are written")] = Path("runs")) -> None:
    """Prove the bench works: every planted fault must trip its own dimension and no other."""
    rows = demo_matrix(out)
    ok = True
    typer.echo(f"{'planted fault':14} {'should trip':13} tripped")
    for fault, row in rows.items():
        expected = [row["expected"]] if row["expected"] else []
        good = row["failed"] == expected
        ok &= good
        typer.echo(
            f"{fault:14} {row['expected'] or '(nothing)':13} {', '.join(row['failed']) or '(nothing)'}"
            f"  {'ok' if good else 'MISMATCH'}"
        )
    if not ok:
        raise typer.Exit(code=1)
    typer.echo("Every planted fault was caught by its own dimension, and only that one.")


@app.command()
def verify(receipts: Path) -> None:
    """Recompute every receipt hash and the chain. Exit 1 if anything was altered."""
    path = receipts / "receipts.jsonl" if receipts.is_dir() else receipts
    head = count = None
    results_file = path.parent / "results.json"
    if results_file.exists():
        recorded = json.loads(results_file.read_text()).get("receipts") or {}
        head, count = recorded.get("head"), recorded.get("count")
    else:
        typer.echo(
            "No results.json beside the receipts: lines cut from the end cannot be detected.", err=True
        )
    ok, problems = verify_receipts(path, head, count)
    for p in problems:
        typer.echo(p, err=True)
    if not ok:
        raise typer.Exit(code=1)
    n = sum(1 for line in path.read_text().splitlines() if line.strip())
    typer.echo(f"{n} receipts verified, chain intact.")


@app.command()
def crate(run_dir: Path) -> None:
    """Write ro-crate-metadata.json for a run directory."""
    typer.echo(f"Wrote {write_crate(run_dir)}")


@app.command()
def report(run_dir: Path, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Print a run's summary."""
    if as_json:
        typer.echo(json.dumps(json.loads((run_dir / "results.json").read_text()), indent=1))
    else:
        typer.echo((run_dir / "summary.md").read_text())


if __name__ == "__main__":
    app()
