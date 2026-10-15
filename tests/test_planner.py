"""Integration tests on the full 100-week plan (needs the client data in data/raw)."""
import pandas as pd
import pytest

from engine.accounting import accounting_report, overload_without_last_chance, rule_violations
from engine.output import SPEC_COLUMNS, fact_buy_plan_suggestions
from engine.planner import BOUGHT, DRAFT, FUTURE_FORECAST, PLANNER_REVIEW
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


def test_backup_routing_follows_the_configured_chain(planner):
    lots = planner.all_lots()
    routed = lots[lots["backup_routed"]]
    assert len(routed)
    assert all(f in planner.backup_chain[a] for a, f in zip(routed["article_id"], routed["assigned_factory"]))
    if planner.cfg["backup_source"] == "factory_chain":
        assert planner.backup_chain[routed["article_id"].iloc[0]][-1] == "ACME-CN04"  # data v5 last resort
        assert (routed["assigned_factory"] != routed["primary_factory"]).all()


def test_output_table_matches_spec_schema(planner):
    fact = fact_buy_plan_suggestions(planner, ["MRP-WK020"])
    assert list(fact.columns) == SPEC_COLUMNS
    assert fact["suggestion_id"].is_unique and len(fact) > 0


def test_piggyback_lots_record_their_source_window(planner):
    lots = planner.all_lots()
    pig = lots[lots["is_piggyback_applied"]]
    assert pig["piggyback_source_window"].str.startswith("WIN-").all()


# ---- monthly buying window
def test_purchases_are_committed_only_in_buying_runs(planner):
    lots = planner.all_lots()
    buying = set(planner.buying_runs())
    assert set(lots["run_id"]) <= buying and len(buying) == 23
    po = planner.runs.set_index("run_id")["po_execution_date"].map(pd.Timestamp)
    assert all(15 <= po[r].day <= 21 for r in buying)


def test_draft_weeks_preview_the_next_window_without_committing(planner):
    r = planner.run_result("MRP-WK021")
    assert not r.is_buying_run and len(r.lots) and (r.lots["plan_status"] == DRAFT).all()
    committed = set(planner.all_lots()["lot_id"])
    assert not committed & set(r.lots["lot_id"])
    decided = planner.pr_outcomes().set_index("pr_id")
    drafted = r.lots["pr_ids"].str.split(",").explode()
    # demand in a draft is bought later, in a buying run, or still has another outcome; never by the draft
    assert not (decided.loc[drafted, "decided_in_run"] == "MRP-WK021").any()


# ---- capacity is checked with the new lot included
def test_no_factory_week_over_limit_except_last_chance(planner):
    assert overload_without_last_chance(planner) <= planner.cfg["capacity"]["hard_limit_pct"] + 1e-6


def test_lots_record_load_including_the_lot(planner):
    lots = planner.all_lots()
    assert (lots["util_after_pct"] >= lots["util_before_pct"]).all()
    bought = lots[(lots["auto_decision"] == "Buy") & ~lots["last_chance"]]
    assert (bought["util_after_pct"] <= planner.cfg["capacity"]["hard_limit_pct"] + 0.05).all()


def test_review_lots_are_not_bought_or_exported(planner):
    lots = planner.all_lots()
    review = lots[lots["auto_decision"] == "Review"]
    assert len(review) and (review["util_after_pct"] > planner.cfg["capacity"]["hard_limit_pct"] - 0.05).all()  # stored to 1 dp
    out = planner.pr_outcomes().set_index("pr_id")
    ids = review["pr_ids"].str.split(",").explode()
    assert (out.loc[ids, "outcome"] == PLANNER_REVIEW).all()
    fact = fact_buy_plan_suggestions(planner)
    assert not set(fact["suggestion_id"].str[4:]) & set(review["lot_id"])
