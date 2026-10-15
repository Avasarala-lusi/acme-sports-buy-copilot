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
    assert len(data.prs) == 25_141  # data v5
    assert data.prs["customer_id"].notna().all()


@needs_data
def test_channel_ids_normalised():
    data = load_data()
    assert set(data.prs["channel_id"]) == {"01", "02"}


@needs_data
def test_known_data_issues_reported():
    data = load_data()
    assert any("above 100% capacity" in i for i in data.issues)
    assert not any("uncertified" in i for i in data.issues)


@needs_data
def test_all_known_findings_are_reported():
    issues = " ".join(load_data().issues)
    for text in ["above 100% capacity", "no loops and ends at ACME-CN04", "backups differ"]:
        assert text in issues, text
    # fixed in data v5: every order has a customer record, C-rated customers have orders, no backup loop
    for text in ["no customer record", "C-rated customers have no sales orders", "form a loop"]:
        assert text not in issues, text


def test_backup_loop_is_detected():
    import pandas as pd
    from engine.data_loader import AcmeData, _backup_findings
    factories = pd.DataFrame({"factory_id": ["A", "B", "C"], "backup_factory": ["B", "A", "A"]})
    articles = pd.DataFrame({"article_id": ["X"], "primary_factory": ["A"], "backup_factory": ["B"]})
    found = " ".join(_backup_findings(AcmeData({"factories": factories, "articles": articles})))
    assert "A → B → A" in found
