# Adding a server

A new server needs four small changes and no new tasks.

## 1. Pin it

Add an entry to [`src/biomed_mcp_receipts/data/servers.yaml`](../src/biomed_mcp_receipts/data/servers.yaml):

```yaml
  - id: myserver
    adapter: myserver
    command: npx
    args: ["-y", "my-mcp-server@1.4.2"]   # always an exact version
    env: {MCP_TRANSPORT_TYPE: stdio}
    package: my-mcp-server (npm)
    version: "1.4.2"
    repo: https://github.com/owner/my-mcp-server
    licence: MIT
    capabilities: [trial.lookup]
```

Only add servers with an open-source licence. A server without one can still be called, but it is
never redistributed or bundled into the Docker image.

## 2. Snapshot its tools

```bash
python scripts/snapshot_tools.py
```

This writes `tests/fixtures/tools/myserver.json` from the server's own `tools/list`.

## 3. Write the adapter

In [`src/biomed_mcp_receipts/adapters/__init__.py`](../src/biomed_mcp_receipts/adapters/__init__.py),
map each capability to the server's tool and arguments, then register it in `ADAPTERS`:

```python
def myserver(task: Task) -> ToolCall:
    if task.capability != "trial.lookup":
        raise NotImplementedError(task.capability)
    return ToolCall(name="get_trial", arguments={"id": task.params["nct_id"]})
```

Read the tool's description as well as its schema. A schema can accept an argument that the tool
then rejects at run time; BioMCP's article search is one example, documented in its adapter.

## 4. Run the tests and a smoke run

```bash
uv run pytest tests/test_adapters.py
uv run bmr run -s myserver --oracle record --cassettes runs/cassettes
```

The contract test validates every adapter call against the snapshot. Read the receipts of the first
run before trusting its scores: they show exactly what the server returned and what the bench read
from it.

## Before any score is published

Open an issue on the server's repository with the findings, the receipts and the command to rerun
them, and give the maintainer 14 days to respond.
