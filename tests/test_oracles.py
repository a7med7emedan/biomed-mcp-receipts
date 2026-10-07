import json

import httpx
import pytest

from biomed_mcp_receipts.models import Task
from biomed_mcp_receipts.oracles import CassetteMissing, OracleHTTP, Oracles
from biomed_mcp_receipts.oracles.http import cassette_name, public_url

pytestmark = pytest.mark.anyio


def task(**kw):
    base = dict(id="t", capability="trial.lookup", params={"nct_id": "NCT90000001"})
    return Task(**{**base, **kw})


async def test_replay_trial(world_oracles):
    ans = await world_oracles.answer(task())
    assert ans.found and ans.status == "RECRUITING" and ans.last_update == "2026-09-15"
    assert ans.release == "2026-10-06T09:00:00"
    assert len(ans.body_sha256) == 64


async def test_replay_not_found(world_oracles):
    ans = await world_oracles.answer(task(params={"nct_id": "NCT00000000"}, expect="not_found"))
    assert ans.found is False


async def test_invalid_input_needs_no_oracle(world_oracles):
    assert await world_oracles.answer(task(params={"nct_id": "NCT1"}, expect="invalid_input")) is None


async def test_replay_literature(world_oracles):
    t = Task(
        id="l",
        capability="literature.search",
        params={"query": "synthetic lrrk2 autophagy", "since": "2026-01-01", "until": "2026-06-30"},
    )
    ans = await world_oracles.answer(t)
    assert ans.pmids[0] == "99000012" and ans.total == 12 and ans.release == "2026/10/07 04:00"


async def test_answers_are_cached_per_task(world_oracles):
    a = await world_oracles.answer(task())
    b = await world_oracles.answer(task())
    assert a is b


async def test_missing_cassette_raises(tmp_path):
    oracles = Oracles(OracleHTTP(mode="replay", cassette_dir=tmp_path))
    with pytest.raises(CassetteMissing):
        await oracles.answer(task(params={"nct_id": "NCT12345678"}))


def test_public_url_drops_secrets_and_sorts():
    url = "https://eutils.ncbi.nlm.nih.gov/x?term=a&api_key=SECRET&db=pubmed"
    assert public_url(url) == "https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&term=a"
    assert cassette_name(url) == cassette_name("https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&term=a")


async def test_record_then_replay(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/version"):
            return httpx.Response(200, json={"dataTimestamp": "2026-10-01T00:00:00"})
        body = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT11111111", "briefTitle": "T"},
                "statusModule": {"overallStatus": "COMPLETED"},
            }
        }
        return httpx.Response(200, json=body)

    http = OracleHTTP(
        mode="record",
        cassette_dir=tmp_path,
        transport=httpx.MockTransport(handler),
        min_interval={"clinicaltrials.gov": 0.0},
    )
    recorded = await Oracles(http).answer(task(params={"nct_id": "NCT11111111"}))
    await http.aclose()
    assert recorded.status == "COMPLETED" and len(seen) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2

    replayed = await Oracles(OracleHTTP(mode="replay", cassette_dir=tmp_path)).answer(
        task(params={"nct_id": "NCT11111111"})
    )
    assert replayed.status == recorded.status and replayed.body_sha256 == recorded.body_sha256
    assert json.loads((next(tmp_path.glob("*.json"))).read_text())["url"].startswith(
        "https://clinicaltrials.gov"
    )


async def test_retries_on_503(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, text="{}")

    http = OracleHTTP(mode="live", transport=httpx.MockTransport(handler), min_interval={})
    r = await http.get("https://example.org/x")
    await http.aclose()
    assert r.status == 200 and calls["n"] == 2


def test_record_mode_needs_a_directory():
    with pytest.raises(ValueError):
        OracleHTTP(mode="record")
