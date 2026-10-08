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
}

export type Decision = "Buy" | "No-Go" | "Delay";

export interface Lot {
  lot_id: string;
  run_id: string;
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
  expected_arrival: string;
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
  decision: Decision;
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
}

export interface Plan {
  run_id: string;
  kpis: Kpis;
  kpis_automatic: Kpis;
  manual_changes: number;
  counts: { unresolved: number; future: number; waiting: number };
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
  qty_before: number;
  qty_removed: number;
  qty_after: number;
  nsv_at_risk_usd: number;
  suggested_rdd: string;
  moq_ok: boolean;
  fix: string | null;
  qty_after_fix: number;
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
      target_utilization_pct: number;
      capacity_warning: boolean;
    };

export interface PullForward {
  windows: { window: string; window_start: string; factory_id: string; units: number; avg_utilization_pct: number }[];
  recommendations: {
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
    moq_ok_for_market: boolean;
    backup_factory: string;
    extra_cost_if_routed_to_backup_usd: number;
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
}

export interface Settings {
  thresholds: {
    moq_per_market: number;
    mpq_apparel: number;
    mpq_footwear: number;
    backup_threshold_pct: number;
    piggyback_tolerance_pct: number;
    grouping_window_days: number;
  };
  items: { topic: string; setting: string; status: string }[];
}

export type Features = Record<"forecast" | "risk" | "optimizer" | "drill" | "benchmark" | "ask" | "data_health", boolean>;
