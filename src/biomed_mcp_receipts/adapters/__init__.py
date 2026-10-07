"""Adapters map a capability task to one server's own tool name and arguments.

Adding a server means adding one function here, not rewriting tasks. Tool names and
argument shapes below were read from each server's own ``tools/list`` at the pinned version.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import Task, ToolCall

AdapterFn = Callable[[Task], ToolCall]


def _limit(task: Task, default: int = 20) -> int:
    return int(task.params.get("limit", default))


def planted(task: Task) -> ToolCall:
    p = task.params
    if task.capability == "trial.lookup":
        return ToolCall(name="trial_lookup", arguments={"nct_id": p["nct_id"]})
    return ToolCall(
        name="literature_search",
        arguments={"query": p["query"], "since": p["since"], "until": p["until"], "limit": _limit(task)},
    )


def biomcp(task: Task) -> ToolCall:
    """genomoncology/biomcp 0.9.x: typed ``get`` and ``search`` tools, JSON output on request.

    Article search takes free text as ``keyword``, a list of up to three strings. Its schema also
    lists ``query``, which other entities use, but article search rejects it at run time
    ("unknown article search field").
    """
    p = task.params
    if task.capability == "trial.lookup":
        return ToolCall(name="get", arguments={"entity": "trial", "id": p["nct_id"], "json": True})
    return ToolCall(
        name="search",
        arguments={
            "entity": "article",
            "keyword": [p["query"]],
            "date_from": p["since"],
            "date_to": p["until"],
            "limit": min(_limit(task), 25),
            "sort": "date",
            "json": True,
        },
    )


def pubmed(task: Task) -> ToolCall:
    """cyanheads/pubmed-mcp-server 2.10.x."""
    p = task.params
    if task.capability != "literature.search":
        raise NotImplementedError(task.capability)
    return ToolCall(
        name="pubmed_search_articles",
        arguments={
            "query": p["query"],
            "maxResults": _limit(task),
            "sort": "pub_date",
            "dateRange": {"minDate": p["since"].replace("-", "/"), "maxDate": p["until"].replace("-", "/")},
        },
    )


def clinicaltrials(task: Task) -> ToolCall:
    """cyanheads/clinicaltrialsgov-mcp-server 2.9.x."""
    if task.capability != "trial.lookup":
        raise NotImplementedError(task.capability)
    return ToolCall(name="clinicaltrials_get_study_record", arguments={"nctId": task.params["nct_id"]})


ADAPTERS: dict[str, AdapterFn] = {
    "planted": planted,
    "biomcp": biomcp,
    "pubmed": pubmed,
    "clinicaltrials": clinicaltrials,
}


def get_adapter(name: str) -> AdapterFn:
    try:
        return ADAPTERS[name]
    except KeyError as exc:
        raise KeyError(f"unknown adapter {name!r}; known: {sorted(ADAPTERS)}") from exc
