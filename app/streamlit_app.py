"""Acme Sports weekly buy planner (Phase 1 app).

Workflow from the scoping review: 1 select a week -> 2 generate the plan -> 3 test a change -> 4 export.
Run with:  streamlit run app/streamlit_app.py
"""
import io
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import pull_forward  # noqa: E402
from engine.accounting import accounting_report, rule_violations  # noqa: E402
from engine.metrics import comparison_table, plan_kpis  # noqa: E402
from engine.output import fact_buy_plan_suggestions, get_planner  # noqa: E402
from engine.planner import FUTURE_FORECAST, UNRESOLVED_MOQ, UNRESOLVED_MPQ  # noqa: E402
from sim import scenarios  # noqa: E402

st.set_page_config(page_title="Acme Sports Buy Planner", layout="wide")


@st.cache_resource(show_spinner="Planning all MRP runs (first load only)…")
def load_planner():
    return get_planner()


planner = load_planner()


@st.cache_data(show_spinner=False)
def global_checks():
    return accounting_report(planner), len(rule_violations(planner)), comparison_table(planner)


@st.cache_data(show_spinner=False)
def all_weeks_csv() -> str:
    return fact_buy_plan_suggestions(planner).to_csv(index=False)


@st.cache_data(show_spinner=False)
def pull_forward_view(run_id: str):
    return pull_forward.window_utilization(planner, run_id), pull_forward.recommendations(planner, run_id)


@st.cache_data(show_spinner=False)
def week_excel(run_id: str) -> bytes:
    result = planner.run_result(run_id)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        fact_buy_plan_suggestions(planner, [run_id]).to_excel(xl, sheet_name="buy_plan", index=False)
        result.lots.to_excel(xl, sheet_name="lot_details", index=False)
        result.outcomes.to_excel(xl, sheet_name="decisions", index=False)
    return buf.getvalue()
runs = planner.runs.copy()
runs["label"] = (runs["run_id"] + " · " + pd.to_datetime(runs["mrp_freeze_datetime_utc"]).dt.strftime("%d %b %Y")
                 + " · " + runs["season"] + " " + runs["range_version"])

# ------------------------------------------------------------------ 1. select a week
st.sidebar.header("1 · Select a week")
label = st.sidebar.selectbox("MRP run", runs["label"], index=19)
run = runs[runs["label"] == label].iloc[0]
run_id = run["run_id"]
result = planner.run_result(run_id)
lots = result.lots
st.sidebar.markdown(
    f"""**Buy week calendar**
- Freeze: {pd.Timestamp(run['mrp_freeze_datetime_utc']):%a %d %b}
- As-Is plan: {pd.Timestamp(run['as_is_plan_date']):%a %d %b}
- Go / No-Go: {pd.Timestamp(run['go_nogo_date']):%a %d %b}
- PO execution: {pd.Timestamp(run['po_execution_date']):%a %d %b}
- Factory confirms by: {pd.Timestamp(run['factory_confirm_deadline']):%a %d %b}"""
)
st.sidebar.caption("Thresholds and client decisions are set in config/thresholds.yaml")

st.title("Acme Sports · Weekly Buy Planner")
st.caption(f"{run_id} · season {run['season']} · range {run['range_version']} · all decisions below are automatic "
           "unless marked manual")

tab_plan, tab_change, tab_pf, tab_cap, tab_export, tab_checks = st.tabs(
    ["2 · Buy plan", "3 · Test a change", "Pull-forward", "Capacity", "4 · Export", "Data & checks"])

# ------------------------------------------------------------------ 2. buy plan
with tab_plan:
    k = plan_kpis(planner, [run_id])
    out = result.outcomes
    unresolved = out[out["outcome"].isin([UNRESOLVED_MOQ, UNRESOLVED_MPQ])] if len(out) else out
    excluded = out[out["outcome"] == FUTURE_FORECAST] if len(out) else out
    prs = planner.prs
    c = st.columns(3) + st.columns(3)
    c[0].metric("Lots to buy", f"{k['lots']}")
    c[1].metric("Units", f"{k['units_bought']:,.0f}")
    c[2].metric("Production cost", f"${k['production_cost_usd'] / 1e6:,.2f}M")
    c[3].metric("Units on time", f"{k['on_time_pct']:.1f}%")
    c[4].metric("Routed to backup", f"{k['backup_routed_pct']:.0f}% of lots")
    c[5].metric("Unresolved units", f"{prs.loc[unresolved['pr_id'], 'requested_qty'].sum() if len(unresolved) else 0:,.0f}")

    sub = st.tabs([f"Purchases ({len(lots)})", f"Unresolved demand ({len(unresolved)})",
                   f"Moved to Future, Rule 5 ({len(excluded)})", f"Waiting, not yet due ({len(result.open_prs)})"])
    with sub[0]:
        f1, f2, f3 = st.columns(3)
        mk = f1.multiselect("Market", sorted(lots["market_destination"].unique()) if len(lots) else [])
        fc = f2.multiselect("Factory", sorted(lots["assigned_factory"].unique()) if len(lots) else [])
        only_warn = f3.checkbox("Only lots with warnings")
        view = lots.copy()
        if mk:
            view = view[view["market_destination"].isin(mk)]
        if fc:
            view = view[view["assigned_factory"].isin(fc)]
        if only_warn:
            view = view[view["warnings"] != ""]
        cols = ["lot_id", "article_id", "market_destination", "consolidated_qty", "assigned_factory",
                "backup_routed", "suggested_rdd", "on_time", "total_cost_usd", "is_piggyback_applied",
                "piggyback_source_window", "decision_type", "reason", "warnings"]
        st.dataframe(view[cols], use_container_width=True, hide_index=True,
                     column_config={"total_cost_usd": st.column_config.NumberColumn(format="$%.0f"),
                                    "suggested_rdd": st.column_config.DateColumn()})
        if len(view):
            pick = st.selectbox("Show the requisitions in a lot", view["lot_id"])
            ids = view.set_index("lot_id").loc[pick, "pr_ids"].split(",")
            st.dataframe(prs.loc[ids, ["pr_id", "size_id", "channel_id", "requested_qty", "rdd_original",
                                       "customer_id", "nsv"]], hide_index=True, use_container_width=True)
    with sub[1]:
        st.caption("Demand that could not be bought under the rules and could not wait. Shown separately, "
                   "never treated as a feasible purchase.")
        if len(unresolved):
            st.dataframe(unresolved[["pr_id", "outcome", "reason"]].merge(
                prs[["pr_id", "article_id", "market_destination", "requested_qty", "rdd_original"]].reset_index(drop=True)),
                hide_index=True, use_container_width=True)
    with sub[2]:
        if len(excluded):
            st.dataframe(excluded[["pr_id", "reason"]].merge(
                prs[["pr_id", "article_id", "market_destination", "requested_qty", "rdd_original"]].reset_index(drop=True)),
                hide_index=True, use_container_width=True)
    with sub[3]:
        waiting = prs.loc[result.open_prs, ["pr_id", "article_id", "market_destination", "requested_qty",
                                            "rdd_original", "release_primary"]] if result.open_prs else prs.iloc[0:0]
        st.caption("Open demand carried to later runs (rolling window). Each keeps its PR ID, so it is never bought twice.")
        st.dataframe(waiting, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ 3. test a change
with tab_change:
    st.caption("Scenarios change a copy of this week's plan. The baseline plan is not modified; "
               "changes are marked as manual decisions.")
    scenario = st.radio("Scenario", ["Hold a customer", "Delay production", "Switch factories"], horizontal=True)
    if scenario == "Hold a customer":
        ids = lots["pr_ids"].str.split(",").explode() if len(lots) else pd.Series(dtype=str)
        customers = planner.prs.loc[ids, "customer_id"].dropna().value_counts()
        cust_labels = {f"{c} ({n} requisitions this week)": c for c, n in customers.items()}
        cust = cust_labels.get(st.selectbox("Customer", list(cust_labels)))
        if cust is None:
            st.info("No customer orders in this week's lots.")
        else:
            r = scenarios.hold_customer(planner, run_id, cust)
            a, b, c3 = st.columns(3)
            a.metric("Lots affected", r["lots_affected"])
            b.metric("NSV at risk", f"${r['nsv_at_risk_usd']:,.0f}")
            c3.metric("Lots below MOQ after hold", len(r["moq_alerts"]))
            if len(r["moq_alerts"]):
                st.warning("Check minimums: some lots fall below MOQ after the hold. A suggested fix is shown per lot.")
            st.dataframe(r["lots"], hide_index=True, use_container_width=True)
            with st.expander("Units removed by size"):
                st.dataframe(r["sizes"], hide_index=True, use_container_width=True)
    elif scenario == "Delay production":
        f = st.selectbox("Factory", sorted(lots["assigned_factory"].unique()) if len(lots) else [])
        days = st.slider("Delay (days)", 1, 60, 14)
        if f:
            r = scenarios.delay_factory(planner, run_id, f, days)
            a, b = st.columns(2)
            a.metric("Lots arriving late", f"{r['lots_late']} of {len(r['lots'])}")
            b.metric("NSV at risk", f"${r['nsv_at_risk_usd']:,.0f}")
            st.dataframe(r["lots"], hide_index=True, use_container_width=True)
            st.subheader("Affected customers")
            st.dataframe(r["customers"], hide_index=True, use_container_width=True)
    else:
        if len(lots):
            lot_id = st.selectbox("Lot", lots["lot_id"])
            lot = lots.set_index("lot_id").loc[lot_id]
            certified = planner.certified[lot["article_id"]]
            options = sorted((f for f in planner.factories.index if f != lot["assigned_factory"]),
                             key=lambda f: f not in certified)
            target_labels = {(f if f in certified else f"{f} (not certified)"): f for f in options}
            target = target_labels[st.selectbox(f"Move from {lot['assigned_factory']} to", list(target_labels))]
            r = scenarios.swap_factory(planner, run_id, lot_id, target)
            if not r["valid"]:
                st.error(r["message"])
            else:
                a, b, c3, d = st.columns(4)
                a.metric("Cost change", f"${r['cost_delta_usd']:,.0f}",
                         f"multiplier {r['cost_multiplier_before']} → {r['cost_multiplier_after']}")
                b.metric("Lead-time change", f"{r['lead_time_delta_days']:+d} days")
                c3.metric("New arrival", f"{r['arrival_after']:%d %b %Y}",
                          "on time" if r["on_time_after"] else "late")
                d.metric("Target load", f"{r['target_utilization_pct']:.0f}%")
                if r["capacity_warning"]:
                    st.warning(f"{target} is above the capacity threshold in those weeks.")
                st.caption(f"MOQ still met: {'yes' if r['moq_still_met'] else 'no'} · decision type: manual")

# ------------------------------------------------------------------ pull-forward
with tab_pf:
    st.caption("Projected load for the next buying windows (committed lots plus open demand at its primary "
               "factory). Windows at or above the threshold get a pull-forward recommendation.")
    util, rec = pull_forward_view(run_id)
    heat = util.pivot(index="factory_id", columns="window", values="avg_utilization_pct")
    st.plotly_chart(px.imshow(heat.round(0), text_auto=True, color_continuous_scale="OrRd", aspect="auto",
                              labels={"color": "Avg weekly load %"}), use_container_width=True)
    if len(rec):
        st.metric("Actionable recommendations", int(rec["actionable"].sum()), f"{len(rec)} groups reviewed")
        st.dataframe(rec, hide_index=True, use_container_width=True)
    else:
        st.info("No overloaded windows ahead.")

# ------------------------------------------------------------------ capacity
with tab_cap:
    ledger = planner.snapshots[run_id].table()
    ledger["week"] = pd.to_datetime(ledger["week"])
    start = pd.Timestamp(run["mrp_freeze_datetime_utc"]) - pd.Timedelta(weeks=4)
    view = ledger[(ledger["week"] >= start) & (ledger["week"] <= start + pd.Timedelta(weeks=40))]
    fig = px.line(view, x="week", y="utilization_pct", color="factory_id",
                  labels={"utilization_pct": "Load % of weekly capacity"})
    fig.add_hline(y=planner.cfg["capacity"]["backup_threshold_pct"], line_dash="dash",
                  annotation_text="backup threshold")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Rolling ledger from our own assignments (client decision); the static utilisation table is not used.")

# ------------------------------------------------------------------ 4. export
with tab_export:
    fact = fact_buy_plan_suggestions(planner, [run_id])
    st.dataframe(fact, hide_index=True, use_container_width=True)
    c1, c2, c3 = st.columns(3)
    c1.download_button("fact_buy_plan_suggestions (this week, CSV)", fact.to_csv(index=False),
                       f"fact_buy_plan_suggestions_{run_id}.csv", "text/csv")
    c2.download_button("fact_buy_plan_suggestions (all weeks, CSV)", all_weeks_csv(),
                       "fact_buy_plan_suggestions_all.csv", "text/csv")
    c3.download_button("Excel workbook (this week)", week_excel(run_id), f"buy_plan_{run_id}.xlsx")

# ------------------------------------------------------------------ data & checks
with tab_checks:
    st.subheader("Success checks")
    rep, n_violations, comparison = global_checks()
    a, b = st.columns(2)
    a.metric("Complete accounting", "PASSED" if rep["passed"] else "FAILED",
             f"{rep['prs_seen']:,} requisitions, {rep['units_seen']:,.0f} units")
    b.metric("Rule violations without a warning", n_violations)
    st.json(rep["checks"])
    st.write("Units by outcome (all runs)", pd.Series(rep["units_by_outcome"]).rename("units"))
    st.subheader("Comparison with the as-is reference (all runs)")
    st.caption("As-is = the factory assignments in the supplied data, buying every requisition when it appears. "
               "The reference plan for the final evaluation is still to be agreed with the client.")
    st.dataframe(comparison, hide_index=True, use_container_width=True)
    st.subheader("Data issues found on load")
    for issue in planner.data.issues:
        st.write("•", issue)
