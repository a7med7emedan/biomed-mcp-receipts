from typer.testing import CliRunner

from biomed_mcp_receipts.cli import app

runner = CliRunner()


def test_servers_and_tasks_list():
    r = runner.invoke(app, ["servers"])
    assert r.exit_code == 0 and "biomcp" in r.output and "clinicaltrials" in r.output
    r = runner.invoke(app, ["tasks"])
    assert r.exit_code == 0 and "[core]" in r.output and "[planted]" in r.output


def test_demo_passes(tmp_path):
    r = runner.invoke(app, ["demo", "--out", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "MISMATCH" not in r.output


def test_run_planted_then_verify_and_crate(tmp_path):
    r = runner.invoke(
        app,
        [
            "run",
            "-s",
            "planted",
            "--out",
            str(tmp_path),
            "--oracle",
            "replay",
            "--cassettes",
            str(tmp_path / "unused"),
        ],
    )
    assert r.exit_code == 0, r.output
    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir())
    assert (run_dir / "ro-crate-metadata.json").exists()
    r = runner.invoke(app, ["verify", str(run_dir)])
    assert r.exit_code == 0 and "chain intact" in r.output
    r = runner.invoke(app, ["report", str(run_dir)])
    assert "planted" in r.output


def test_run_rejects_unknown_server(tmp_path):
    r = runner.invoke(app, ["run", "-s", "nope", "--out", str(tmp_path)])
    assert r.exit_code != 0


def test_version():
    assert runner.invoke(app, ["version"]).output.strip() == "0.1.0"


def test_demo_twice_keeps_one_run_per_fault(tmp_path):
    runner.invoke(app, ["demo", "--out", str(tmp_path)])
    runner.invoke(app, ["demo", "--out", str(tmp_path)])
    lines = (tmp_path / "demo-none" / "receipts.jsonl").read_text().splitlines()
    assert len(lines) == 7
    r = runner.invoke(app, ["verify", str(tmp_path / "demo-none")])
    assert r.exit_code == 0


def test_verify_catches_lines_cut_from_the_end(tmp_path):
    runner.invoke(app, ["demo", "--out", str(tmp_path)])
    path = tmp_path / "demo-none" / "receipts.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[:3]) + "\n")
    r = runner.invoke(app, ["verify", str(tmp_path / "demo-none")])
    assert r.exit_code == 1


def test_replay_of_real_servers_needs_cassettes(tmp_path):
    r = runner.invoke(app, ["run", "-s", "clinicaltrials", "--oracle", "replay", "--out", str(tmp_path)])
    assert r.exit_code != 0


def test_python_command_resolves_to_this_interpreter():
    import sys

    from biomed_mcp_receipts.config import load_servers
    from biomed_mcp_receipts.runner import stdio_target

    assert stdio_target(load_servers()["planted"]).command == sys.executable
