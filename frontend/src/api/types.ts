// Shapes returned by the planning API (api/main.py). Dates are ISO strings.

export interface Run {
  run_id: string;
  week_number: number;
  mrp_freeze_datetime_utc: string;
  as_is_plan_date: string;
  go_nogo_date: string;
  po_execution_date: string;
  factory_transmission_date: string;
  factory_confirm_deadline: string;
  season: string;
  range_version: string;
  quarter: string;
  is_buying_run: boolean;
}

export type Decision = "Buy" | "No-Go" | "Delay";
export type LotDecision = Decision | "Review";

export interface Lot {
  lot_id: string;
  run_id: string;
  plan_status: "Committed" | "Draft";
  buying_window: string;
  auto_decision: "Buy" | "Review";
  capacity_status: string;
  util_before_pct: number;
  util_after_pct: number;
  mfg_days: number;
  article_id: string;
  category: "footwear" | "apparel";
  market_destination: string;
  consolidated_qty: number;
  n_prs: number;
  pr_ids: string;
  earliest_rdd: string;
  suggested_rdd: string;
  primary_factory: string;
  assigned_factory: string;
  backup_routed: boolean;
  release_date: string;
  production_start: string;
  inventory_exposure_days: number;
  inventory_exposure_basis: string;
  lead_time_source: string;
  alternatives?: string;
  trans_days: number;
  on_time: boolean;
  on_time_units: number;
  unit_cost_usd: number;
  cost_multiplier: number;
  total_cost_usd: number;
  cost_delta_vs_primary_usd: number;
  nsv_usd: number;
  is_piggyback_applied: boolean;
  piggyback_source_window: string | null;
  last_chance: boolean;
  decision: LotDecision;
  decision_type: "auto" | "manual";
  override_note: string;
  reason: string;
  warnings: string;
  certified_factories: string[];
}

export interface Kpis {
  lots: number;
  units_bought: number;
  production_cost_usd: number;
  cost_per_unit_usd: number;
  units_on_time: number;
  on_time_pct: number;
  backup_routed_pct: number;
  lots_with_warnings: number;
  unresolved_units: number;
  forecast_excluded_units: number;
  review_lots: number;
  review_units: number;
}

export interface Plan {
  run_id: string;
  is_buying_run: boolean;
  plan_status: "Committed" | "Draft";
  buying_window: string;
  buy_date: string;
  next_buy_date: string;
  buying_run_id: string | null;
  kpis: Kpis;
  kpis_automatic: Kpis;
  manual_changes: number;
  decision_issues: string[];
  counts: { unresolved: number; future: number; review: number; waiting: number };
  units: { bought: number; review: number; unresolved: number; future: number; waiting: number };
  lots: Lot[];
}

export interface Requisition {
  pr_id: string;
  article_id: string;
  market_destination: string;
  requested_qty: number;
  rdd_original: string;
  outcome: string;
  reason: string;
  release_primary?: string;
}

export interface LotRequisition {
  inventory_exposure_days: number;
  pr_id: string;
  size_id: string;
  channel_id: "01" | "02";
  requested_qty: number;
  rdd_original: string;
  customer_id: string | null;
  nsv: number;
}

export interface Customer {
  customer_id: string;
  name: string | null;
  segment: string | null;
  credit_rating: string | null;
  n_prs: number;
}

export interface Factory {
  factory_id: string;
  country: string;
  specialization: string;
  weekly_capacity_units: number;
  cost_multiplier: number;
  backup_factory: string;
}

export interface Overrides {
  lots: Record<string, { decision: Decision; factory: string | null; note: string; updated_at: string }>;
  held_customers: string[];
}

export interface HoldLot {
  lot_id: string;
  article_id: string;
  market_destination: string;
  assigned_factory: string;
  qty_before: number;
  qty_removed: number;
  qty_after: number;
  nsv_at_risk_usd: number;
  suggested_rdd: string;
  moq_ok: boolean;
  fix: string | null;
  pulled_pr_ids: string;
  qty_after_fix: number;
  moq_ok_after_fix: boolean;
  mpq: number;
  factory_total_after: number;
  mpq_ok_after_fix: boolean;
  factory_load_after_pct: number | null;
}

export interface HoldResult {
  customer_id: string;
  lots_affected: number;
  nsv_at_risk_usd: number;
  lots: HoldLot[];
  sizes: { lot_id: string; pr_id: string; size_id: string; qty_removed: number; nsv_usd: number }[];
  moq_alerts: HoldLot[];
}

export interface DelayResult {
  factory: string;
  days: number;
  lots_late: number;
  nsv_at_risk_usd: number;
  lots: {
    lot_id: string;
    article_id: string;
    market_destination: string;
    qty: number;
    rdd: string;
    arrival_before: string;
    arrival_after: string;
    late_after: boolean;
    late_units: number;
    nsv_at_risk_usd: number;
  }[];
  customers: { customer_id: string | null; units: number; nsv_at_risk_usd: number }[];
}

export type SwapResult =
  | { valid: false; message: string }
  | {
      valid: true;
      lot_id: string;
      from_factory: string;
      to_factory: string;
      cost_before_usd: number;
      cost_after_usd: number;
      cost_delta_usd: number;
      cost_multiplier_before: number;
      cost_multiplier_after: number;
      lead_time_delta_days: number;
      arrival_before: string;
      arrival_after: string;
      on_time_after: boolean;
      moq_still_met: boolean;
      target_load_before_pct: number;
      target_utilization_pct: number;
      source_load_before_pct: number;
      source_load_after_pct: number;
      capacity_warning: boolean;
      over_capacity: boolean;
      mpq: number;
      source_total_after: number;
      target_total_after: number;
      mpq_source_ok: boolean;
      mpq_target_ok: boolean;
    };

export interface PullForward {
  windows: {
    window: string;
    window_start: string;
    factory_id: string;
    units: number;
    weeks: number;
    avg_utilization_pct: number;
    peak_utilization_pct: number;
  }[];
  recommendations: {
    pr_ids: string[];
    target_run_id: string | null;
    source_run_id: string | null;
    certification_ok: boolean;
    window_visibility_ok: boolean;
    earliness_ok: boolean;
    factory_id: string;
    overloaded_window: string;
    overloaded_util_pct: number;
    article_id: string;
    market_destination: string;
    n_prs: number;
    units: number;
    recommendation: string;
    target_window: string | null;
    days_earlier: number;
    capacity_ok: boolean;
    moq_ok_for_market: boolean;
    mpq_target_ok: boolean;
    mpq_source_ok: boolean;
    source_peak_after_pct: number;
    target_peak_before_pct: number | null;
    target_peak_after_pct: number | null;
    backup_factory: string | null;
    extra_cost_if_routed_to_backup_usd: number | null;
    actionable: boolean;
  }[];
}

export interface CapacityRow {
  factory_id: string;
  week: string;
  units: number;
  weekly_capacity: number;
  utilization_pct: number;
}

export interface Checks {
  checks: Record<string, boolean>;
  passed: boolean;
  prs_seen: number;
  units_seen: number;
  prs_by_outcome: Record<string, number>;
  units_by_outcome: Record<string, number>;
  rule_violations: number;
  comparison: { metric: string; our_plan: number; as_is_reference: number }[];
  baseline: { metric: string; baseline: number; our_plan: number; better_if: "lower" | "higher" | null; note: string; improved: boolean | null }[];
}

export interface Settings {
  thresholds: {
    moq_per_market: number;
    mpq_apparel: number;
    mpq_footwear: number;
    backup_threshold_pct: number;
    hard_limit_pct: number;
    piggyback_tolerance_pct: number;
    grouping_window_days: number;
  };
  items: { topic: string; setting: string; status: string }[];
}

export type Features = Record<"forecast" | "risk" | "optimizer" | "drill" | "benchmark" | "ask" | "data_health", boolean>;

export type TrendPoint = Kpis & { run_id: string; buying_window: string };

export interface Route {
  factory_id: string;
  market: string;
  lots: number;
  units: number;
  bought_units: number;
  backup_units: number;
  review_units: number;
  cost_usd: number;
  on_time_units: number;
  late_lots: number;
  articles: number;
  max_load_pct: number;
}

export interface Network {
  run_id: string;
  routes: Route[];
  factories: { factory_id: string; country: string; weekly_capacity_units: number; cost_multiplier: number }[];
}

export interface ForecastView {
  run_id: string;
  origin_week: number;
  model: string;
  horizon_weeks: number;
  stage_coverage_pct: number;
  history: { factory: string; week: number; date: string; units: number }[];
  intake: { factory: string; week: number; date: string; horizon: number; p10: number; p50: number; p90: number; actual: number | null }[];
  load: {
    factory_id: string; week: string; capacity: number; committed_units: number; known_open_units: number;
    forecast_units: number; known_pct: number; forecast_pct: number; forecast_p90_pct: number;
  }[];
  windows: { window: string; factory_id: string; known_peak_pct: number; forecast_peak_pct: number; p90_peak_pct: number; early_warning: boolean; forecast_units: number }[];
}

export interface Backtest {
  default_model: string;
  coverage_pct: number;
  origins: number;
  horizon_weeks: number;
  overall: { model: string; wape_pct: number }[];
  by_horizon: { model: string; band: string; wape_pct: number }[];
  network_by_horizon: { horizon: number; wape_pct: number }[];
}

export interface ImpactRow {
  units: number;
  baseline_on_time_pct: number;
  plan_on_time_pct: number;
  plan_late_units: number;
  not_bought_units: number;
  extra_late_or_unbought_units: number;
  usd_at_price: number;
  plan_median_days_late: number;
  [dimension: string]: string | number;
}

export interface ImpactStatus { units: number; share_pct: number; usd_at_price: number; usd_order_value: number }

export interface Impact {
  price_per_unit_usd: number;
  price_range_usd: [number, number];
  order_value_per_unit_usd: number;
  baseline_units_above_capacity: number;
  baseline_units_above_capacity_pct: number;
  baseline_weeks_over_capacity: number;
  baseline_peak_utilization_pct: number;
  firm_units_per_week: number;
  network_weekly_capacity: number;
  firm_requisitions: number;
  firm_units: number;
  plan: Record<string, ImpactStatus>;
  baseline: Record<string, ImpactStatus>;
  plan_median_days_late: number;
  extra_units_not_on_time: number;
  extra_usd_at_price: number;
  extra_usd_range: [number, number];
  largest_market_share_of_extra_pct: number;
  late_bands: { band: string; plan_units: number; baseline_units: number }[];
  by_market: ImpactRow[];
  by_category: ImpactRow[];
  by_product_line: ImpactRow[];
  by_channel: ImpactRow[];
  by_segment: ImpactRow[];
  top_customers: ImpactRow[];
}

export interface Seasonality {
  weeks: number;
  stl_seasonal_strength: number;
  acf_lag52: number;
  acf_bound_95: number;
  acf_lag52_significant: boolean;
  kruskal_stage_h: number;
  kruskal_stage_p: number;
  kruskal_month_h: number;
  kruskal_month_p: number;
  stage_mean_units: Record<string, number>;
  stage_ratio_max_min: number;
}
