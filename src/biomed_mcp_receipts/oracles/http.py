"""HTTP for oracles, with three modes.

live    ask the primary source, politely rate limited per host
record  live, and save every response as a cassette file
replay  answer only from cassette files; never touch the network

Cassettes keep CI independent of NCBI or ClinicalTrials.gov being up, and let anyone rerun
a past check against exactly the evidence it was scored on.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import anyio
import httpx

Mode = Literal["live", "record", "replay"]
SECRET_PARAMS = {"api_key"}
USER_AGENT = "biomed-mcp-receipts/0.1 (+https://github.com/a7med7emedan/biomed-mcp-receipts)"


class CassetteMissing(RuntimeError):
    """Replay mode was asked for a response nobody recorded."""


@dataclass
class Response:
    url: str
    status: int
    body: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body.encode()).hexdigest()

    def json(self) -> object:
        return json.loads(self.body)


def public_url(url: str) -> str:
    """The URL with secrets removed: what receipts show and what cassettes are keyed by."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in SECRET_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(query)), ""))


def cassette_name(url: str) -> str:
    return hashlib.sha256(public_url(url).encode()).hexdigest()[:20] + ".json"


@dataclass
class OracleHTTP:
    mode: Mode = "live"
    cassette_dir: Path | None = None
    min_interval: dict[str, float] = field(default_factory=dict)
    timeout: float = 30.0
    transport: httpx.AsyncBaseTransport | None = None
    _last: dict[str, float] = field(default_factory=dict)
    _client: httpx.AsyncClient | None = None

    def __post_init__(self) -> None:
        if self.mode in ("record", "replay") and self.cassette_dir is None:
            raise ValueError(f"mode {self.mode!r} needs a cassette directory")
        if not self.min_interval:
            ncbi = 0.11 if os.environ.get("NCBI_API_KEY") else 0.34
            self.min_interval = {"eutils.ncbi.nlm.nih.gov": ncbi, "clinicaltrials.gov": 0.2}

    async def get(self, url: str) -> Response:
        if self.mode == "replay":
            return self._read_cassette(url)
        response = await self._fetch(url)
        if self.mode == "record":
            self._write_cassette(response)
        return response

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _fetch(self, url: str) -> Response:
        host = urlsplit(url).netloc
        wait = self.min_interval.get(host, 0.0) - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            await anyio.sleep(wait)
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout, headers={"User-Agent": USER_AGENT}, transport=self.transport
            )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                r = await self._client.get(url)
                self._last[host] = time.monotonic()
                if r.status_code in (429, 502, 503, 504) and attempt < 2:
                    await anyio.sleep(1.5 * (attempt + 1))
                    continue
                return Response(url=public_url(url), status=r.status_code, body=r.text)
            except httpx.HTTPError as exc:
                last_error = exc
                await anyio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"oracle request failed after 3 attempts: {public_url(url)}") from last_error

    def _path(self, url: str) -> Path:
        assert self.cassette_dir is not None
        return self.cassette_dir / cassette_name(url)

    def _read_cassette(self, url: str) -> Response:
        path = self._path(url)
        if not path.exists():
            raise CassetteMissing(f"no cassette for {public_url(url)} ({path.name})")
        data = json.loads(path.read_text())
        return Response(url=data["url"], status=data["status"], body=data["body"])

    def _write_cassette(self, response: Response) -> None:
        assert self.cassette_dir is not None
        self.cassette_dir.mkdir(parents=True, exist_ok=True)
        record = {"url": response.url, "status": response.status, "body": response.body}
        self._path(response.url).write_text(json.dumps(record, indent=1, sort_keys=True))


def write_cassette(cassette_dir: Path, url: str, status: int, body: object) -> Path:
    """Write one cassette by hand. Used by tests and by the fixture generator."""
    cassette_dir.mkdir(parents=True, exist_ok=True)
    text = body if isinstance(body, str) else json.dumps(body, sort_keys=True)
    path = cassette_dir / cassette_name(url)
    record = {"url": public_url(url), "status": status, "body": text}
    path.write_text(json.dumps(record, indent=1, sort_keys=True))
    return path
