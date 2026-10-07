import json

from biomed_mcp_receipts.models import CheckRecord, RawResult, Score, ToolCall
from biomed_mcp_receipts.receipts import ReceiptWriter, read_receipts, verify, write_crate


def record(i: int) -> CheckRecord:
    return CheckRecord(
        run_id="r1",
        check_id=f"s/t{i}",
        server_id="s",
        task_id=f"t{i}",
        capability="trial.lookup",
        call=ToolCall(name="get", arguments={"id": i}),
        result=RawResult(
            ok=True, text=f"answer {i}", payload={"content": [{"type": "text", "text": str(i)}]}
        ),
        scores=[Score(dimension="correctness", value=1.0)],
    )


def write_three(path):
    w = ReceiptWriter(path)
    for i in range(3):
        w.write(record(i), {"id": "s", "name": "server", "version": "1"})


def test_chain_verifies(tmp_path):
    path = tmp_path / "receipts.jsonl"
    write_three(path)
    ok, problems = verify(path)
    assert ok, problems
    rows = read_receipts(path)
    assert rows[0]["prev_chain"] == "0" * 64
    assert rows[1]["prev_chain"] == rows[0]["chain"]
    assert "request_sha256" in rows[0] and "response_sha256" in rows[0]


def test_edit_is_detected(tmp_path):
    path = tmp_path / "receipts.jsonl"
    write_three(path)
    lines = path.read_text().splitlines()
    row = json.loads(lines[1])
    row["scores"][0]["value"] = 0.0
    lines[1] = json.dumps(row, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    ok, problems = verify(path)
    assert not ok and "line 2" in problems[0]


def test_deleted_line_is_detected(tmp_path):
    path = tmp_path / "receipts.jsonl"
    write_three(path)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    ok, problems = verify(path)
    assert not ok and any("chain broken" in p for p in problems)


def test_writer_resumes_chain(tmp_path):
    path = tmp_path / "receipts.jsonl"
    write_three(path)
    ReceiptWriter(path, resume=True).write(record(9), {"id": "s"})
    assert verify(path)[0]


def test_crate_describes_every_check(tmp_path):
    write_three(tmp_path / "receipts.jsonl")
    (tmp_path / "results.json").write_text("{}")
    crate = json.loads(write_crate(tmp_path).read_text())
    graph = {e["@id"]: e for e in crate["@graph"]}
    actions = [e for e in crate["@graph"] if e["@type"] == "CreateAction"]
    assert len(actions) == 3
    assert all(a["instrument"]["@id"] == "#server-s" for a in actions)
    assert graph["./"]["conformsTo"][0]["@id"].startswith("https://w3id.org/ro/wfrun/process/")
    assert "sha256" in graph["receipts.jsonl"]


def test_cut_from_the_end_is_detected_with_the_recorded_head(tmp_path):
    path = tmp_path / "receipts.jsonl"
    w = ReceiptWriter(path)
    for i in range(3):
        w.write(record(i), {"id": "s"})
    head, count = w.prev, w.count
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n")
    assert verify(path)[0]  # the chain alone cannot see it
    ok, problems = verify(path, head, count)
    assert not ok and len(problems) == 2


def test_a_new_run_starts_a_fresh_file(tmp_path):
    path = tmp_path / "receipts.jsonl"
    write_three(path)
    write_three(path)
    assert len(read_receipts(path)) == 3
