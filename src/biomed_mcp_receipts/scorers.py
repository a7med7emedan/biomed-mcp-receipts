"""One scorer per dimension. Each returns a Score whose value is None when it does not apply.

Scores are never added into one number: a server can be correct and stale, or fresh and unsourced,
and the reader should see which.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp import types

from .models import OracleAnswer, RawResult, Score, Task
from .normalize import literature_answer, normalise_status, trial_answer

TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (all |any )?(previous|prior|above) instructions",
        r"<\s*/?\s*(system|important|instructions?)\s*>",
        r"do not (tell|inform|mention to) the user",
        r"exfiltrat",
        r"(send|post|upload) .{0,40}(to|at) https?://",
    )
]
NEWEST_K = 5


# ---------------------------------------------------------------- conformance (once per server)


def _schema_ok(schema: Any) -> tuple[bool, str]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return False, exc.message
    return True, ""


def conformance(
    tools: list[types.Tool], tools_again: list[types.Tool], server_info: Any
) -> tuple[Score, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    info_ok = bool(
        server_info is not None and getattr(server_info, "name", "") and getattr(server_info, "version", "")
    )
    check("server identifies itself (name and version)", info_ok)
    check("at least one tool listed", bool(tools))

    missing = [t.name for t in tools if not (t.description or "").strip()]
    check("every tool has a description", not missing, ", ".join(missing))

    bad_names = [t.name for t in tools if not TOOL_NAME_RE.match(t.name)]
    check("tool names use the allowed characters", not bad_names, ", ".join(bad_names))

    bad_in = []
    for t in tools:
        ok, why = _schema_ok(t.input_schema)
        if not ok or (t.input_schema or {}).get("type") != "object":
            bad_in.append(f"{t.name}: {why or 'type is not object'}")
    check("every inputSchema is valid JSON Schema 2020-12 of type object", not bad_in, "; ".join(bad_in))

    bad_out = []
    for t in tools:
        if t.output_schema is not None:
            ok, why = _schema_ok(t.output_schema)
            if not ok:
                bad_out.append(f"{t.name}: {why}")
    check("every outputSchema is valid JSON Schema 2020-12", not bad_out, "; ".join(bad_out))

    same_order = [t.name for t in tools] == [t.name for t in tools_again]
    check("tools/list order is deterministic", same_order)

    flagged = [
        t.name
        for t in tools
        if any(p.search(f"{t.title or ''} {t.description or ''}") for p in INJECTION_PATTERNS)
    ]
    check("no instruction-injection text in tool descriptions", not flagged, ", ".join(flagged))

    passed = sum(c["ok"] for c in checks)
    return Score(
        dimension="conformance", value=passed / len(checks), detail=f"{passed}/{len(checks)} checks"
    ), checks


# ---------------------------------------------------------------- per check


def schema(tool: types.Tool | None, raw: RawResult | None) -> Score:
    if tool is None or tool.output_schema is None:
        return Score(dimension="schema", value=None, detail="tool declares no outputSchema")
    if raw is None or not raw.ok or raw.is_error:
        return Score(dimension="schema", value=None, detail="no successful result to validate")
    if raw.structured is None:
        return Score(
            dimension="schema", value=0.0, detail="outputSchema declared but no structuredContent returned"
        )
    try:
        errors = sorted(
            Draft202012Validator(tool.output_schema).iter_errors(raw.structured), key=lambda e: e.path
        )
    except Exception as exc:  # an unknown type or an unresolvable $ref in the server's own schema
        return Score(dimension="schema", value=0.0, detail=f"outputSchema cannot be applied: {exc}"[:300])
    if errors:
        return Score(
            dimension="schema", value=0.0, detail=f"{len(errors)} violation(s): {errors[0].message[:200]}"
        )
    return Score(dimension="schema", value=1.0, detail="structuredContent matches outputSchema")


def correctness(task: Task, raw: RawResult | None, oracle: OracleAnswer | None) -> Score:
    if task.expect != "record":
        return Score(dimension="correctness", value=None, detail="robustness task")
    if oracle is None or not oracle.found:
        return Score(dimension="correctness", value=None, detail="oracle has no record; check the task")
    if raw is None or not raw.ok or raw.is_error:
        return Score(
            dimension="correctness",
            value=0.0,
            detail=f"call failed: {((raw.error if raw else None) or '')[:200]}",
        )
    if task.capability == "trial.lookup":
        ans = trial_answer(raw, oracle.title)
        gold_status = normalise_status(oracle.status)
        parts = {
            "id": oracle.nct_id in ans.nct_ids,
            "status": ans.status is not None and ans.status == gold_status,
            "title": ans.title_found,
        }
        value = sum(parts.values()) / len(parts)
        detail = ", ".join(f"{k} {'ok' if v else 'wrong'}" for k, v in parts.items())
        return Score(
            dimension="correctness",
            value=value,
            detail=f"{detail} (server {ans.status}, source {gold_status})",
        )
    ans_l = literature_answer(raw)
    if oracle.total is not None and oracle.total > len(oracle.pmids):
        return Score(
            dimension="correctness", value=None, detail="source has more records than the oracle fetched"
        )
    if not ans_l.pmids:
        return Score(dimension="correctness", value=0.0, detail="no PubMed IDs found in the answer")
    gold = set(oracle.pmids)
    hits = [p for p in ans_l.pmids if p in gold]
    precision = len(hits) / len(ans_l.pmids)
    strays = [p for p in ans_l.pmids if p not in gold][:5]
    detail = f"{len(hits)}/{len(ans_l.pmids)} returned records match the query window"
    if strays:
        detail += f"; not in source result: {', '.join(strays)}"
    return Score(dimension="correctness", value=precision, detail=detail)


def _days_between(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days
    except ValueError:
        return None


def freshness(task: Task, raw: RawResult | None, oracle: OracleAnswer | None) -> Score:
    if task.expect != "record" or oracle is None or not oracle.found:
        return Score(dimension="freshness", value=None, detail="not applicable")
    if raw is None or not raw.ok or raw.is_error:
        return Score(dimension="freshness", value=None, detail="no successful result")
    if task.capability == "trial.lookup":
        ans = trial_answer(raw, oracle.title)
        if not oracle.last_update:
            return Score(dimension="freshness", value=None, detail="source gives no last-update date")
        if not ans.last_update:
            return Score(
                dimension="freshness", value=None, detail="server does not state the record's last update"
            )
        lag = _days_between(oracle.last_update, ans.last_update)
        if lag is None:
            return Score(dimension="freshness", value=None, detail="unreadable date")
        if lag <= 0:
            return Score(
                dimension="freshness", value=1.0, detail=f"last update {ans.last_update} matches source"
            )
        return Score(
            dimension="freshness",
            value=0.0,
            detail=f"{lag} days behind source ({ans.last_update} vs {oracle.last_update})",
        )
    ans_l = literature_answer(raw)
    k = min(NEWEST_K, int(task.params.get("limit", 20)), len(oracle.pmids))
    if k == 0:
        return Score(dimension="freshness", value=None, detail="source has no records in the window")
    newest = oracle.pmids[:k]
    got = [p for p in newest if p in ans_l.pmids]
    missing = [p for p in newest if p not in ans_l.pmids]
    detail = f"{len(got)}/{k} of the source's newest records returned"
    if missing:
        detail += f"; missing {', '.join(missing)}"
    return Score(dimension="freshness", value=len(got) / k, detail=detail)


SOURCE_NAMES = {
    "trial.lookup": re.compile(r"clinicaltrials\.gov|clinicaltrials gov|ctgov", re.IGNORECASE),
    "literature.search": re.compile(r"pubmed|ncbi|europe ?pmc|medline", re.IGNORECASE),
}
RECORD_LINKS = {
    "trial.lookup": re.compile(r"clinicaltrials\.gov/(study|ct2/show)/NCT\d{8}", re.IGNORECASE),
    "literature.search": re.compile(
        r"pubmed\.ncbi\.nlm\.nih\.gov/\d+|doi\.org/10\.|europepmc\.org/", re.IGNORECASE
    ),
}


def attribution(task: Task, raw: RawResult | None) -> Score:
    if task.expect != "record" or raw is None or not raw.ok or raw.is_error:
        return Score(dimension="attribution", value=None, detail="not applicable")
    from .normalize import haystack

    text = haystack(raw)
    named = bool(SOURCE_NAMES[task.capability].search(text))
    linked = bool(RECORD_LINKS[task.capability].search(text))
    value = 0.5 * named + 0.5 * linked
    detail = f"source named: {'yes' if named else 'no'}; record links: {'yes' if linked else 'no'}"
    return Score(dimension="attribution", value=value, detail=detail)


# An error only counts as the right answer when it is about the input. "HTTP 403" or
# "request failed" means the server could not reach its own source, which says nothing
# about how it handles a bad input, so such checks are left unscored.
INPUT_ERROR_WORDS = re.compile(
    r"not found|no (study|studies|trial|results|records|match)|does not exist|unknown (id|nct)"
    r"|invalid (nct|id|identifier|argument|arguments|input|param|params|parameter|query|format)"
    r"|input validation|must match|expected an? (nct|valid|id)|malformed|not a valid|-32602",
    re.IGNORECASE,
)


def _error_text(raw: RawResult) -> str:
    return f"{raw.error or ''} {raw.text or ''}"


def robustness(task: Task, raw: RawResult | None) -> Score:
    if task.expect == "record":
        return Score(dimension="robustness", value=None, detail="not a robustness task")
    if raw is None:
        return Score(dimension="robustness", value=None, detail="no result")
    if not raw.ok or raw.is_error:
        message = _error_text(raw).strip()
        if INPUT_ERROR_WORDS.search(message):
            return Score(
                dimension="robustness", value=1.0, detail=f"clean error about the input: {message[:160]}"
            )
        return Score(
            dimension="robustness",
            value=None,
            detail=f"error unrelated to the input, likely an upstream failure; not scored: {message[:160]}",
        )
    if task.capability == "trial.lookup":
        ans = trial_answer(raw)
        if ans.status is not None:
            return Score(
                dimension="robustness",
                value=0.0,
                detail=f"returned a record (status {ans.status}) for an ID that does not exist",
            )
        if task.expect == "invalid_input" and not INPUT_ERROR_WORDS.search(raw.text or ""):
            return Score(dimension="robustness", value=0.5, detail="no record, but no clear error either")
        return Score(dimension="robustness", value=1.0, detail="no record returned")
    ans_l = literature_answer(raw)
    if ans_l.pmids:
        return Score(
            dimension="robustness",
            value=0.0,
            detail=f"returned {len(ans_l.pmids)} records for a query the source has none for",
        )
    return Score(dimension="robustness", value=1.0, detail="no records returned")


def stability(task: Task, first: RawResult | None, second: RawResult | None) -> Score:
    if first is None or second is None or not first.ok or not second.ok:
        return Score(dimension="stability", value=None, detail="needs two completed calls")
    if first.is_error or second.is_error:
        return Score(dimension="stability", value=None, detail="an error has no answer to compare")
    if task.capability == "trial.lookup":
        a, b = trial_answer(first), trial_answer(second)
        same = (a.status, a.nct_ids) == (b.status, b.nct_ids)
    else:
        same = literature_answer(first).pmids == literature_answer(second).pmids
    return Score(
        dimension="stability",
        value=1.0 if same else 0.0,
        detail="same answer twice" if same else "answer changed between identical calls",
    )
