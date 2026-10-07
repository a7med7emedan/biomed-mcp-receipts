"""Typed records shared across the bench: tasks, servers, answers, scores."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Capability = Literal["trial.lookup", "literature.search"]
Expectation = Literal["record", "not_found", "invalid_input", "no_results"]


class Task(BaseModel):
    """A question written once against a capability, never against one server's tool names."""

    id: str
    capability: Capability
    params: dict[str, Any]
    expect: Expectation = "record"
    note: str = ""


class ServerSpec(BaseModel):
    """How to launch one server under test over stdio, pinned to an exact version."""

    id: str
    adapter: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    package: str = ""
    version: str = ""
    repo: str = ""
    licence: str = ""
    taskset: str = "core"
    timeout_s: float = 90.0
    capabilities: list[Capability]


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class RawResult(BaseModel):
    """What came back from one tool call, kept verbatim for the receipt."""

    ok: bool
    is_error: bool = False
    error: str | None = None
    text: str = ""
    structured: Any = None
    payload: dict[str, Any] | None = None
    latency_ms: float = 0.0


class TrialAnswer(BaseModel):
    nct_ids: list[str] = Field(default_factory=list)
    status: str | None = None
    title_found: bool = False
    last_update: str | None = None


class LiteratureAnswer(BaseModel):
    pmids: list[str] = Field(default_factory=list)


class OracleAnswer(BaseModel):
    """The gold answer, taken from the primary source at run time."""

    source: str
    url: str
    release: str | None = None
    retrieved_at: str
    found: bool = True
    body_sha256: str = ""
    # trial.lookup
    nct_id: str | None = None
    status: str | None = None
    title: str | None = None
    last_update: str | None = None
    # literature.search
    pmids: list[str] = Field(default_factory=list)
    total: int | None = None


class Score(BaseModel):
    """One dimension's verdict on one check. ``value`` is None when the dimension does not apply."""

    dimension: str
    value: float | None
    detail: str = ""


class CheckRecord(BaseModel):
    run_id: str
    check_id: str
    server_id: str
    task_id: str
    capability: str
    expect: str = "record"
    call: ToolCall | None = None
    result: RawResult | None = None
    repeat_result: RawResult | None = None
    oracle: OracleAnswer | None = None
    scores: list[Score] = Field(default_factory=list)
