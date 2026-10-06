"""Integration tests on the full 100-week plan (needs the client data in data/raw)."""
import pandas as pd
import pytest

from engine.accounting import accounting_report, rule_violations
from engine.output import SPEC_COLUMNS, fact_buy_plan_suggestions
from engine.planner import BOUGHT, FUTURE_FORECAST
from tests.conftest import needs_data

pytestmark = needs_data


def test_complete_accounting(planner):
    report = accounting_report(planner)
    assert report["passed"], report["checks"]


def test_no_rule_violations(planner):
    assert rule_violations(planner).empty


def test_every_lot_on_a_certified_factory(planner):
    lots = planner.all_lots()
    assert all(f in planner.certified[a] for a, f in zip(lots["article_id"], lots["assigned_factory"]))


def test_lots_never_mix_markets(planner):
    lots = planner.all_lots()
    for ids, market in zip(lots["pr_ids"].head(500), lots["market_destination"].head(500)):
        assert set(planner.prs.loc[ids.split(","), "market_destination"]) == {market}


def test_wholesale_forecast_never_bought_unless_exception(planner):
    out = planner.pr_outcomes().merge(planner.prs[["pr_id", "has_order", "early_buy", "last_chance"]]
                                      .reset_index(drop=True), on="pr_id")
    forecast = out[(out["channel_id"] == "01") & ~out["has_order"]]
    bought = forecast[forecast["outcome"] == BOUGHT]
    assert (bought["early_buy"] | bought["last_chance"]).all()
    excluded = out[out["outcome"] == FUTURE_FORECAST]
    assert (~excluded["has_order"] & (excluded["channel_id"] == "01")).all()


def test_backup_routing_uses_the_article_backup(planner):
    lots = planner.all_lots()
    routed = lots[lots["backup_routed"]]
    backups = planner.data.articles.set_index("article_id")["backup_factory"]
    assert (routed["assigned_factory"] == routed["article_id"].map(backups)).all()


def test_output_table_matches_spec_schema(planner):
    fact = fact_buy_plan_suggestions(planner, ["MRP-WK020"])
    assert list(fact.columns) == SPEC_COLUMNS
    assert fact["suggestion_id"].is_unique and len(fact) > 0


def test_piggyback_lots_record_their_source_window(planner):
    lots = planner.all_lots()
    pig = lots[lots["is_piggyback_applied"]]
    assert pig["piggyback_source_window"].str.startswith("WIN-").all()
