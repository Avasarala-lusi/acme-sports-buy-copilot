"""Small counterexamples for the released rolling optimizer (no client data needed)."""
from copy import deepcopy
import pandas as pd
import pytest
from engine.planner import Planner
from engine.optimizer import RollingOptimizer, options, solve
from engine.capacity import CapacityLedger
from engine.benchmark import select_weight, plan_kpis, eligible_ids
from tests.test_client_clarifications import small_planner


def candidates(p):
    return pd.DataFrame([dict(lot_id=f'L{i}', run_id='R2', article_id=r['article_id'], category=r['category'],
        market_destination=r['market_destination'], primary_factory=r['primary'], pr_ids=pr,
        last_chance=r['last_chance'], rule_factory=None, qty=float(r['requested_qty']),
        start=pd.Timestamp('2026-01-14'), season='TEST') for i,(pr,r) in enumerate(p.rows.items())])


def bought(p):
    u=candidates(p); s=solve(p,0,u,options(p,u),time_limit=5)
    return [int(i) for i,j in s['choice'].items() if j>=0]


def test_optimizer_never_uses_another_market_to_waive_moq():
    p=small_planner((200,1000))
    p.rows['P1']['market_destination']='MX'
    assert bought(p)==[]  # 1000 alone also fails factory MPQ


def test_optimizer_mpq_respects_configured_rdd_span():
    p=small_planner((600,600),['2026-01-21','2026-02-20'])
    p.rows['P1']['market_destination']='MX'
    assert bought(p)==[]
    p.cfg['quantities']['mpq_scope']='purchase'
    assert bought(p)==[0,1]


def test_last_chance_cannot_be_displaced_by_a_larger_normal_order():
    p=small_planner((100,5000),capacity=3000)
    p.rows['P0']['last_chance']=True
    assert bought(p)==[0]


def test_release_rdd_revenue_priority_is_fixed_before_cost():
    p=small_planner((1200,1200),['2026-01-22','2026-01-21'],capacity=720)
    assert bought(p)==[1]
    p.rows['P0']['release_primary']=p.rows['P1']['release_primary']
    assert bought(p)==[1]  # earliest RDD breaks equal release
    p.rows['P0']['rdd_original']=p.rows['P1']['rdd_original']
    p.rows['P0']['nsv']=10000
    assert bought(p)==[0]


def two_factory_planner():
    p=small_planner()
    data=deepcopy(p.data)
    f=data.tables['factories'].iloc[0].copy()
    f['factory_id']='G';f['cost_multiplier']=.5;f['mfg_lt_min_days']=14;f['mfg_lt_max_days']=14
    data.tables['factories']=pd.concat([data.tables['factories'],f.to_frame().T],ignore_index=True)
    data.tables['cert_matrix']=pd.concat([data.tables['cert_matrix'],pd.DataFrame([dict(article_id='A',factory_id='G',is_certified=True)])],ignore_index=True)
    return Planner(data=data,config=deepcopy(p.cfg))


def test_cost_and_planned_service_choose_different_certified_factories():
    p=two_factory_planner();u=candidates(p);opts=options(p,u)
    cheap=solve(p,0,u,opts);service=solve(p,1,u,opts)
    assert cheap['opts'].loc[cheap['choice'].loc[0],'factory']=='G'
    assert service['opts'].loc[service['choice'].loc[0],'factory']=='F'


def test_prior_commitments_reduce_capacity_and_are_not_mutated():
    p=small_planner(capacity=720);u=candidates(p);opts=options(p,u)
    committed=CapacityLedger({'F':720});committed.add('F','2026-01-14',7,100)
    old=committed.table().copy()
    result=solve(p,.5,u,opts,committed=committed)
    assert result['choice'].loc[0]==-1
    pd.testing.assert_frame_equal(old,committed.table())


def test_one_solve_cannot_optimize_all_history_or_disable_mpq():
    p=small_planner((1200,1200));u=candidates(p);u.loc[1,'run_id']='R4'
    with pytest.raises(ValueError,match='one buying window'): solve(p,.5,u)
    with pytest.raises(ValueError,match='cannot be disabled'): solve(p,.5,u,enforce_mpq=False)


def rolling_data():
    p=small_planner((1200,1200),['2026-01-21','2026-02-18'])
    data=deepcopy(p.data)
    data.tables['runs']['season']=['TRAIN','TRAIN','TRAIN','TEST','TEST']
    data.tables['prs'].loc[1,'run_id']='R4'
    data.tables['prs'].loc[1,'mrp_run_date']=pd.Timestamp('2026-01-25')
    cfg=deepcopy(p.cfg);cfg['buying_window']['weekly_drafts']=False
    return data,cfg


def test_future_demand_cannot_change_earlier_optimizer_decisions():
    data,cfg=rolling_data()
    p=RollingOptimizer(data=data,config=cfg,weight=.5);p.plan_through('R2')
    changed=deepcopy(data);changed.tables['prs'].loc[1,'requested_qty']=999999
    q=RollingOptimizer(data=changed,config=deepcopy(cfg),weight=.5);q.plan_through('R2')
    pd.testing.assert_frame_equal(p.bought_lots(),q.bought_lots())
    assert 'P1' not in p.outcomes
    earlier=p.bought_lots().copy();p.plan_all()
    pd.testing.assert_frame_equal(earlier,p.bought_lots().query("run_id == 'R2'").reset_index(drop=True))


def test_weight_selection_has_no_access_to_test_metrics():
    a=dict(weight=0.,validation={'passed':True},tuning=dict(on_time_units=100.,production_cost_usd=100.,cost_per_unit_usd=1.))
    b=dict(weight=1.,validation={'passed':True},tuning=dict(on_time_units=110.,production_cost_usd=105.,cost_per_unit_usd=1.))
    before=select_weight([a,b])
    b['test']={'on_time_units':0.,'production_cost_usd':1e12}
    assert select_weight([a,b])==before


def test_complete_eligible_demand_is_counted_even_without_a_purchase_lot():
    p=small_planner((100,1200));p.plan_all()
    k=plan_kpis(p,eligible_ids(p))
    assert k['firm_units']==1300
    assert k['on_time_units']+k['late_units']+k['units_not_bought']==1300


def test_footwear_uses_2400_and_unconfirmed_or_uncertified_options_cannot_buy():
    p=small_planner()
    p.rows['P0']['category']='footwear'
    assert bought(p)==[]
    p.rows['P0']['category']='apparel'
    p.rows['P0']['has_order']=False
    assert bought(p)==[]
    p.rows['P0']['has_order']=True
    u=candidates(p);opts=options(p,u);opts['factory']='UNCERTIFIED'
    assert solve(p,.5,u,opts)['choice'].loc[0]==-1


def test_benchmark_reconciles_demand_and_does_not_select_using_later_outcomes():
    from engine.benchmark import network_results
    data,cfg=rolling_data()
    cfg['benchmark']=dict(tuning_seasons=['TRAIN'],test_seasons=['TEST'],weights=[0.,1.])
    p=Planner(data=data,config=cfg);p.plan_all()
    result=network_results(p)
    assert result['complete']
    assert result['universe']['units']==2400
    for approach in result['approaches']:
        k=approach['results']['all']
        assert k['on_time_units']+k['late_units']+k['units_not_bought']==2400
    changed=deepcopy(data);changed.tables['prs'].loc[1,'requested_qty']=999999
    q=Planner(data=changed,config=deepcopy(cfg));q.plan_all()
    future=network_results(q)
    assert future['selected_weight']==result['selected_weight']
    assert future['selection_steps']==result['selection_steps']
    assert all(a['results']['tuning']==b['results']['tuning'] for a,b in zip(result['approaches'],future['approaches']))
