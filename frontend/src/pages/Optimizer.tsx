import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Legend, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { CircleDollarSign, Clock, PackageCheck, Warehouse } from "lucide-react";
import { api } from "../api/client";
import type { PlanChange } from "../api/types";
import { DataTable } from "../components/DataTable";
import { PlanCompare } from "../components/PlanCompare";
import { Badge, Card, ErrorBox, Kpi, Loading, PageHeader, SectionTitle } from "../components/ui";
import { useToken } from "../lib/theme";
import { int, moneyShort, pct } from "../lib/format";

const short = (f: string | null) => (f ? f.replace("ACME-", "") : "not bought");
const weightName = (w: number) => (w === 0 ? "Cost-focused" : w === 1 ? "Service-focused" : w === 0.5 ? "Balanced" : w < 0.5 ? "More cost-focused" : "More service-focused");

export function Optimizer() {
  const q = useQuery({ queryKey: ["network-plans"], queryFn: api.networkPlans, staleTime: Infinity });
  const [idx, setIdx] = useState<number | null>(null);
  const s1 = useToken("--color-series-1"), s2 = useToken("--color-series-2"), s3 = useToken("--color-series-3");
  const grid = useToken("--color-grid"), axis = useToken("--color-axis"), ink = useToken("--color-ink");
  const panel = useToken("--color-panel"), line = useToken("--color-line");

  const d = q.data;
  const weights = d?.weights ?? [];
  const i = idx ?? Math.max(0, weights.indexOf(d?.selected_weight ?? 0.5));
  const w = weights[i] ?? 0.5;
  const opt = d?.approaches.find((a) => a.kind === "optimiser" && a.weight === w);
  const rules = d?.approaches.find((a) => a.key === "rules");
  const asIs = d?.approaches.find((a) => a.key === "as_is");
  const plan = d?.plans.find((p) => p.weight === w);

  const frontier = useMemo(() => (d?.approaches ?? []).filter((a) => a.kind === "optimiser").map((a) => ({
    x: a.results.all.cost_per_unit_usd, y: a.results.all.on_time_pct_of_firm, name: weightName(a.weight!), w: a.weight,
  })), [d]);

  const mix = plan?.by_factory ?? [];

  if (q.isLoading) return <Loading label="Replaying five settings. A fresh full calculation can take 15–25 minutes; completed settings are cached…" />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!d || !opt || !rules || !asIs) return null;
  const o = opt.results.all, r = rules.results.all;
  const tooltip = { contentStyle: { background: panel, border: `1px solid ${line}`, borderRadius: 10, fontSize: 12 }, labelStyle: { color: ink } };

  return (
    <>
      <PageHeader eyebrow="Historical comparison · one buying window at a time" title="Cost vs. service"
        subtitle={`Historical replay across all supplied runs, independent of the week selector. Compare the same ${int(d.universe.requisitions)} eligible requests (${int(d.universe.units)} units). Each window sees known demand and retains prior commitments. Priority and quantity/capacity checks come before cost or planned on-time service. This comparison does not change saved purchases.`} />

      {!d.complete && <Card className="mb-5 p-5">Validation is incomplete. Do not use these figures as verified improvements.</Card>}
      <Card className="mb-5 p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-medium">{weightName(w)} <span className="font-num text-faint">· weight {w}</span>
            {w === d.selected_weight && <Badge tone="good">recommended</Badge>}</div>
          <div className="text-xs text-faint">Replay {opt.seconds?.toFixed(0)} s · {opt.validation?.passed ? "Checks passed" : "Review required"}</div>
        </div>
        <input type="range" min={0} max={weights.length - 1} step={1} value={i} onChange={(e) => setIdx(Number(e.target.value))}
          className="w-full accent-[var(--color-accent)]" aria-label="Cost vs service weight" />
        <div className="mt-1 flex justify-between text-xs text-muted"><span>Cost-focused</span><span>Planned-service-focused</span></div>
        <p className="mt-3 text-xs text-muted">Each setting optimizes the current window. Earlier choices affect later capacity, so moving right does not guarantee better on-time results over the full history. Compare the measured outcomes below.</p>
      </Card>

      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={PackageCheck} label="Units bought · rules → optimiser" value={`${int(r.units_bought)} → ${int(o.units_bought)}`}
          sub={`${o.units_bought >= r.units_bought ? "+" : ""}${int(o.units_bought - r.units_bought)} of the ${int(o.firm_units)} eligible units`} />
        <Kpi icon={Clock} label="Eligible demand planned on time" value={`${pct(r.on_time_pct_of_firm, 1)} → ${pct(o.on_time_pct_of_firm, 1)}`}
          sub={`bought units on time ${pct(r.on_time_pct_of_bought, 0)} → ${pct(o.on_time_pct_of_bought, 0)}`} />
        <Kpi icon={CircleDollarSign} label="Production cost per unit" value={`$${r.cost_per_unit_usd.toFixed(2)} → $${o.cost_per_unit_usd.toFixed(2)}`}
          sub={`total ${moneyShort(r.production_cost_usd)} → ${moneyShort(o.production_cost_usd)}`} />
        <Kpi icon={Warehouse} label="Units at a backup factory" value={`${pct(r.backup_units_pct, 0)} → ${pct(o.backup_units_pct, 0)}`}
          sub={`no factory-week above 100% (peak ${pct(o.peak_utilization_pct, 0)})`} />
      </div>

      <div className="mb-5 grid gap-4 xl:grid-cols-[1.25fr_1fr]">
        <Card className="p-5">
          <SectionTitle hint="same eligible demand; unresolved units included">Rules vs. optimiser</SectionTitle>
          <PlanCompare highlight="opt" rows={{ as_is: asIs.results.all, rules: r, opt: o }}
            columns={[{ key: "as_is", label: "Supplied reference", sub: "capacity ignored" }, { key: "rules", label: "Rule engine" },
              { key: "opt", label: "Optimiser", sub: weightName(w) }]} />
        </Card>
        <Card className="p-5">
          <SectionTitle hint="each dot is one slider position">The trade-off</SectionTitle>
          <div className="h-[300px]">
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid stroke={grid} />
                <XAxis type="number" dataKey="x" name="Cost per unit" unit="$" domain={["auto", "auto"]} tick={{ fontSize: 11, fill: axis }}
                  tickFormatter={(v: number) => v.toFixed(0)} label={{ value: "production cost per unit ($)", position: "insideBottom", offset: -4, fontSize: 11, fill: axis }} />
                <YAxis type="number" dataKey="y" name="On time" unit="%" domain={["auto", "auto"]} tick={{ fontSize: 11, fill: axis }} width={48}
                  tickFormatter={(v: number) => v.toFixed(0)} />
                <ZAxis range={[90, 90]} />
                <Tooltip {...tooltip} formatter={(v: number, n: string) => [n === "Cost per unit" ? `$${v.toFixed(2)}` : `${v.toFixed(1)}%`, n]} />
                <Legend wrapperStyle={{ fontSize: 12, color: ink }} />
                <Scatter name="Optimiser" data={frontier} fill={s1} line={{ stroke: s1 }} isAnimationActive={false} />
                <Scatter name="Rule engine" data={[{ x: r.cost_per_unit_usd, y: r.on_time_pct_of_firm }]} fill={s2} isAnimationActive={false} />
                <Scatter name="Selected" data={[{ x: o.cost_per_unit_usd, y: o.on_time_pct_of_firm }]} fill={s3} shape="star" isAnimationActive={false} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-faint">{d.baseline_note}</p>
        </Card>
      </div>

      <Card className="mb-5 p-5">
        <SectionTitle hint="units by factory, optimiser plan">Where the optimiser makes it</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
          {mix.map((f) => (
            <div key={f.factory_id} className="rounded-xl border border-line p-3">
              <div className="text-xs text-muted">{short(f.factory_id)}</div>
              <div className="font-num mt-1 text-lg">{int(f.units)}</div>
              <div className="text-[11px] text-faint">{pct(f.on_time_pct, 0)} on time · {moneyShort(f.production_cost_usd)}</div>
            </div>
          ))}
        </div>
      </Card>

      <SectionTitle hint={`largest ${plan?.changes.length ?? 0} requests with different factory, timing or purchase outcomes`}>What changes</SectionTitle>
      <DataTable<PlanChange> rows={plan?.changes ?? []} rowKey={(x) => x.pr_id ?? x.lot_id} maxHeight="55vh" columns={[
        { key: "pr_id", header: "PR" },
        { key: "rule_run_id", header: "Rule purchase" },
        { key: "plan_run_id", header: "Optimizer purchase" },
        { key: "article_id", header: "Article" },
        { key: "market_destination", header: "Market" },
        { key: "qty", header: "Units", align: "right", render: (x) => <span className="font-num">{int(x.qty)}</span> },
        { key: "rule_factory", header: "Rules", render: (x) => <span className={x.rule_factory ? "" : "text-faint"}>{short(x.rule_factory)}</span> },
        { key: "plan_factory", header: "Optimiser", render: (x) => <span className={x.plan_factory ? "font-medium" : "text-faint"}>{short(x.plan_factory)}</span> },
        { key: "plan_on_time_units", header: "On-time units (rules → opt.)", align: "right",
          render: (x) => <span className="font-num">{int(x.rule_on_time_units)} → {int(x.plan_on_time_units)}</span> },
        { key: "cost_change_usd", header: "Cost change", align: "right", render: (x) => <span className="font-num">{moneyShort(x.cost_change_usd)}</span> },
      ]} />
      <p className="mt-3 text-xs text-faint">{d.evaluation_note} {d.routing_policy} Total supplied demand: {int(d.universe.all_units)} units; {int(d.universe.excluded_units)} units are ineligible under confirmation rules and disclosed separately. {d.service_basis}. Unbought units include review, quantity shortfalls and demand not yet due by the final run. A slider setting is a preference, not a guarantee of the lowest cost per unit or the best possible historical plan.</p>
    </>
  );
}
