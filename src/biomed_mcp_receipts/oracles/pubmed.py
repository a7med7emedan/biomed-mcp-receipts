"""Gold answers for literature.search, straight from NCBI E-utilities."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from urllib.parse import urlencode

from ..models import OracleAnswer
from .http import OracleHTTP

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SOURCE = "NCBI E-utilities (PubMed)"
ORACLE_RETMAX = 200


def _pdat(day: str) -> str:
    return day.replace("-", "/")


class PubMedOracle:
    def __init__(self, http: OracleHTTP) -> None:
        self.http = http
        self._release: str | None = None

    def _url(self, endpoint: str, params: dict[str, str]) -> str:
        params = {**params, "tool": "biomed-mcp-receipts"}
        key = os.environ.get("NCBI_API_KEY")
        if key:
            params["api_key"] = key
        return f"{BASE}/{endpoint}?{urlencode(sorted(params.items()))}"

    async def release(self) -> str | None:
        """When PubMed says it last updated."""
        if self._release is None:
            r = await self.http.get(self._url("einfo.fcgi", {"db": "pubmed", "retmode": "json"}))
            if r.status == 200:
                data = r.json()
                info = data.get("einforesult", {}) if isinstance(data, dict) else {}
                dbinfo = info.get("dbinfo")
                if isinstance(dbinfo, list):
                    dbinfo = dbinfo[0] if dbinfo else {}
                if isinstance(dbinfo, dict):
                    self._release = dbinfo.get("lastupdate")
        return self._release

    async def search(self, query: str, since: str, until: str) -> OracleAnswer:
        """Every PMID matching the query in the date window, newest publication first."""
        url = self._url(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": str(ORACLE_RETMAX),
                "sort": "pub_date",
                "datetype": "pdat",
                "mindate": _pdat(since),
                "maxdate": _pdat(until),
            },
        )
        r = await self.http.get(url)
        if r.status != 200:
            raise RuntimeError(f"E-utilities answered {r.status} for {query!r}")
        data = r.json()
        result = data.get("esearchresult", {}) if isinstance(data, dict) else {}
        pmids = [str(p) for p in result.get("idlist", [])]
        total = int(result.get("count", len(pmids)))
        return OracleAnswer(
            source=SOURCE,
            url=r.url,
            release=await self.release(),
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            found=total > 0,
            body_sha256=r.sha256,
            pmids=pmids,
            total=total,
        )
