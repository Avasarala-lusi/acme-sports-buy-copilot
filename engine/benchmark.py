"""Read-only historical replay: known demand, one formal buying window at a time.

Tuning metrics are captured at the end of the earlier period, before continuing
that replay into the test period. Later outcomes never enter weight selection.
The supplied assignments are a reference with different timing assumptions.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
import numpy as np
import pandas as pd

from engine.accounting import accounting_report, rule_violations
from engine.optimizer import RollingOptimizer, evaluate_as_is
from engine.planner import Planner
from engine.rules.exclusion import forecast_excluded


def _seasons(planner):
    return list(dict.fromkeys(planner.runs['season']))


def eligible_ids(planner, through=None):
    through = planner.processed if through is None else through
    return [p for p, r in planner.rows.items() if planner.run_index[r['run_id']] <= through
            and not forecast_excluded(r['channel_id'], r['has_order'], r['early_buy'])]


def plan_kpis(planner, ids):
    """PR-level outcomes on a fixed population; capacity uses the complete ledger."""
    ids = list(ids)
    prs = planner.prs.loc[ids]
    lots = planner.bought_lots()
    if len(lots):
        detail = lots.assign(pr_id=lots['pr_ids'].str.split(',')).explode('pr_id').set_index('pr_id')
        detail = detail.loc[detail.index.intersection(ids)]
    else:
        detail = pd.DataFrame()
    total = float(prs['requested_qty'].sum())
    bought_ids = list(detail.index)
    bought_prs = planner.prs.loc[bought_ids]
    qty = bought_prs['requested_qty'].astype(float)
    arrival = pd.to_datetime(detail['suggested_rdd']) if len(detail) else pd.Series(dtype='datetime64[ns]')
    ontime = (arrival <= bought_prs['rdd_original']) if len(detail) else pd.Series(dtype=bool)
    bought = float(qty.sum())
    ontime_qty = float(qty.loc[ontime].sum()) if len(qty) else 0.
    cost = float((qty*bought_prs['unit_cost_usd']*detail['assigned_factory'].map(planner.factories['cost_multiplier'])).sum()) if len(detail) else 0.
    backup = float(qty[detail['assigned_factory'] != bought_prs['primary']].sum()) if len(detail) else 0.
    # For a cohort, include other cohorts sharing its production weeks in load checks.
    relevant_weeks = set()
    for row in detail.itertuples():
        relevant_weeks.update(planner.ledger.weeks_for(row.production_start, row.mfg_days))
    capacity = planner.ledger.table()
    if len(capacity): capacity = capacity[capacity['week'].isin(relevant_weeks)]
    return dict(firm_units=total, units_bought=bought, units_not_bought=total-bought,
        bought_pct=bought/total*100 if total else 0., production_cost_usd=cost,
        cost_per_unit_usd=cost/bought if bought else 0., on_time_units=ontime_qty, late_units=bought-ontime_qty,
        on_time_pct_of_bought=ontime_qty/bought*100 if bought else 0.,
        on_time_pct_of_firm=ontime_qty/total*100 if total else 0.,
        # Legacy shape retained for the disabled disruption consumer. Current UI
        # omits probability metrics; these are deterministic planned units only.
        expected_on_time_units=ontime_qty, expected_on_time_pct_of_bought=ontime_qty/bought*100 if bought else 0.,
        backup_units_pct=backup/bought*100 if bought else 0.,
        peak_utilization_pct=float(capacity['utilization_pct'].max()) if len(capacity) else 0.,
        weeks_over_100=int((capacity['utilization_pct'] > 100.0001).sum()) if len(capacity) else 0,
        units_in_closed_weeks=0., orders_below_mpq=None)


def _validation(planner):
    accounting = accounting_report(planner)
    violations = rule_violations(planner)
    fallbacks = sum(bool(r.get('fallback')) for r in getattr(planner,'optimizer_runs',[]))
    return dict(passed=accounting['passed'] and not len(violations) and fallbacks==0,
                accounting=accounting['checks'], rule_violations=int(len(violations)),
                solver_fallbacks=fallbacks)


def select_weight(candidates):
    """Team heuristic using *only* captured tuning outcomes, never profit or test data."""
    ordered = sorted(candidates, key=lambda a:a['weight'])
    valid = [a for a in ordered if a['validation']['passed']]
    if not valid: return None, []
    chosen, steps = valid[0], []
    for candidate in valid[1:]:
        old, new = chosen['tuning'], candidate['tuning']
        extra_units = new['on_time_units']-old['on_time_units']
        extra_cost = new['production_cost_usd']-old['production_cost_usd']
        unit_cost = old['cost_per_unit_usd']
        marginal = extra_cost/extra_units if extra_units > 0 else None
        accepted = extra_units > 0 and marginal <= unit_cost
        steps.append(dict(from_weight=chosen['weight'], to=candidate['weight'],
            extra_on_time_units=extra_units, extra_cost_usd=extra_cost,
            cost_per_extra_on_time_unit_usd=marginal, average_unit_cost_usd=unit_cost, accepted=accepted))
        if accepted: chosen = candidate
    return chosen['weight'], steps


def _mix_and_changes(base, alternative):
    """PR-level changes remain comparable even when consolidation or purchase timing differs."""
    def detail(p):
        lots=p.bought_lots()
        if not len(lots): return pd.DataFrame()
        return lots.assign(pr_id=lots['pr_ids'].str.split(',')).explode('pr_id').set_index('pr_id')
    before, after = detail(base), detail(alternative)
    mix=[]
    if len(after):
        for f,g in after.groupby('assigned_factory'):
            qty=alternative.prs.loc[g.index,'requested_qty'].astype(float)
            ontime=pd.to_datetime(g['suggested_rdd'])<=alternative.prs.loc[g.index,'rdd_original']
            cost=qty*alternative.prs.loc[g.index,'unit_cost_usd']*float(alternative.factories.loc[f,'cost_multiplier'])
            mix.append(dict(factory_id=f,units=float(qty.sum()),production_cost_usd=float(cost.sum()),
                            on_time_pct=float(qty[ontime].sum()/qty.sum()*100)))
    changes=[]
    for pr_id in set(before.index)|set(after.index):
        a=before.loc[pr_id] if pr_id in before.index else None
        b=after.loc[pr_id] if pr_id in after.index else None
        if a is not None and b is not None and a['assigned_factory']==b['assigned_factory'] and a['production_start']==b['production_start']: continue
        pr=base.rows[pr_id];qty=float(pr['requested_qty'])
        def cost(row): return qty*pr['unit_cost_usd']*float(base.factories.loc[row['assigned_factory'],'cost_multiplier']) if row is not None else 0.
        changes.append(dict(pr_id=pr_id,lot_id=b['lot_id'] if b is not None else a['lot_id'],
            run_id=b['run_id'] if b is not None else a['run_id'], article_id=pr['article_id'],market_destination=pr['market_destination'],
            qty=qty,rule_factory=a['assigned_factory'] if a is not None else None,plan_factory=b['assigned_factory'] if b is not None else None,
            rule_on_time_units=qty if a is not None and a['suggested_rdd']<=pr['rdd_original'] else 0.,
            plan_on_time_units=qty if b is not None and b['suggested_rdd']<=pr['rdd_original'] else 0.,
            rule_run_id=a['run_id'] if a is not None else None,plan_run_id=b['run_id'] if b is not None else None,
            cost_change_usd=float(cost(b)-cost(a))))
    return mix,sorted(changes,key=lambda r:(-r['qty'],r['pr_id']))[:300]


def replay_weight(planner, weight, populations, end, cache=False):
    """Independent rolling replay; cache only real-data automatic reference results.

    No shared state or purchases are changed. Small per-weight JSON caches let a
    long first calculation resume without repeating completed settings.
    """
    if cache:
        from engine.config import ROOT
        from engine.output import _config_hash
        path=ROOT/planner.cfg['data']['output_dir']/f'rolling_weight_v2_{_config_hash(planner.cfg)}_{weight:g}.json'
        if path.exists(): return json.loads(path.read_text())
    t0=time.monotonic()
    settings=deepcopy(planner.cfg)
    settings['buying_window']['weekly_drafts']=False  # previews never change commitments
    alternative=RollingOptimizer(data=planner.data,config=settings,weight=weight)
    alternative.plan_through(planner.runs.iloc[end]['run_id'])
    tune=plan_kpis(alternative,eligible_ids(alternative))
    # Capture proof/metrics NOW, while no test-period requests have been processed.
    tune_valid=_validation(alternative)
    alternative.plan_all()
    valid=_validation(alternative)
    results={k:plan_kpis(alternative,pop) for k,pop in populations.items()}
    approach=dict(key=f'opt_{weight:g}',label=f'Optimizer, weight {weight:g}',kind='optimiser',weight=weight,
                  seconds=time.monotonic()-t0,status='Verified rolling replay' if valid['passed'] else 'Review required',
                  gap_pct=None,results=results,validation=valid)
    candidate=dict(weight=weight,tuning=tune,validation=tune_valid)
    mix,changes=_mix_and_changes(planner,alternative)
    payload=dict(approach=approach,candidate=candidate,plan=dict(weight=weight,by_factory=mix,changes=changes))
    if cache:
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,allow_nan=False));tmp.replace(path)
    return payload


def network_results(planner, cache_weights=False):
    cfg=planner.cfg.get('benchmark',{})
    seasons=_seasons(planner)
    tuning=[s for s in cfg.get('tuning_seasons',seasons[:2]) if s in seasons]
    test=[s for s in cfg.get('test_seasons',seasons[2:]) if s in seasons]
    if not tuning or not test or set(tuning)&set(test): raise ValueError('Disjoint, nonempty tuning and test seasons required')
    tune_indices=planner.runs.index[planner.runs['season'].isin(tuning)]
    test_indices=planner.runs.index[planner.runs['season'].isin(test)]
    end=int(max(tune_indices))
    if end >= min(test_indices): raise ValueError('Tuning must finish before the first test run')
    weights=[float(w) for w in cfg.get('weights',[0.,.25,.5,.75,1.])]
    ids=eligible_ids(planner)
    cohort=planner.prs['run_id'].map(planner.runs.set_index('run_id')['season'])
    populations={'all':ids,**{s:[p for p in ids if cohort[p]==s] for s in seasons},
                 'tuning':[p for p in ids if cohort[p] in tuning], 'test':[p for p in ids if cohort[p] in test]}
    class PlannedOnly:
        def p_on_time(self, factory, slack): return (np.asarray(slack)>=0).astype(float)
    baseline={key:evaluate_as_is(planner,pd.DataFrame({'pr_ids':pop}),PlannedOnly()) for key,pop in populations.items()}
    for value in baseline.values(): value['late_units']=value['units_bought']-value['on_time_units']
    approaches=[dict(key='as_is',label='Supplied assignments (reference)',kind='baseline',results=baseline),
                dict(key='rules',label='Rule engine',kind='rules',results={k:plan_kpis(planner,pop) for k,pop in populations.items()},validation=_validation(planner))]
    candidates=[]; plans=[]
    for weight in weights:
        payload=replay_weight(planner,weight,populations,end,cache=cache_weights)
        approaches.append(payload['approach']);candidates.append(payload['candidate']);plans.append(payload['plan'])
    chosen,steps=select_weight(candidates)
    for row in steps: row['from']=row.pop('from_weight')
    all_units=float(planner.prs['requested_qty'].sum())
    eligible_units=float(planner.prs.loc[ids,'requested_qty'].sum())
    return dict(seasons=seasons,tuning_seasons=tuning,test_seasons=test,weights=weights,selected_weight=chosen,
        selection_rule='Team heuristic: prefer additional planned on-time units when their marginal production cost is no more than the prior production cost per bought unit; tuning data only',
        selection_steps=steps,approaches=approaches,plans=plans,
        universe=dict(lots=0,requisitions=len(ids),units=eligible_units,from_review_lots=0,all_units=all_units,
                      excluded_units=all_units-eligible_units),
        evaluation_note='Read-only automatic historical replay. Each window sees received PRs only; previous commitments remain fixed. Saved manual decisions are not changed or included. Cohorts use PR intake season; capacity checks include the complete production ledger.',
        baseline_note='Supplied assignments use the intake run PO date, including weekly dates. Rules and optimizer use formal MID/EOM purchases. All loads use business-day production allocation. Differences cannot be attributed to factory selection alone.',
        service_basis='Planned on-time units; no simulated delivery probabilities',
        routing_policy='Optimizer considers all certified factories jointly; the rule engine walks the backup chain. This is an alternative recommendation policy, not a change to the core rules.',
        complete=all(a.get('validation',{}).get('passed',True) for a in approaches) and chosen is not None)


def cached_network_results(planner):
    from engine.config import ROOT
    from engine.output import _config_hash
    path=ROOT/planner.cfg['data']['output_dir']/f'rolling_network_v2_{_config_hash(planner.cfg)}.json'
    if path.exists(): return json.loads(path.read_text())
    result=network_results(planner,cache_weights=True)
    # Convert NumPy scalars without changing booleans into strings. No NaN/Infinity.
    out=json.loads(json.dumps(result,default=lambda x:x.item() if isinstance(x,np.generic) else str(x),allow_nan=False))
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(out,allow_nan=False));temporary.replace(path)
    return out
