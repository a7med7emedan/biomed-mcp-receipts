"""Contract tests: every adapter call must be valid against the real server's own inputSchema.

The schemas in fixtures/tools/ were captured from each server's tools/list at the pinned version.
If a server changes its tools, refresh the snapshot with scripts/snapshot_tools.py and this test
shows exactly which adapter call broke.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from biomed_mcp_receipts.adapters import ADAPTERS, get_adapter
from biomed_mcp_receipts.config import load_servers, load_tasks

SNAPSHOTS = Path(__file__).parent / "fixtures" / "tools"
REAL = [s for s in load_servers().values() if s.id != "planted"]


def cases():
    for spec in REAL:
        for task in load_tasks(spec.taskset):
            if task.capability in spec.capabilities:
                yield pytest.param(spec, task, id=f"{spec.id}-{task.id}")


@pytest.mark.parametrize(("spec", "task"), list(cases()))
def test_adapter_call_matches_real_schema(spec, task):
    snapshot = json.loads((SNAPSHOTS / f"{spec.id}.json").read_text())
    assert snapshot["server_info"]["version"] == spec.version, "snapshot and pinned version differ"
    tools = {t["name"]: t for t in snapshot["tools"]}
    call = get_adapter(spec.adapter)(task)
    assert call.name in tools, f"{spec.id} has no tool {call.name!r}"
    schema = tools[call.name]["input_schema"]
    if task.expect == "invalid_input":
        return  # a malformed input may be rejected by the schema; that is the point of the task
    errors = list(Draft202012Validator(schema).iter_errors(call.arguments))
    assert not errors, [e.message for e in errors]


def test_every_server_has_an_adapter():
    for spec in load_servers().values():
        assert spec.adapter in ADAPTERS


def test_unknown_adapter():
    with pytest.raises(KeyError):
        get_adapter("nope")


def test_single_capability_adapters_refuse_the_other():
    from biomed_mcp_receipts.models import Task

    lit = Task(
        id="l",
        capability="literature.search",
        params={"query": "q", "since": "2025-01-01", "until": "2025-02-01"},
    )
    trial = Task(id="t", capability="trial.lookup", params={"nct_id": "NCT04280705"})
    with pytest.raises(NotImplementedError):
        ADAPTERS["clinicaltrials"](lit)
    with pytest.raises(NotImplementedError):
        ADAPTERS["pubmed"](trial)
