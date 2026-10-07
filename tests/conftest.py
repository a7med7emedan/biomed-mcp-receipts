from __future__ import annotations

from pathlib import Path

import pytest

from biomed_mcp_receipts.fixtures import build_world_cassettes
from biomed_mcp_receipts.oracles import OracleHTTP, Oracles

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def world_cassettes(tmp_path: Path) -> Path:
    directory = tmp_path / "cassettes"
    build_world_cassettes(directory)
    return directory


@pytest.fixture
def world_oracles(world_cassettes: Path) -> Oracles:
    return Oracles(OracleHTTP(mode="replay", cassette_dir=world_cassettes))
