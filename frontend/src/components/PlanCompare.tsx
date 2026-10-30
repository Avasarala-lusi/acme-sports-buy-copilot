import type { PlanKpis } from "../api/types";
import { int, moneyShort, pct } from "../lib/format";
import { cx } from "./ui";

type Better = "higher" | "lower" | null;
const ROWS: { key: keyof PlanKpis; label: string; fmt: (v: number) => string; better: Better; hint?: string }[] = [
  { key: "units_bought", label: "Units bought", fmt: int, better: "higher" },
  { key: "bought_pct", label: "Demand bought", fmt: (v) => pct(v, 1), better: "higher" },
  { key: "on_time_pct_of_firm", label: "Demand on time", fmt: (v) => pct(v, 1), better: "higher", hint: "units arriving by their requested date, as a share of all demand in the lots" },
  { key: "on_time_pct_of_bought", label: "Bought units on time", fmt: (v) => pct(v, 1), better: "higher" },
  { key: "expected_on_time_pct_of_bought", label: "Expected on time with lead-time variation", fmt: (v) => pct(v, 1), better: "higher" },
  { key: "cost_per_unit_usd", label: "Production cost per unit", fmt: (v) => `$${v.toFixed(2)}`, better: "lower" },
  { key: "production_cost_usd", label: "Production cost", fmt: moneyShort, better: null },
  { key: "units_not_bought", label: "Units not bought (planner)", fmt: int, better: "lower" },
  { key: "backup_units_pct", label: "Units at a backup factory", fmt: (v) => pct(v, 1), better: "lower" },
  { key: "weeks_over_100", label: "Factory-weeks over 100%", fmt: int, better: "lower" },
  { key: "peak_utilization_pct", label: "Peak weekly load", fmt: (v) => pct(v, 0), better: "lower" },
  { key: "orders_below_mpq", label: "Production orders below MPQ (not last chance)", fmt: int, better: "lower" },
];

export function PlanCompare({ columns, rows, highlight }: {
  columns: { key: string; label: string; sub?: string }[];
  rows: Record<string, PlanKpis>;
  highlight?: string;
  keys?: (keyof PlanKpis)[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="py-2 pr-3 font-medium">Measure</th>
            {columns.map((c) => (
              <th key={c.key} className={cx("px-3 py-2 text-right font-medium", c.key === highlight && "text-accent")}>
                {c.label}{c.sub && <div className="text-[10px] font-normal text-faint">{c.sub}</div>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => {
            const vals = columns.map((c) => rows[c.key]?.[r.key] as number | null | undefined);
            const nums = vals.filter((v): v is number => v != null);
            const best = r.better && nums.length > 1 ? (r.better === "higher" ? Math.max(...nums) : Math.min(...nums)) : null;
            return (
              <tr key={String(r.key)} className="border-b border-line/60 last:border-0">
                <td className="py-2 pr-3 text-muted" title={r.hint}>{r.label}</td>
                {vals.map((v, i) => (
                  <td key={columns[i].key} className={cx("font-num px-3 py-2 text-right",
                    best != null && v != null && Math.abs(v - best) < 1e-9 ? "text-good font-medium" : "text-ink")}>
                    {v == null ? "—" : r.fmt(v)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Pool several seasons' KPIs into one (sums, with shares recomputed). */
export function pool(parts: PlanKpis[]): PlanKpis {
  const s = (k: keyof PlanKpis) => parts.reduce((t, p) => t + ((p[k] as number) ?? 0), 0);
  const firm = s("firm_units"), bought = s("units_bought"), cost = s("production_cost_usd");
  const onTime = s("on_time_units"), expected = s("expected_on_time_units");
  const backup = parts.reduce((t, p) => t + p.backup_units_pct / 100 * p.units_bought, 0);
  const mpq = parts.some((p) => p.orders_below_mpq == null) ? null : s("orders_below_mpq");
  return {
    firm_units: firm, units_bought: bought, units_not_bought: firm - bought, bought_pct: firm ? bought / firm * 100 : 0,
    production_cost_usd: cost, cost_per_unit_usd: bought ? cost / bought : 0, on_time_units: onTime,
    on_time_pct_of_bought: bought ? onTime / bought * 100 : 0, on_time_pct_of_firm: firm ? onTime / firm * 100 : 0,
    expected_on_time_units: expected, expected_on_time_pct_of_bought: bought ? expected / bought * 100 : 0,
    backup_units_pct: bought ? backup / bought * 100 : 0,
    peak_utilization_pct: Math.max(...parts.map((p) => p.peak_utilization_pct)), weeks_over_100: s("weeks_over_100"),
    units_in_closed_weeks: s("units_in_closed_weeks"), orders_below_mpq: mpq,
  };
}
