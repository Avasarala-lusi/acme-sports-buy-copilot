"""Small regression examples independent of the client CSVs."""
from copy import deepcopy
from datetime import date
import pandas as pd
import pytest
from engine.calendar import BuyingCalendar
from engine.capacity import CapacityLedger
from engine.config import load_config
from engine.data_loader import AcmeData
from engine.planner import Planner, BOUGHT
from engine.overrides import OverrideStore,effective_lots
from engine.accounting import accounting_report,rule_violations


def small_planner(quantities=(1200,),rdds=None,mfg=7,capacity=10000,last_chance=False):
    rdds=rdds or ['2026-01-21']*len(quantities)
    runs=pd.DataFrame([dict(run_id=f'R{i}',week_number=i,po_execution_date=pd.Timestamp(d),
                           mrp_freeze_datetime_utc=pd.Timestamp(d)-pd.Timedelta(days=3))
                       for i,d in enumerate(['2026-01-07','2026-01-14','2026-01-21','2026-01-28','2026-02-11'],1)])
    prs=pd.DataFrame([dict(pr_id=f'P{i}',run_id='R1',article_id='A',market_destination='US',channel_id='01',
        customer_id=f'C{i}',size_id='M',requested_qty=q,rdd_original=pd.Timestamp(rdds[i]),
        mrp_run_date=pd.Timestamp('2026-01-04'),assigned_factory='F',backup_triggered=False,
        manufacturing_lead_time=mfg,transportation_lead_time=0)
        for i,q in enumerate(quantities)])
    tables=dict(runs=runs,prs=prs,
        articles=pd.DataFrame([dict(article_id='A',category='apparel',unit_cost_usd=1,
            early_buy_flag=False,last_chance_flag=last_chance,primary_factory='F',backup_factory=None)]),
        factories=pd.DataFrame([dict(factory_id='F',backup_factory=None,weekly_capacity_units=capacity,
            cost_multiplier=1,mfg_lt_min_days=mfg,mfg_lt_max_days=mfg,trans_lt_min_days=0,trans_lt_max_days=0)]),
        cert_matrix=pd.DataFrame([dict(article_id='A',factory_id='F',is_certified=True)]),
        sales_orders=pd.DataFrame([dict(pr_id=f'P{i}',net_sales_value=100+i) for i in range(len(quantities))]))
    return Planner(AcmeData(tables),deepcopy(load_config()))


def test_mid_eom_calendar_navigation():
    cal=BuyingCalendar()
    assert cal.dates_in_month(2025,8)==[date(2025,8,13),date(2025,8,27)]
    assert cal.after(date(2025,8,13))==date(2025,8,27)
    assert cal.on_or_before(date(2025,8,20))==date(2025,8,13)
    assert len(cal.windows_from(date(2025,8,13),4))==5


def test_partial_weeks_are_business_day_weighted_and_conserve_units():
    ledger=CapacityLedger({'F':1000})
    ledger.add('F',pd.Timestamp('2026-01-07'),10,800)
    assert ledger.units['F'][date(2026,1,5)]==pytest.approx(300)
    assert ledger.units['F'][date(2026,1,12)]==pytest.approx(500)
    assert ledger.table().units.sum()==pytest.approx(800)
    ledger.remove('F',pd.Timestamp('2026-01-07'),10,800)
    assert ledger.table().empty


def test_fractional_midpoint_is_not_truncated():
    ledger=CapacityLedger({'F':1000})
    ledger.add('F',pd.Timestamp('2026-01-05'),7.5,550)
    assert ledger.units['F'][date(2026,1,5)]==pytest.approx(500)
    assert ledger.units['F'][date(2026,1,12)]==pytest.approx(50)


def test_date_precision_does_not_treat_noon_as_a_late_day():
    from engine.rules.timing import delivery_date
    assert delivery_date('2026-01-14',7.5,0)==pd.Timestamp('2026-01-21')


def test_early_suggested_rdd_is_not_clamped_to_original():
    p=small_planner(rdds=['2026-02-03']);p.plan_all()
    lot=p.bought_lots().iloc[0]
    assert lot.production_start==pd.Timestamp('2026-01-14')
    assert lot.suggested_rdd==pd.Timestamp('2026-01-21')
    assert lot.inventory_exposure_days==-13
    assert 'expected_arrival' not in p.all_lots()
    assert lot.lead_time_source=='PR-provided'
    assert rule_violations(p).empty


def test_priority_is_last_chance_then_release_then_rdd_then_revenue():
    p=small_planner((1200,1200),['2026-01-21','2026-02-01'])
    assert p.priority_key(['P0'])<p.priority_key(['P1'])
    p.rows['P1']['last_chance']=True
    assert p.priority_key(['P1'])<p.priority_key(['P0'])
    p.rows['P0']['last_chance']=True
    p.rows['P1']['release_primary']=p.rows['P0']['release_primary']
    assert p.priority_key(['P0'])<p.priority_key(['P1'])
    p.rows['P1']['rdd_original']=p.rows['P0']['rdd_original']
    assert p.priority_key(['P1'])<p.priority_key(['P0'])
    p.rows['P1']['nsv']=p.rows['P0']['nsv']
    p.rows['P1']['has_order']=False
    assert p.priority_key(['P0'])<p.priority_key(['P1'])


def test_mpq_cannot_pool_distant_rdds():
    p=small_planner((700,500),['2026-01-21','2026-02-10'],mfg=50)
    p.plan_through('R2')
    assert p.bought_lots().empty
    assert p.pr_outcomes().outcome.eq('UNRESOLVED_MPQ').all()


def test_last_chance_never_waives_hard_ceiling():
    p=small_planner(capacity=100,last_chance=True);p.plan_all()
    assert p.bought_lots().empty
    assert set(p.pr_outcomes().outcome)=={'PLANNER_REVIEW'}
    assert p.ledger.table().empty


def test_delay_replays_later_week_without_duplicate_purchase(tmp_path):
    p=small_planner();p.plan_all()
    before=p.bought_lots().copy()
    store=OverrideStore(tmp_path/'decisions.json')
    lot=p.results['R2'].lots.iloc[0]
    store.set_lot(p,'R2',lot.lot_id,'Delay')
    effective=store.replay(p);effective.plan_all()
    assert effective_lots(p,'R2',store).iloc[0].decision=='Delay'
    bought=effective.bought_lots()
    assert len(bought)==1 and bought.iloc[0].run_id=='R4'
    assert bought.iloc[0].production_start==pd.Timestamp('2026-01-28')
    assert effective.ledger.units['F'].get(date(2026,1,12),0)==0
    assert accounting_report(effective)['passed']
    assert p.bought_lots().equals(before)
    store.reset('R2')
    assert store.replay(p) is p


def test_no_go_cancels_and_frees_capacity(tmp_path):
    p=small_planner();p.plan_all()
    store=OverrideStore(tmp_path/'decisions.json')
    store.set_lot(p,'R2',p.results['R2'].lots.iloc[0].lot_id,'No-Go')
    effective=store.replay(p);effective.plan_all()
    assert effective.bought_lots().empty
    assert effective.ledger.table().empty
    assert effective.pr_outcomes().iloc[0].outcome=='CANCELLED'


def test_hold_rechecks_mpq_and_keeps_uncommitted_demand(tmp_path):
    p=small_planner((600,600));p.plan_all()
    store=OverrideStore(tmp_path/'decisions.json');store.hold_customer('R2','C0')
    effective=store.replay(p);effective.plan_through('R2')
    assert effective.ledger.table().empty
    assert set(effective.open)=={'P0','P1'}
    assert effective_lots(p,'R2',store).iloc[0].decision=='Review'
    assert effective_lots(p,'R2',store).iloc[0].consolidated_qty==600
    effective.plan_all()
    assert effective.bought_lots().empty  # overdue demand requires a planner decision
    lot=effective.results['R4'].lots.iloc[0]
    assert set(lot.pr_ids.split(','))=={'P0','P1'}
    store.set_lot(effective,'R4',lot.lot_id,'Buy',note='Approve late purchase after the hold')
    approved=store.replay(p);approved.plan_all()
    assert approved.bought_lots().consolidated_qty.sum()==1200


def test_manual_buy_cannot_override_capacity(tmp_path):
    p=small_planner(capacity=100);p.plan_all()
    store=OverrideStore(tmp_path/'decisions.json')
    lot=p.results['R2'].lots.iloc[0]
    store.set_lot(p,'R2',lot.lot_id,'Buy',note='request approval')
    assert effective_lots(p,'R2',store).iloc[0].decision=='Review'
    assert store.replay(p).ledger.table().empty


def test_accepted_pull_forward_is_saved_exported_and_replayed(tmp_path):
    from engine.pull_forward import recommendations
    from engine.output import fact_buy_plan_suggestions
    p=small_planner((800,1200),['2026-02-11','2026-02-06'],capacity=1000)
    p.data.tables['prs'].loc[0,'manufacturing_lead_time']=28
    cfg=deepcopy(p.cfg);cfg['quantities']['mpq']['apparel']=800
    p=Planner(p.data,cfg);p.plan_through('R2')
    rec=recommendations(p,'R2')
    move=rec[rec.actionable].iloc[0]
    assert move.target_run_id=='R2' and move.source_run_id=='R4'
    store=OverrideStore(tmp_path/'decisions.json')
    store.accept_pull(p,'R2',move.pr_ids,move.target_run_id)
    effective=store.replay(p);effective.plan_all()
    bought=effective.bought_lots()
    assert bought.consolidated_qty.sum()==2000
    assert bought.pr_ids.str.split(',').explode().is_unique
    fact=fact_buy_plan_suggestions(effective)
    assert fact.is_piggyback_applied.any()
    assert set(fact.loc[fact.is_piggyback_applied,'piggyback_source_window'])=={'R4'}
    assert accounting_report(effective)['passed']
    assert effective.ledger.table().utilization_pct.max()<85


def test_duplicate_pull_acceptance_rejected(tmp_path):
    store=OverrideStore(tmp_path/'decisions.json')
    p=small_planner();p.plan_through('R2')
    with pytest.raises(ValueError,match='not feasible'):
        store.accept_pull(p,'R2',['P0'],'R2')


def test_unmatched_legacy_decision_fails_closed(tmp_path):
    p=small_planner();p.plan_all()
    store=OverrideStore(tmp_path/'decisions.json')
    store.run('R2')['lots']['old-row-position-id']={'decision':'No-Go'}
    store.save()
    effective=store.replay(p);effective.plan_through('R2')
    assert effective.decision_issues
    assert effective.ledger.table().empty
    assert effective_lots(p,'R2',store).iloc[0].decision=='Review'


def test_concurrent_requests_do_not_duplicate_commitments_and_cache_roundtrips():
    from concurrent.futures import ThreadPoolExecutor
    import pickle
    p=small_planner()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(p.plan_through,['R5','R4','R5']))
    assert len(p.bought_lots())==1
    assert accounting_report(p)['passed']
    restored=pickle.loads(pickle.dumps(p))
    assert restored.bought_lots().equals(p.bought_lots())
