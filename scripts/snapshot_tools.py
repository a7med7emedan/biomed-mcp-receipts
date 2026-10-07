"""Capture or check each pinned server's tools/list.

    python scripts/snapshot_tools.py            write tests/fixtures/tools/<server>.json
    python scripts/snapshot_tools.py --check    exit 1 if a pinned server's tools drifted

The adapter contract tests validate every adapter call against these snapshots, so a change in a
server's tool names or input schemas shows up as a named, failing test rather than a quiet 0 score.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio

from biomed_mcp_receipts.config import load_servers
from biomed_mcp_receipts.runner import session, stdio_target

SNAPSHOTS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "tools"


def comparable(snapshot: dict) -> dict:
    return {t["name"]: t["input_schema"] for t in snapshot["tools"]}


async def capture(server_id: str) -> dict:
    spec = load_servers()[server_id]
    async with session(stdio_target(spec), spec.timeout_s) as client:
        tools = (await client.list_tools()).tools
        info = client.server_info
        return {
            "server_info": info.model_dump(mode="json") if info else None,
            "protocol": client.protocol_version,
            "tools": [
                {
                    "name": t.name,
                    "input_schema": t.input_schema,
                    "output_schema": t.output_schema,
                }
                for t in tools
            ],
        }


async def main(check: bool) -> int:
    drift = 0
    for spec in load_servers().values():
        if spec.id == "planted":
            continue
        live = await capture(spec.id)
        path = SNAPSHOTS / f"{spec.id}.json"
        if check:
            stored = json.loads(path.read_text())
            if comparable(stored) != comparable(live):
                drift += 1
                added = sorted(set(comparable(live)) - set(comparable(stored)))
                removed = sorted(set(comparable(stored)) - set(comparable(live)))
                print(f"DRIFT {spec.id}: added {added}, removed {removed}, or input schemas changed")
            else:
                print(f"ok    {spec.id} {spec.version}: {len(live['tools'])} tools unchanged")
        else:
            live["captured"] = __import__("datetime").date.today().isoformat()
            path.write_text(json.dumps(live, indent=1, sort_keys=True) + "\n")
            print(f"wrote {path}")
    return 1 if drift else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true")
    sys.exit(anyio.run(main, parser.parse_args().check))
