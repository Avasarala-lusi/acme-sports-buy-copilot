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
    fact = fact_buy_plan_suggestions(planner, ["MRP-WK019"])
    assert list(fact.columns) == SPEC_COLUMNS
    assert fact["suggestion_id"].is_unique and len(fact) > 0


def test_piggyback_lots_record_their_source_window(planner):
    lots = planner.all_lots()
    pig = lots[lots["is_piggyback_applied"]]
    assert pig["piggyback_source_window"].str.startswith("MRP-WK").all()


# ---- monthly buying window
def test_purchases_are_committed_only_in_buying_runs(planner):
    lots = planner.all_lots()
    buying = set(planner.buying_runs())
    assert set(lots["run_id"]) <= buying and len(buying) == 46
    po = planner.runs.set_index("run_id")["po_execution_date"].map(pd.Timestamp)
    assert all(planner.calendar.is_window(po[r]) for r in buying)


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
    assert len(review) and review["warnings"].str.len().gt(0).all()
    out = planner.pr_outcomes().set_index("pr_id")
    ids = review["pr_ids"].str.split(",").explode()
    assert set(ids)<=set(out.index)  # reviewed demand can be purchased in a later window
    fact = fact_buy_plan_suggestions(planner)
    assert not set(fact["suggestion_id"].str[4:]) & set(review["lot_id"])


def test_review_lots_list_alternatives(planner):
    lots = planner.all_lots()
    # lots sent to review because no factory in the chain had capacity
    review = lots[(lots["auto_decision"] == "Review") & lots["warnings"].str.contains("no certified factory has room")]
    assert len(review)
    assert (review["alternatives"].str.len() > 0).all()
    assert review["alternatives"].str.contains("with this lot").all()


def test_baseline_evaluation_uses_the_same_requisitions(planner):
    from engine.metrics import baseline_evaluation
    from engine.planner import BOUGHT
    ev = baseline_evaluation(planner).set_index("metric")
    n = ev.loc["Requisitions compared (same PRs, same units)"]
    assert n["baseline"] == n["our_plan"] == (planner.pr_outcomes()["outcome"] == BOUGHT).sum()
    for m in ["Backup-triggered assignments (% of PRs)", "Load spread across factories (avg weekly std, pts)",
              "Article-market lots below MOQ 300 (%)"]:
        assert m in ev.index


def test_retried_demand_is_not_bought_late_automatically(planner):
    """Demand sent to review or left unresolved is retried for visibility, but a later automatic purchase must
    still be able to start by its release date; otherwise it stays with the planner."""
    earlier = {}
    for run in planner.buying_runs():  # drafts are previews; only buying runs decide
        out = planner.results[run].outcomes
        for x in (out.itertuples() if len(out) else []):
            if x.outcome in ("PLANNER_REVIEW", "UNRESOLVED_MOQ", "UNRESOLVED_MPQ"):
                earlier.setdefault(x.pr_id, run)
    lots = planner.bought_lots()
    lots = lots[(~lots["last_chance"]) & (lots["decision_type"] == "auto")]
    late = []
    for lot in lots.itertuples():
        for p in lot.pr_ids.split(","):
            if p in earlier and planner.run_index[earlier[p]] < planner.run_index[lot.run_id]:
                if planner.rows[p]["release_primary"] < lot.production_start:
                    late.append((lot.lot_id, p))
    assert not late, late[:5]


def test_equal_release_dates_go_to_the_earliest_rdd_then_sales_value(planner):
    """Client (Oct 29): ties on the release date go to the earliest RDD, then the highest NSV, then order-backed."""
    prs = planner.prs[~planner.prs["last_chance"]]
    same = prs.groupby("release_primary").filter(lambda g: g["rdd_original"].nunique() > 1)
    g = same[same["release_primary"] == same["release_primary"].iloc[0]].sort_values("rdd_original")
    early, late = g["pr_id"].iloc[0], g["pr_id"].iloc[-1]
    assert planner.priority_key([early]) < planner.priority_key([late])
    ties = prs.groupby(["release_primary", "rdd_original"]).filter(lambda x: x["nsv"].nunique() > 1)
    t = ties[(ties["release_primary"] == ties["release_primary"].iloc[0])
             & (ties["rdd_original"] == ties["rdd_original"].iloc[0])].sort_values("nsv", ascending=False)
    assert planner.priority_key([t["pr_id"].iloc[0]]) < planner.priority_key([t["pr_id"].iloc[-1]])


def test_production_order_mpq_scope():
    """Proposed MPQ scope: one production order per article, factory and buying window, whatever the RDD spread.
    Every bought order meets MPQ unless it is a last-chance buy, market lots keep their 15-day span, and it buys
    at least as much as the 15-day MPQ bands."""
    from engine.config import load_config
    from engine.planner import Planner
    from engine.rules.quantities import mpq_for
    cfg = load_config()
    cfg["quantities"]["mpq_scope"] = "purchase"
    pl = Planner(config=cfg)
    pl.plan_all()
    assert rule_violations(pl).empty
    lots = pl.bought_lots()
    orders = lots.groupby(["run_id", "article_id", "assigned_factory"]).agg(
        qty=("consolidated_qty", "sum"), category=("category", "first"), last_chance=("last_chance", "any"))
    short = orders[orders["qty"] < orders["category"].map(lambda c: mpq_for(c, cfg["quantities"]["mpq"]))]
    assert short["last_chance"].all()
    base = Planner()
    base.plan_all()
    assert lots["consolidated_qty"].sum() >= base.bought_lots()["consolidated_qty"].sum()
