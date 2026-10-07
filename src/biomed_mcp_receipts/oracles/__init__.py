"""Oracles ask the primary source directly and return the gold answer plus its release."""

from __future__ import annotations

from ..models import OracleAnswer, Task
from .clinicaltrials import ClinicalTrialsOracle
from .http import CassetteMissing, OracleHTTP, write_cassette
from .pubmed import PubMedOracle

__all__ = [
    "CassetteMissing",
    "ClinicalTrialsOracle",
    "OracleHTTP",
    "Oracles",
    "PubMedOracle",
    "write_cassette",
]


class Oracles:
    """One gold answer per task per run, cached so every server is scored on the same evidence."""

    def __init__(self, http: OracleHTTP) -> None:
        self.http = http
        self.trials = ClinicalTrialsOracle(http)
        self.pubmed = PubMedOracle(http)
        self._cache: dict[str, OracleAnswer | None] = {}

    async def answer(self, task: Task) -> OracleAnswer | None:
        if task.id not in self._cache:
            self._cache[task.id] = await self._ask(task)
        return self._cache[task.id]

    async def _ask(self, task: Task) -> OracleAnswer | None:
        if task.expect == "invalid_input":
            return None  # nothing to look up: the input itself is malformed
        p = task.params
        if task.capability == "trial.lookup":
            return await self.trials.trial(p["nct_id"])
        if task.capability == "literature.search":
            return await self.pubmed.search(p["query"], p["since"], p["until"])
        raise ValueError(f"no oracle for capability {task.capability}")

    async def aclose(self) -> None:
        await self.http.aclose()
