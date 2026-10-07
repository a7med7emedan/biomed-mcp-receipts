"""Turn a server's free-form answer into a comparable answer.

Servers answer in their own shapes: structured JSON, JSON inside a text block, or prose.
Extraction looks at structured content first, then JSON found in text, then the text itself,
so one extractor serves every server and adapters only have to map the request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from typing import Any

from .models import LiteratureAnswer, RawResult, TrialAnswer

NCT_RE = re.compile(r"\bNCT\d{8}\b")
PMID_RES = (
    re.compile(r"\bPMID:?\s*(\d{5,9})\b", re.IGNORECASE),
    re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{5,9})"),
)
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?")

TRIAL_STATUSES = (
    "ACTIVE_NOT_RECRUITING",
    "NOT_YET_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "RECRUITING",
    "COMPLETED",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
    "AVAILABLE",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
    "WITHHELD",
    "UNKNOWN",
)

# Trial-level status keys, most specific first. A bare "status" key is only a fallback, because
# ClinicalTrials.gov also gives every site a status (locations[].status) that is not the trial's.
PRIMARY_STATUS_KEYS = {"overallstatus", "overall_status", "recruitmentstatus", "recruitment_status"}
FALLBACK_STATUS_KEYS = {"status"}
# In prose, a status only counts right after a label such as "Overall status:" or "Status -".
STATUS_LABEL_RE = re.compile(
    r"(?:overall|recruitment|trial|study)?\s*status\s*[:=\-]\s*([A-Za-z ,_]{3,40})", re.I
)
LAST_UPDATE_KEYS = {
    "lastupdatepostdate",
    "last_update_post_date",
    "lastupdated",
    "last_updated",
    "last_update",
    "lastupdatepostdatestruct",
}
PMID_KEYS = {"pmid", "pmids"}


def normalise_status(value: Any) -> str | None:
    """Map 'Active, not recruiting' and 'ACTIVE_NOT_RECRUITING' to one spelling."""
    if not isinstance(value, str):
        return None
    key = re.sub(r"[^A-Z]+", "_", value.upper()).strip("_")
    return key if key in TRIAL_STATUSES else None


def normalise_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def haystack(raw: RawResult) -> str:
    parts = [raw.text or ""]
    if raw.structured is not None:
        parts.append(json.dumps(raw.structured, sort_keys=True, default=str, ensure_ascii=False))
    return "\n".join(parts)


def json_documents(raw: RawResult) -> Iterator[Any]:
    """Structured content, then any JSON document carried inside the text."""
    if raw.structured is not None:
        yield raw.structured
    text = (raw.text or "").strip()
    if not text:
        return
    for block in [text, *text.split("\n\n")]:
        block = block.strip()
        if block[:1] in "[{":
            try:
                yield json.loads(block)
            except ValueError:
                continue


def walk(obj: Any) -> Iterator[tuple[str, Any]]:
    """Every (key, value) pair in a nested JSON value."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), v
            yield from walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk(item)


def _unique(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        seen.setdefault(v, None)
    return list(seen)


def _first_date(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("date")
    if isinstance(value, str) and DATE_RE.match(value):
        return value[:10]
    return None


def _status_from_prose(text: str) -> str | None:
    """The first status that follows a status label, e.g. "Overall status: Active, not recruiting"."""
    for match in STATUS_LABEL_RE.finditer(text):
        words = re.sub(r"[^A-Z]+", "_", match.group(1).upper()).strip("_")
        # longest status first, so ACTIVE_NOT_RECRUITING wins over RECRUITING
        for candidate in sorted(TRIAL_STATUSES, key=len, reverse=True):
            if words == candidate or words.startswith(candidate + "_"):
                return candidate
    return None


def trial_answer(raw: RawResult, oracle_title: str | None = None) -> TrialAnswer:
    text = haystack(raw)
    primary = fallback = last_update = None
    for doc in json_documents(raw):
        for key, value in walk(doc):
            k = key.lower()
            if primary is None and k in PRIMARY_STATUS_KEYS:
                primary = normalise_status(value)
            if fallback is None and k in FALLBACK_STATUS_KEYS:
                fallback = normalise_status(value)
            if last_update is None and k in LAST_UPDATE_KEYS:
                last_update = _first_date(value)
    status = primary or fallback or _status_from_prose(raw.text or "")
    title_found = bool(oracle_title) and normalise_text(oracle_title or "") in normalise_text(text)
    return TrialAnswer(
        nct_ids=_unique(NCT_RE.findall(text)),
        status=status,
        title_found=title_found,
        last_update=last_update,
    )


def literature_answer(raw: RawResult) -> LiteratureAnswer:
    found: list[str] = []
    for doc in json_documents(raw):
        for key, value in walk(doc):
            if key.lower() in PMID_KEYS:
                values = value if isinstance(value, list) else [value]
                found.extend(str(v) for v in values if re.fullmatch(r"\d{5,9}", str(v)))
    if not found:
        text = haystack(raw)
        for rx in PMID_RES:
            found.extend(rx.findall(text))
    return LiteratureAnswer(pmids=_unique(found))
