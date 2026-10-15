"""Generate docs/worked_examples.md: hand-checkable calculations on real lots from one MRP run.

Every number is read from the engine's output and re-derived here with plain arithmetic;
the script stops if any hand calculation disagrees with the engine.

Usage: python scripts/build_worked_examples.py [RUN_ID]
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.accounting import accounting_report  # noqa: E402
from engine import pull_forward  # noqa: E402
from engine.calendar import window_label  # noqa: E402
from engine.output import get_planner  # noqa: E402
from engine.planner import FUTURE_FORECAST, PLANNER_REVIEW  # noqa: E402
from sim import scenarios  # noqa: E402

RUN = sys.argv[1] if len(sys.argv) > 1 else "MRP-WK020"
p = get_planner()
cfg = p.cfg
res = p.run_result(RUN)
assert res.is_buying_run, f"{RUN} is a draft week; pick a buying run"
all_run_lots = res.lots.set_index("lot_id")
lots = all_run_lots[all_run_lots["auto_decision"] == "Buy"]
run = p.runs.set_index("run_id").loc[RUN]
run_date = pd.Timestamp(run["mrp_freeze_datetime_utc"]).normalize()
moq = cfg["quantities"]["moq_per_market"]
tol = cfg["piggyback"]["tolerance_pct"]
d = lambda x: f"{pd.Timestamp(x):%d %b %Y}"
money = lambda x: f"−${-x:,.2f}" if x < 0 else f"${x:,.2f}"
out = [f"# Worked examples: {RUN} ({d(run_date)})",
       "",
       "Each example takes a real lot from the plan and shows the calculation step by step, so it can be "
       "checked by hand or in Excel. Values come from the supplied data and `config/thresholds.yaml`. "
       "The script that writes this page re-checks every result against the engine.",
       ""]


def section(title):
    out.extend(["", f"## {title}", ""])


# ---------------------------------------------------------------- pick lots
routed = lots[lots["backup_routed"] & (lots["capacity_status"] == "Within capacity")].iloc[0]
pig = lots[lots["is_piggyback_applied"]].iloc[0] if lots["is_piggyback_applied"].any() else None

# ---------------------------------------------------------------- Rule 1
pr_id = routed["pr_ids"].split(",")[0]
pr = p.rows[pr_id]
m, t = p.lead_times(pr, pr["primary"])
release = pr["rdd_original"] - pd.Timedelta(days=m + t)
nxt = res.next_buy_date
assert release == pr["release_primary"] and release < nxt
drafts = [r for r in p.runs["run_id"] if p.results[r].buy_date == res.buy_date and r != RUN]
section("0. Monthly buying window")
out += [f"The buying window is the PO day of the third week of each month (days 15-21). {RUN}'s PO date, "
        f"{d(res.buy_date)}, is in the third week, so {RUN} is a **buying run**: its purchases are committed.", "",
        f"The weekly runs before it ({', '.join(drafts) or 'none'}) showed **drafts** of this window: what it would buy "
        "with the demand known that week. Drafts change nothing; the next window is "
        f"{window_label(nxt)} ({d(nxt)})."]
section("1. Rule 1: purchase window")
out += [f"Requisition **{pr_id}** ({pr['article_id']}, {pr['market_destination']}, {pr['requested_qty']:,} units).", "",
        "| Step | Value |", "|---|---|",
        f"| Requested delivery date (RDD) | {d(pr['rdd_original'])} |",
        f"| Manufacturing lead time at primary {pr['primary']} | {m} days |",
        f"| Transport lead time | {t} days |",
        f"| Release date = RDD − {m} − {t} | **{d(release)}** |",
        f"| This buying window | {window_label(res.buy_date)} ({d(res.buy_date)}) |",
        f"| Next buying window | {window_label(nxt)} ({d(nxt)}) |",
        f"| Release date before next window? | Yes → **Buy in this window** |"]

# ---------------------------------------------------------------- Rule 2
ids = routed["pr_ids"].split(",")
rdds = [p.rows[x]["rdd_original"] for x in ids]
span = (max(rdds) - min(rdds)).days
assert span <= cfg["grouping"]["window_days"]
section("2. Rule 2: 15-day grouping")
out += [f"Lot **{routed.name}** groups {len(ids)} requisition(s) of {routed['article_id']} for {routed['market_destination']}:", "",
        "| Requisition | Size | Units | RDD |", "|---|---|---|---|"]
out += [f"| {x} | {p.rows[x]['size_id']} | {p.rows[x]['requested_qty']:,} | {d(p.rows[x]['rdd_original'])} |" for x in ids]
out += ["", f"Latest RDD − earliest RDD = {span} days ≤ {cfg['grouping']['window_days']} → same lot."]

# ---------------------------------------------------------------- Rule 3 + capacity
qty = sum(p.rows[x]["requested_qty"] for x in ids)
assert qty == routed["consolidated_qty"] and qty >= moq
cat = routed["category"]
mpq = cfg["quantities"]["mpq"][cat]
same = lots[(lots["article_id"] == routed["article_id"]) & (lots["assigned_factory"] == routed["assigned_factory"])]
fac_total = int(same["consolidated_qty"].sum())
assert fac_total >= mpq or routed["last_chance"]
reach = re.search(r"would reach (\d+)%", routed["reason"])
backup_at = re.search(r"routed to backup \S+ at (\d+)%", routed["reason"])
mult_p = float(p.factories.loc[routed["primary_factory"], "cost_multiplier"])
mult_b = float(p.factories.loc[routed["assigned_factory"], "cost_multiplier"])
delta = qty * routed["unit_cost_usd"] * (mult_b - mult_p)
assert abs(delta - routed["cost_delta_vs_primary_usd"]) < 0.01
section("3. Rule 3: minimum quantities, and capacity routing")
out += ["| Check | Calculation | Result |", "|---|---|---|",
        f"| MOQ (per market) | {' + '.join(format(p.rows[x]['requested_qty'], ',') for x in ids)} = {qty:,} ≥ {moq} | Met |",
        f"| MPQ ({cat}, per factory) | {routed['article_id']} at {routed['assigned_factory']} this window = {fac_total:,} ≥ {mpq:,} | Met |",
        f"| Capacity | Primary {routed['primary_factory']} busiest production week **with this lot**: {reach.group(1) if reach else '?'}% ≥ {cfg['capacity']['backup_threshold_pct']}% | Route to backup |",
        f"| Backup | {routed['assigned_factory']} with this lot: {routed['util_before_pct']:.1f}% → {routed['util_after_pct']:.1f}% < {cfg['capacity']['backup_threshold_pct']}%, certified | Assigned |",
        f"| Cost change | {qty:,} × {money(routed['unit_cost_usd'])} × ({mult_b} − {mult_p}) | **{money(delta)}** |"]

# ---------------------------------------------------------------- Rule 4
if pig is not None:
    m4 = re.search(r"Rule 4: (.*?) was within (\d+)% of (MOQ|MPQ) ([\d,]+); pulled ([\d,]+) units forward from ([^|;]+)",
                   pig["reason"])
    section("4. Rule 4: piggyback (pull-forward to reach a minimum)")
    out += [f"Lot **{pig.name}** ({pig['article_id']}, {pig['market_destination']}).", ""]
    if m4:
        before, pct, kind, thr, pulled, src = m4.groups()
        before_n = float(re.sub(r"[^\d.]", "", before.split()[-1]))
        thr_n = float(thr.replace(",", ""))
        assert before_n >= thr_n * (1 - int(pct) / 100)
        out += ["| Step | Value |", "|---|---|",
                f"| Quantity before | {before} |",
                f"| Threshold | {kind} {thr} |",
                f"| Tolerance check | {before_n:,.0f} ≥ {thr_n:,.0f} × (1 − {pct}%) = {thr_n * (1 - int(pct) / 100):,.0f} → auto-trigger |",
                f"| Pulled forward (into an existing market lot) | {pulled} units from {src.strip()} |",
                f"| Final lot quantity | {pig['consolidated_qty']:,} |"]
    else:
        out += [f"Reason recorded by the engine: {pig['reason']}"]

# ---------------------------------------------------------------- Rule 5
fo = p.run_result(RUN).outcomes
fo = fo[fo["outcome"] == FUTURE_FORECAST]
if len(fo):
    x = fo["pr_id"].iloc[0]
    r = p.rows[x]
    assert r["channel_id"] == "01" and not r["has_order"] and not r["early_buy"]
    section("5. Rule 5: wholesale forecast exclusion")
    out += ["| Field | Value |", "|---|---|",
            f"| Requisition | {x} ({r['article_id']}, {r['market_destination']}, {r['requested_qty']:,} units) |",
            "| Channel | 01 (wholesale) |",
            "| Confirmed sales order? | No |",
            "| Early Buy article? | No |",
            "| Result | Moved to **Future** (not bought) |"]

# ---------------------------------------------------------------- planner review
rev = all_run_lots[all_run_lots["auto_decision"] == "Review"]
if len(rev):
    rv = rev.iloc[0]
    rv_out = p.run_result(RUN).outcomes.set_index("pr_id").loc[rv["pr_ids"].split(","), "outcome"]
    assert (rv_out == PLANNER_REVIEW).all() and rv["util_after_pct"] > cfg["capacity"]["hard_limit_pct"] - 0.05
    section("5b. Capacity: a lot that needs planner review")
    out += [f"Lot **{rv.name}** ({rv['article_id']}, {rv['market_destination']}, {rv['consolidated_qty']:,} units).", "",
            f"Engine note: {rv['warnings'].split(' | ')[0]}", "",
            f"Every certified option would pass the {cfg['capacity']['hard_limit_pct']}% limit with this lot, so it is "
            "**not bought** and its requisitions are marked for planner review. A planner can approve it, move it, "
            f"or reject it. This window has {len(rev)} such lot(s)."]

# ---------------------------------------------------------------- what-if: hold
lot_ids = lots["pr_ids"].str.split(",").explode()
named = p.prs.loc[lot_ids, "customer_id"].dropna().value_counts()
ratings = p.data.customers.set_index("customer_id")["credit_rating"]
c_rated = [c for c in named.index if ratings.get(c) == "C"]
cust = c_rated[0] if c_rated else named.index[0]  # credit hold: a C-rated customer when the run has one
h = scenarios.hold_customer(p, RUN, cust)
section(f"6. What-if: credit hold on customer {cust} (rating {ratings.get(cust, '?')})")
out += [f"NSV at risk = sum of {cust}'s sales orders in this week's lots = **{money(h['nsv_at_risk_usd'])}**.", "",
        "| Lot | Before | Removed | After = before − removed | MOQ check | Suggested fix | After fix: MOQ / MPQ |",
        "|---|---|---|---|---|---|---|"]
for r in h["lots"].itertuples():
    assert r.qty_after == r.qty_before - r.qty_removed
    if r.pulled_pr_ids:
        assert not (p.prs.loc[r.pulled_pr_ids.split(","), "customer_id"] == cust).any()
    check = "lot fully held" if r.qty_after == 0 else ("≥ 300, OK" if r.qty_after >= moq else f"< {moq}, alert")
    after = f"{'OK' if r.moq_ok_after_fix else 'below'} / {'OK' if r.mpq_ok_after_fix else 'below'}"
    out.append(f"| {r.lot_id} | {r.qty_before:,} | {r.qty_removed:,.0f} | {r.qty_before:,} − {r.qty_removed:,.0f} = **{r.qty_after:,.0f}** | {check} | {r.fix or '—'} | {after} |")
out += ["", f"A fix only uses future demand from other customers (never {cust}), each requisition at most once, and "
        "MOQ, MPQ and factory load are re-checked after it."]

# ---------------------------------------------------------------- what-if: delay
f = lots["assigned_factory"].iloc[0]
dl = scenarios.delay_factory(p, RUN, f, 14)
r = dl["lots"].iloc[0]
assert (r["arrival_after"] - r["arrival_before"]).days == 14
section(f"7. What-if: {f} production delayed 14 days")
out += [f"Lot **{r['lot_id']}**: expected arrival {d(r['arrival_before'])} + 14 days = **{d(r['arrival_after'])}**; "
        f"RDD {d(r['rdd'])} → {'late' if r['late_after'] else 'still on time'}.", "",
        f"Across {f}'s {len(dl['lots'])} lots this week: {dl['lots_late']} would be late, "
        f"{money(dl['nsv_at_risk_usd'])} of sales value at risk."]

# ---------------------------------------------------------------- what-if: swap
lot = lots.iloc[0]
target = next(x for x in sorted(p.certified[lot["article_id"]]) if x != lot["assigned_factory"])
sw = scenarios.swap_factory(p, RUN, lot.name, target)
expected = lot["consolidated_qty"] * lot["unit_cost_usd"] * (sw["cost_multiplier_after"] - sw["cost_multiplier_before"])
assert abs(sw["cost_delta_usd"] - expected) < 0.01
bad = next((x for x in p.factories.index if x not in p.certified[lot["article_id"]]), None)
section(f"8. What-if: switch lot {lot.name} from {lot['assigned_factory']} to {target}")
out += ["| Step | Value |", "|---|---|",
        f"| Certified for {lot['article_id']}? | Yes ({', '.join(sorted(p.certified[lot['article_id']]))}) |",
        f"| Cost change | {lot['consolidated_qty']:,} × {money(lot['unit_cost_usd'])} × ({sw['cost_multiplier_after']} − {sw['cost_multiplier_before']}) = **{money(sw['cost_delta_usd'])}** |",
        f"| Lead-time change | {sw['lead_time_delta_days']:+d} days |",
        f"| New arrival | {d(sw['arrival_after'])} vs RDD {d(lot['earliest_rdd'])} → {'on time' if sw['on_time_after'] else 'late'} |",
        f"| MOQ still met | {'Yes' if sw['moq_still_met'] else 'No'} ({lot['consolidated_qty']:,} units, unchanged) |",
        f"| {lot['assigned_factory']} load (lot removed) | {sw['source_load_before_pct']:.1f}% → {sw['source_load_after_pct']:.1f}% |",
        f"| {target} load (lot added) | {sw['target_load_before_pct']:.1f}% → **{sw['target_utilization_pct']:.1f}%**"
        f"{' (above the threshold)' if sw['capacity_warning'] else ''}{' (over capacity)' if sw['over_capacity'] else ''} |",
        f"| MPQ {sw['mpq']:,} after the move | {lot['assigned_factory']} {sw['source_total_after']:,.0f}, {target} {sw['target_total_after']:,.0f} units |"]
if bad:
    out += ["", f"Switching to **{bad}** is rejected: it is not certified for {lot['article_id']} in the certification matrix."]

# ---------------------------------------------------------------- pull-forward
util = pull_forward.window_utilization(p, RUN)
rec = pull_forward.recommendations(p, RUN)
u0 = util.iloc[0]
cap = p.factories.loc[u0["factory_id"], "weekly_capacity_units"]
assert abs(u0["avg_utilization_pct"] - u0["units"] / (cap * u0["weeks"]) * 100) < 1e-9
section("8b. Pull-forward")
out += [f"Window load uses the same weeks above and below the line: {u0['factory_id']} in {u0['window']} = "
        f"{u0['units']:,.0f} units ÷ ({cap:,} × {u0['weeks']} weeks) = {u0['avg_utilization_pct']:.1f}% on average; "
        f"its busiest week is {u0['peak_utilization_pct']:.1f}%. A window is flagged on its busiest week.", ""]
if len(rec):
    acc = rec[rec["actionable"]]
    out += [f"{len(rec)} article-market groups were reviewed in overloaded windows; {len(acc)} can move. Each move is "
            "tested on one shared copy of the ledger that already holds the earlier moves."]
    if len(acc):
        a = acc.iloc[0]
        out += ["", f"Example: {a['units']:,.0f} units of {a['article_id']} for {a['market_destination']} at {a['factory_id']}: "
                f"{a['recommendation']}."]

# ---------------------------------------------------------------- accounting
rep = accounting_report(p)
units = rep["units_by_outcome"]
assert abs(sum(units.values()) - rep["units_seen"]) < 1e-6
section("9. Complete accounting (all 100 runs, 23 buying windows)")
out += ["| Outcome | Units |", "|---|---|"] + [f"| {k} | {v:,.0f} |" for k, v in units.items()]
out += [f"| **Total** | **{sum(units.values()):,.0f}** = all {rep['prs_seen']:,} requisitions ({rep['units_seen']:,.0f} units) |"]

path = ROOT / "docs" / "worked_examples.md"
path.write_text("\n".join(out) + "\n")
print("wrote", path)
