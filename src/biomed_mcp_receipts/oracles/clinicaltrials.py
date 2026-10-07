"""Gold answers for trial.lookup, straight from the ClinicalTrials.gov v2 API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import OracleAnswer
from .http import OracleHTTP

BASE = "https://clinicaltrials.gov/api/v2"
SOURCE = "ClinicalTrials.gov API v2"


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


class ClinicalTrialsOracle:
    def __init__(self, http: OracleHTTP) -> None:
        self.http = http
        self._release: str | None = None

    async def release(self) -> str | None:
        """The data timestamp ClinicalTrials.gov reports for its current snapshot."""
        if self._release is None:
            r = await self.http.get(f"{BASE}/version")
            if r.status == 200:
                data = r.json()
                if isinstance(data, dict):
                    self._release = str(data.get("dataTimestamp") or data.get("apiVersion") or "")
        return self._release or None

    async def trial(self, nct_id: str) -> OracleAnswer:
        url = f"{BASE}/studies/{nct_id}?format=json"
        r = await self.http.get(url)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        release = await self.release()
        if r.status == 404:
            return OracleAnswer(
                source=SOURCE, url=r.url, release=release, retrieved_at=now, found=False, body_sha256=r.sha256
            )
        if r.status != 200:
            raise RuntimeError(f"ClinicalTrials.gov answered {r.status} for {nct_id}")
        data = r.json()
        proto = _get(data, "protocolSection") or {}
        return OracleAnswer(
            source=SOURCE,
            url=r.url,
            release=release,
            retrieved_at=now,
            found=True,
            body_sha256=r.sha256,
            nct_id=_get(proto, "identificationModule", "nctId"),
            title=_get(proto, "identificationModule", "briefTitle"),
            status=_get(proto, "statusModule", "overallStatus"),
            last_update=_get(proto, "statusModule", "lastUpdatePostDateStruct", "date"),
        )
