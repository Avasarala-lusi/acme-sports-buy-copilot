import pytest

from engine.config import load_config
from engine.data_loader import TABLES, load_data
from tests.conftest import needs_data


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
