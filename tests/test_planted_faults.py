"""The bench's self-test: each planted fault must trip its own dimension and no other."""

import sys

import pytest
from mcp import StdioServerParameters

from biomed_mcp_receipts import DIMENSIONS
from biomed_mcp_receipts.config import load_servers, load_tasks
from biomed_mcp_receipts.planted import FAULTS, build_server, parse_faults
from biomed_mcp_receipts.receipts import verify
from biomed_mcp_receipts.runner import run

pytestmark = pytest.mark.anyio


async def run_planted(tmp_path, oracles, faults, target=None):
    spec = load_servers()["planted"]
    results = await run(
        [spec],
        {spec.id: load_tasks("planted")},
        {spec.id: oracles},
        tmp_path,
        "replay",
        targets={spec.id: target if target is not None else build_server(faults)},
        run_id="t",
    )
    return results["servers"]["planted"], results


def tripped(server_summary):
    return sorted(
        d
        for d in DIMENSIONS
        if server_summary["dimensions"][d]["mean"] is not None and server_summary["dimensions"][d]["mean"] < 1
    )


async def test_clean_server_scores_perfectly(tmp_path, world_oracles):
    summary, _ = await run_planted(tmp_path, world_oracles, set())
    assert summary["error"] is None
    assert tripped(summary) == []
    for dim in DIMENSIONS:
        assert summary["dimensions"][dim]["n"] > 0, f"{dim} was never scored"
    assert verify(tmp_path / "t" / "receipts.jsonl")[0]


@pytest.mark.parametrize("fault", sorted(FAULTS))
async def test_each_fault_trips_only_its_dimension(tmp_path, world_oracles, fault):
    summary, _ = await run_planted(tmp_path, world_oracles, {fault})
    assert tripped(summary) == [FAULTS[fault]]


async def test_all_faults_together(tmp_path, world_oracles):
    summary, _ = await run_planted(tmp_path, world_oracles, set(FAULTS))
    assert tripped(summary) == sorted(set(FAULTS.values()))


async def test_planted_server_over_real_stdio(tmp_path, world_oracles):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "biomed_mcp_receipts.planted"], env={"PLANTED_FAULTS": "stale"}
    )
    summary, _ = await run_planted(tmp_path, world_oracles, set(), target=params)
    assert summary["error"] is None
    assert tripped(summary) == ["freshness"]


async def test_unreachable_server_is_reported_not_raised(tmp_path, world_oracles):
    params = StdioServerParameters(command="/nonexistent/server-binary")
    summary, _ = await run_planted(tmp_path, world_oracles, set(), target=params)
    assert summary["error"]


def test_parse_faults():
    assert parse_faults(None) == set() and parse_faults("none") == set()
    assert parse_faults("all") == set(FAULTS)
    assert parse_faults("stale, flaky") == {"stale", "flaky"}
    with pytest.raises(ValueError):
        parse_faults("nope")


async def test_upstream_outage_is_flagged_not_rewarded(tmp_path, world_oracles):
    """A server whose own source is down must not score well on robustness or stability."""
    from mcp import types
    from mcp.server.lowlevel import Server

    async def call_tool(ctx, params):
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="Upstream returned HTTP 503 Service Unavailable")],
            is_error=True,
        )

    async def list_tools(ctx, params):
        return types.ListToolsResult(
            tools=[
                types.Tool(name="trial_lookup", description="d", input_schema={"type": "object"}),
                types.Tool(name="literature_search", description="d", input_schema={"type": "object"}),
            ]
        )

    down = Server("down", version="1", on_list_tools=list_tools, on_call_tool=call_tool)
    summary, _ = await run_planted(tmp_path, world_oracles, set(), target=down)
    assert summary["dimensions"]["robustness"]["n"] == 0
    assert summary["dimensions"]["stability"]["n"] == 0
    assert summary["dimensions"]["correctness"]["mean"] == 0.0
    assert len(summary["failed_record_calls"]) == 3
    summary_md = (tmp_path / "t" / "summary.md").read_text()
    assert "returned an error instead of an answer" in summary_md


async def test_a_hung_call_does_not_sink_the_rest_of_the_run(tmp_path, world_oracles):
    """The first call hangs and times out; later checks run in fresh sessions and still score."""
    spec = load_servers()["planted"].model_copy(update={"timeout_s": 3.0})
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "biomed_mcp_receipts.planted"],
        env={"PLANTED_HANG_ON": "NCT90000001"},
    )
    results = await run(
        [spec],
        {spec.id: load_tasks("planted")},
        {spec.id: world_oracles},
        tmp_path,
        "replay",
        targets={spec.id: params},
        run_id="hang",
    )
    summary = results["servers"]["planted"]
    assert summary["error"] is None
    assert summary["failed_record_calls"] == ["trial-synthetic-recruiting"]
    later = {c["task_id"]: c for c in summary["checks"]}["trial-synthetic-completed"]
    correctness = next(s for s in later["scores"] if s["dimension"] == "correctness")
    assert correctness["value"] == 1.0
