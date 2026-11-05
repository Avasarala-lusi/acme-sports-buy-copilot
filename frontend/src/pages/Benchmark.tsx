import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Approach, PlanKpis } from "../api/types";
import { PlanCompare } from "../components/PlanCompare";
import { Badge, Card, ErrorBox, Loading, PageHeader, SectionTitle, Segmented } from "../components/ui";
import { int, moneyShort, pct } from "../lib/format";

export function Benchmark() {
  const q = useQuery({ queryKey: ["network-plans"], queryFn: api.networkPlans, staleTime: Infinity });
  const [scope, setScope] = useState<string>("test");
  if (q.isLoading) return <Loading label="Building the chronological comparison. A fresh calculation can take 15–25 minutes; later visits use cached results…" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const seasonsIn = scope === "test" ? d.test_seasons : scope === "tuning" ? d.tuning_seasons : scope === "all" ? d.seasons : [scope];
  const pick = (a: Approach): PlanKpis => a.results[scope];
  const shown = d.approaches.filter((a) => a.kind !== "optimiser" || [0, d.selected_weight, 1].includes(a.weight!));
  const label = (a: Approach) => (a.kind !== "optimiser" ? a.label
    : a.weight === d.selected_weight ? "Optimiser (recommended)" : a.weight === 0 ? "Optimizer, cost-focused" : "Optimizer, service-focused");
  const rows = Object.fromEntries(shown.map((a) => [a.key, pick(a)]));
  const sel = d.approaches.find((a) => a.weight === (d.selected_weight ?? d.weights[0]))!;
  const rules = d.approaches.find((a) => a.key === "rules")!;
  const test = { opt: sel.results.test, rules: rules.results.test };

  return (
    <>
      <PageHeader eyebrow="Planner benchmark · chronological replay" title="Which planning approach works best?"
        subtitle={`Historical comparison, independent of the week selector. Compare ${int(d.universe.units)} eligible units, including unresolved demand. Each buying window sees received requests only. Slider selection uses earlier-period results captured before entering ${d.test_seasons.join(" and ")}. Later-season outcomes do not choose the setting.`}
        actions={<Segmented value={scope} onChange={setScope} options={[
          { value: "test", label: `Later period (${d.test_seasons.join("+")})` }, { value: "tuning", label: "Earlier cohort" },
          ...d.seasons.map((s) => ({ value: s, label: s })), { value: "all", label: "All" }]} />} />

      {!d.complete && <Card className="mb-5 p-5">Validation is incomplete. Results require review.</Card>}
      <details className="mb-4 text-xs text-muted"><summary className="cursor-pointer">Scope, timing and assumptions</summary><p className="mt-2">{d.evaluation_note} Cohort tables show outcomes through the end of the replay; setting selection uses metrics frozen at the earlier-period cutoff. {d.baseline_note} Supplied demand: {int(d.universe.all_units)} units; confirmation-ineligible demand: {int(d.universe.excluded_units)} units. {d.service_basis}. Unbought units include review, quantity shortfalls and demand not yet due at the final run.</p></details>
      <Card className="mb-5 p-5">
        <div className="text-sm">
          On the later evaluation period the recommended optimiser puts <span className="font-num font-medium">{pct(test.opt.on_time_pct_of_firm, 1)}</span> of
          the demand on time against <span className="font-num">{pct(test.rules.on_time_pct_of_firm, 1)}</span> for the rule engine, buys{" "}
          <span className="font-num">{int(test.opt.units_bought - test.rules.units_bought)}</span> more units, at{" "}
          <span className="font-num">${test.opt.cost_per_unit_usd.toFixed(2)}</span> per unit against{" "}
          <span className="font-num">${test.rules.cost_per_unit_usd.toFixed(2)}</span>. Review capacity checks alongside service and cost.
        </div>
      </Card>

      <Card className="mb-5 p-5">
        <SectionTitle hint={seasonsIn.join(", ")}>Results</SectionTitle>
        <PlanCompare highlight={sel.key} rows={rows}
          columns={shown.map((a) => ({ key: a.key, label: label(a), sub: a.kind === "baseline" ? "capacity ignored" : a.weight != null ? `weight ${a.weight}` : undefined }))} />
      </Card>

      <Card className="p-5">
        <SectionTitle hint="tuning seasons only">How the recommended setting was chosen</SectionTitle>
        <p className="mb-3 text-sm text-muted">Rule: {d.selection_rule}.</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {d.selection_steps.map((s) => (
            <div key={s.to} className="rounded-xl border border-line p-3">
              <div className="flex items-center justify-between text-xs text-muted">Weight {s.from} → {s.to}
                <Badge tone={s.accepted ? "good" : "neutral"}>{s.accepted ? "accepted" : "not selected"}</Badge></div>
              <div className="font-num mt-1 text-lg">{s.cost_per_extra_on_time_unit_usd != null ? `$${s.cost_per_extra_on_time_unit_usd.toFixed(0)}` : "—"}</div>
              <div className="text-[11px] text-faint">per extra on-time unit ({int(s.extra_on_time_units)} units, {moneyShort(s.extra_cost_usd)}) vs ${s.average_unit_cost_usd.toFixed(0)} to make one</div>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
