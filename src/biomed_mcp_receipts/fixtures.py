"""Build replay cassettes for the synthetic world, shaped like the real APIs' responses.

The planted-fault server and these cassettes come from the same world file, so a planted server
with no faults must score 1.0 on every dimension that applies. That is the bench's self-test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .oracles.clinicaltrials import BASE as CT_BASE
from .oracles.http import write_cassette
from .oracles.pubmed import BASE as PM_BASE
from .oracles.pubmed import ORACLE_RETMAX
from .planted import load_world


def _pm_url(endpoint: str, params: dict[str, str]) -> str:
    params = {**params, "tool": "biomed-mcp-receipts"}
    return f"{PM_BASE}/{endpoint}?{urlencode(sorted(params.items()))}"


def build_world_cassettes(cassette_dir: Path, world: dict[str, Any] | None = None) -> list[Path]:
    world = world or load_world()
    written = [
        write_cassette(
            cassette_dir,
            f"{CT_BASE}/version",
            200,
            {"apiVersion": "2.0.5", "dataTimestamp": world["release"]["ctgov"]},
        ),
        write_cassette(
            cassette_dir,
            _pm_url("einfo.fcgi", {"db": "pubmed", "retmode": "json"}),
            200,
            {"einforesult": {"dbinfo": [{"dbname": "pubmed", "lastupdate": world["release"]["pubmed"]}]}},
        ),
        write_cassette(
            cassette_dir,
            f"{CT_BASE}/studies/NCT00000000?format=json",
            404,
            {"message": "No study found for NCT00000000"},
        ),
    ]
    for t in world["trials"]:
        body = {
            "protocolSection": {
                "identificationModule": {"nctId": t["nct_id"], "briefTitle": t["title"]},
                "statusModule": {
                    "overallStatus": t["overall_status"],
                    "lastUpdatePostDateStruct": {"date": t["last_update_post_date"], "type": "ACTUAL"},
                },
            },
            "hasResults": False,
        }
        written.append(
            write_cassette(cassette_dir, f"{CT_BASE}/studies/{t['nct_id']}?format=json", 200, body)
        )
    for q in world["literature"]:
        ids = [r["pmid"] for r in q["records"]]
        params = {
            "db": "pubmed",
            "term": q["query"],
            "retmode": "json",
            "retmax": str(ORACLE_RETMAX),
            "sort": "pub_date",
            "datetype": "pdat",
            "mindate": q["since"].replace("-", "/"),
            "maxdate": q["until"].replace("-", "/"),
        }
        body = {
            "esearchresult": {"count": str(len(ids)), "retmax": str(len(ids)), "retstart": "0", "idlist": ids}
        }
        written.append(write_cassette(cassette_dir, _pm_url("esearch.fcgi", params), 200, body))
    return written
