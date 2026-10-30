import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Approach, PlanKpis } from "../api/types";
import { PlanCompare, pool } from "../components/PlanCompare";
import { Badge, Card, ErrorBox, Loading, PageHeader, SectionTitle, Segmented } from "../components/ui";
import { int, moneyShort, pct } from "../lib/format";

export function Benchmark() {
  const q = useQuery({ queryKey: ["network-plans"], queryFn: api.networkPlans, staleTime: Infinity });
  const [scope, setScope] = useState<string>("test");
  if (q.isLoading) return <Loading label="Running every planning approach on every season (a few minutes the first time)…" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const seasonsIn = scope === "test" ? d.test_seasons : scope === "tuning" ? d.tuning_seasons : scope === "all" ? d.seasons : [scope];
  const pick = (a: Approach): PlanKpis => (scope === "all" ? a.results.all : pool(seasonsIn.map((s) => a.results[s])));
  const shown = d.approaches.filter((a) => a.kind !== "optimiser" || [0, d.selected_weight, 1].includes(a.weight!));
  const label = (a: Approach) => (a.kind !== "optimiser" ? a.label
    : a.weight === d.selected_weight ? "Optimiser (recommended)" : a.weight === 0 ? "Optimiser, cheapest" : "Optimiser, safest");
  const rows = Object.fromEntries(shown.map((a) => [a.key, pick(a)]));
  const sel = d.approaches.find((a) => a.weight === d.selected_weight)!;
  const rules = d.approaches.find((a) => a.key === "rules")!;
  const test = { opt: pool(d.test_seasons.map((s) => sel.results[s])), rules: pool(d.test_seasons.map((s) => rules.results[s])) };

  return (
    <>
      <PageHeader eyebrow="Planner benchmark · same firm demand, season by season" title="Which planning approach works best?"
        subtitle={`Today's assignments, the rule engine and the optimiser, compared on the same ${int(d.universe.units)} units of firm demand (every lot the rule engine bought or sent to review). The optimiser's recommended setting was chosen on ${d.tuning_seasons.join(" and ")} only; ${d.test_seasons.join(" and ")} played no part in the choice, so they show how it does on seasons it has not seen.`}
        actions={<Segmented value={scope} onChange={setScope} options={[
          { value: "test", label: `Unseen (${d.test_seasons.join("+")})` }, { value: "tuning", label: "Tuning" },
          ...d.seasons.map((s) => ({ value: s, label: s })), { value: "all", label: "All" }]} />} />

      <Card className="mb-5 p-5">
        <div className="text-sm">
          On the unseen seasons the recommended optimiser puts <span className="font-num font-medium">{pct(test.opt.on_time_pct_of_firm, 1)}</span> of
          the demand on time against <span className="font-num">{pct(test.rules.on_time_pct_of_firm, 1)}</span> for the rule engine, buys{" "}
          <span className="font-num">{int(test.opt.units_bought - test.rules.units_bought)}</span> more units, at{" "}
          <span className="font-num">${test.opt.cost_per_unit_usd.toFixed(2)}</span> per unit against{" "}
          <span className="font-num">${test.rules.cost_per_unit_usd.toFixed(2)}</span>. Neither ever loads a factory above 100%.
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
                <Badge tone={s.accepted ? "good" : "neutral"}>{s.accepted ? "worth it" : "stop"}</Badge></div>
              <div className="font-num mt-1 text-lg">{Number.isFinite(s.cost_per_extra_on_time_unit_usd) ? `$${s.cost_per_extra_on_time_unit_usd.toFixed(0)}` : "—"}</div>
              <div className="text-[11px] text-faint">per extra on-time unit ({int(s.extra_on_time_units)} units, {moneyShort(s.extra_cost_usd)}) vs ${s.average_unit_cost_usd.toFixed(0)} to make one</div>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
