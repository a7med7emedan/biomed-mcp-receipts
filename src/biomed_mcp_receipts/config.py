"""Load the pinned server list and the task sets that ship with the package."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml

from .models import ServerSpec, Task

DATA = resources.files("biomed_mcp_receipts") / "data"


def load_servers(path: Path | None = None) -> dict[str, ServerSpec]:
    text = path.read_text() if path else (DATA / "servers.yaml").read_text()
    raw = yaml.safe_load(text)
    return {s["id"]: ServerSpec(**s) for s in raw["servers"]}


def load_tasks(taskset: str, directory: Path | None = None) -> list[Task]:
    if directory is not None:
        text = (directory / f"{taskset}.yaml").read_text()
    else:
        text = (DATA / "tasks" / f"{taskset}.yaml").read_text()
    raw = yaml.safe_load(text)
    tasks = [Task(**t) for t in raw["tasks"]]
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate task ids in {taskset}")
    return tasks


def available_tasksets() -> list[str]:
    return sorted(
        p.name.removesuffix(".yaml") for p in (DATA / "tasks").iterdir() if p.name.endswith(".yaml")
    )
