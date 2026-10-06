import pytest

from engine.config import ROOT, load_config
from engine.data_loader import TABLES, load_data

RAW = ROOT / "data" / "raw"
needs_data = pytest.mark.skipif(
    not all((RAW / f).exists() for f in TABLES.values()),
    reason="client data not present in data/raw (it is not committed)",
)


def test_config_has_spec_thresholds():
    cfg = load_config()
    assert cfg["quantities"]["moq_per_market"] == 300
    assert cfg["capacity"]["backup_threshold_pct"] == 85
    assert cfg["grouping"]["window_days"] == 15


@needs_data
def test_loads_all_tables():
    data = load_data()
    assert set(data.tables) == set(TABLES)
    assert len(data.runs) == 100
    assert len(data.prs) == 24_962


@needs_data
def test_channel_ids_normalised():
    data = load_data()
    assert set(data.prs["channel_id"]) == {"01", "02"}


@needs_data
def test_known_data_issues_reported():
    data = load_data()
    assert any("above 100% capacity" in i for i in data.issues)
    assert not any("uncertified" in i for i in data.issues)
