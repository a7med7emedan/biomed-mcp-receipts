# Contributing

Thank you for helping. Reproduction reports, new servers, new capabilities and fixes are all welcome.

## Set up

```bash
git clone git@github.com:a7med7emedan/biomed-mcp-receipts.git
cd biomed-mcp-receipts
uv sync
uv run pytest
uv run bmr demo
```

## Good places to start

- **Add a server.** Pin it, write one adapter function and snapshot its tools. See
  [docs/adding-a-server.md](docs/adding-a-server.md).
- **Add a capability.** Variant lookup, gene lookup and drug labels each need tasks, an oracle
  against the primary source, and a planted fault that proves the scorer works.
- **Reproduce a run.** Replay someone's cassettes, run `bmr verify` and report any mismatch.

## Before opening a pull request

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest --cov --cov-fail-under=90
uv run bmr demo
```

All four must pass. CI runs the same commands on Python 3.11, 3.12 and 3.13.

## Ground rules

- **The planted-fault test is the contract.** A change to a scorer must keep every planted fault
  tripping its own dimension and no other. If you add a dimension, add a fault that trips it.
- **No real patient data**, ever, in code, fixtures or issues. Clinical examples use synthetic data.
- **Pin exact versions** of servers under test, and refresh the tool snapshot when you bump one.
- **Scores about someone else's server are not published** until its maintainer has had the
  findings for 14 days. Report findings to them first, with receipts.
- Commit messages: a short imperative subject line, a blank line, then why the change is needed.

## Reporting a disagreement with a score

Open an issue with the run ID and the `check_id` from `receipts.jsonl`. Every receipt holds the full
request, the full response and the oracle's evidence, so the disagreement can be checked directly.
