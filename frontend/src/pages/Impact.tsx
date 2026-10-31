import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CircleDollarSign, Clock, Factory, PackageX } from "lucide-react";
import { api } from "../api/client";
import type { ImpactRow, ImpactStatus } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Badge, Card, ErrorBox, Kpi, Loading, PageHeader, SectionTitle, Segmented, cx } from "../components/ui";
import { int, moneyShort, pct } from "../lib/format";

const PRICES = ["19", "21", "22"] as const;
type Dim = "by_market" | "by_product_line" | "by_category" | "by_channel" | "by_segment" | "top_customers" | "by_factory" | "by_article";
const DIMS: { value: Dim; label: string; key: string }[] = [
  { value: "by_market", label: "Market", key: "market" },
  { value: "by_product_line", label: "Product line", key: "product_line" },
  { value: "by_category", label: "Category", key: "category" },
  { value: "by_channel", label: "Channel", key: "channel" },
  { value: "by_segment", label: "Customer type", key: "segment" },
  { value: "top_customers", label: "Top customers", key: "customer" },
  { value: "by_factory", label: "Factory", key: "factory" },
  { value: "by_article", label: "Article", key: "article_id" },
];
const STATES = [
  { key: "on time", label: "On time", color: "var(--color-status-good)" },
  { key: "late", label: "Late", color: "var(--color-status-warning)" },
  { key: "not bought (planner)", label: "Not bought: planner decision needed", color: "var(--color-status-critical)" },
];

function Split({ title, data }: { title: string; data: Record<string, ImpactStatus> }) {
  const total = STATES.reduce((t, s) => t + (data[s.key]?.units ?? 0), 0) || 1;
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between text-sm">
        <span className="font-medium">{title}</span>
        <span className="font-num text-xs text-faint">{int(total)} units</span>
      </div>
      <div className="flex h-3 gap-[2px] overflow-hidden rounded-full">
        {STATES.map((s) => (data[s.key]?.units ? (
          <div key={s.key} title={`${s.label}: ${int(data[s.key].units)} units`} style={{ flexGrow: data[s.key].units, background: s.color }}
            className="first:rounded-l-full last:rounded-r-full" />
        ) : null))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {STATES.filter((s) => data[s.key]?.units).map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <i className="h-2 w-2 rounded-full" style={{ background: s.color }} />
            {s.label} <span className="font-num text-ink">{pct((data[s.key].units / total) * 100, 1)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function Impact() {
  const [price, setPrice] = useState<(typeof PRICES)[number]>("21");
  const [dim, setDim] = useState<Dim>("by_market");
  const q = useQuery({ queryKey: ["impact", price], queryFn: () => api.impact(Number(price)) });

  if (q.isLoading) return <Loading label="Measuring late and undelivered demand…" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const r = q.data!;
  const d = DIMS.find((x) => x.value === dim)!;
  const planLate = r.plan["late"]?.units ?? 0;
  const notBought = r.plan["not bought (planner)"]?.units ?? 0;

  return (
    <>
      <PageHeader eyebrow="Simulated planning impact · automatic plan vs baseline" title="Who is affected, and how much"
        subtitle={`Historical automatic-plan comparison, not the current manual scenario or observed deliveries. Includes ${int(r.unconfirmed_conflict_units)} units of unconfirmed last-chance conflicts awaiting a decision. Dollar exposure uses an illustrative $${r.price_per_unit_usd}/unit.`}
        actions={<Segmented value={price} onChange={setPrice} options={PRICES.map((p) => ({ value: p, label: `$${p}/unit` }))} />} />

      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Clock} label="On time · baseline → plan"
          value={`${pct(r.baseline["on time"]?.share_pct ?? 0, 0)} → ${pct(r.plan["on time"]?.share_pct ?? 0, 0)}`}
          sub={`of ${int(r.firm_units)} compared units; purchases only: ${pct((r.plan["on time"]?.units ?? 0) / Math.max(1, (r.plan["on time"]?.units ?? 0) + planLate) * 100, 1)}`} />
        <Kpi icon={AlertTriangle} label="Delivered late (plan)" value={int(planLate)}
          sub={`median ${Math.round(r.plan_median_days_late)} days late in the simulated schedule`} />
        <Kpi icon={PackageX} label="Not bought" value={int(notBought)} sub="capacity, minimums, timing or eligibility conflicts; planner decides" />
        <Kpi icon={CircleDollarSign} label={`Value not on time vs baseline · $${r.price_per_unit_usd}/unit`}
          value={moneyShort(r.extra_usd_at_price)} sub={`${moneyShort(r.extra_usd_range[0])} – ${moneyShort(r.extra_usd_range[1])} at $19–22`} />
      </div>

      <div className="mb-5 grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <Card className="space-y-5 p-5">
          <Split title="Baseline (assignments in the data)" data={r.baseline} />
          <Split title="Our plan" data={r.plan} />
        </Card>
        <Card className="p-5">
          <div className="mb-2 flex items-center gap-2 text-[15px] font-semibold"><Factory size={16} className="text-accent" /> Why the baseline looks better</div>
          <p className="text-sm text-muted">
            The supplied baseline does not enforce our capacity checks. It places{" "}
            <span className="font-num text-ink">{int(r.baseline_units_above_capacity)}</span> units
            ({pct(r.baseline_units_above_capacity_pct, 0)} of compared demand) beyond 100% of their capacity, in{" "}
            {r.baseline_weeks_over_capacity} factory-weeks, peaking at {pct(r.baseline_peak_utilization_pct, 0)}.
          </p>
          <p className="mt-2 text-sm text-muted">
            Compared demand averages <span className="font-num text-ink">{int(r.firm_units_per_week)}</span> units a week against a network
            capacity of <span className="font-num text-ink">{int(r.network_weekly_capacity)}</span>. Our plan never exceeds 100%, so the
            unpurchased units ({int(notBought)}) need review. Capacity, timing, minimums and eligibility all contribute; capacity is not the sole cause of the timing gap.
          </p>
          <p className="mt-3 rounded-lg bg-sidebar p-2.5 text-xs text-faint">
            Footnote: ${r.price_per_unit_usd}/unit is Roberto’s illustrative assumption (sensitivity $19–22), not an actual penalty or profit loss. Unbought demand is separate from late purchases. Factory breakdown uses the assigned factory for purchases and intended primary for unbought demand. The sales orders in the
            data average {moneyShort(r.order_value_per_unit_usd)} per unit, so order-value figures are about{" "}
            {Math.round(r.order_value_per_unit_usd / r.price_per_unit_usd)}× higher.
          </p>
        </Card>
      </div>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <SectionTitle hint={`largest market carries ${pct(r.largest_market_share_of_extra_pct, 0)} of the gap: spread across all markets`}>
          Where the gap falls
        </SectionTitle>
        <Segmented value={dim} onChange={setDim} options={DIMS.map((x) => ({ value: x.value, label: x.label }))} />
      </div>
      <DataTable rows={r[dim] as ImpactRow[]} rowKey={(x) => String(x[d.key])} maxHeight="55vh" columns={[
        { key: d.key, header: d.label, render: (x) => <span className="font-medium">{String(x[d.key] || "—")}</span> },
        { key: "units", header: "Firm units", align: "right", render: (x) => <span className="font-num">{int(x.units)}</span> },
        { key: "baseline_on_time_pct", header: "On time · baseline", align: "right", render: (x) => <span className="font-num text-muted">{pct(x.baseline_on_time_pct, 0)}</span> },
        { key: "plan_on_time_pct", header: "On time · plan", align: "right",
          render: (x) => <span className={cx("font-num", x.plan_on_time_pct < 40 ? "text-bad" : "text-warn")}>{pct(x.plan_on_time_pct, 0)}</span> },
        { key: "plan_late_units", header: "Late", align: "right", render: (x) => <span className="font-num">{int(x.plan_late_units)}</span> },
        { key: "not_bought_units", header: "Not bought", align: "right", render: (x) => <span className="font-num">{int(x.not_bought_units)}</span> },
        { key: "plan_median_days_late", header: "Median days late", align: "right", render: (x) => <span className="font-num">{Math.round(x.plan_median_days_late)}</span> },
        { key: "usd_at_price", header: `Value vs baseline · $${r.price_per_unit_usd}`, align: "right",
          render: (x) => <span className="font-num">{moneyShort(x.usd_at_price)}</span> },
      ]} />

      <Card className="mt-5 p-5">
        <SectionTitle hint="units delivered late, by how late">How late</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-4">
          {r.late_bands.map((b) => (
            <div key={b.band} className="rounded-xl border border-line p-3">
              <div className="text-xs text-muted">{b.band}</div>
              <div className="font-num mt-1 text-lg">{int(b.plan_units)}</div>
              <div className="text-[11px] text-faint">baseline {int(b.baseline_units)}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-faint">
          <Badge tone="good">no automatic purchase arrives more than 60 days late</Badge>
          demand that would be later stays with the planner
        </div>
      </Card>
    </>
  );
}
