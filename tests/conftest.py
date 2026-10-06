import pytest

from engine.config import ROOT
from engine.data_loader import TABLES

RAW = ROOT / "data" / "raw"
needs_data = pytest.mark.skipif(
    not all((RAW / f).exists() for f in TABLES.values()),
    reason="client data not present in data/raw (it is not committed)",
)


@pytest.fixture(scope="session")
def planner():
    from engine.output import get_planner
    return get_planner()
