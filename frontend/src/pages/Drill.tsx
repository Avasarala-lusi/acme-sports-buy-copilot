import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Factory, Play } from "lucide-react";
import { api } from "../api/client";
import { PlanCompare } from "../components/PlanCompare";
import { Button, Card, ErrorBox, Kpi, Loading, PageHeader, SectionTitle, Select, fieldClass } from "../components/ui";
import { int, pct } from "../lib/format";

const short = (f: string) => f.replace("ACME-", "");

export function Drill() {
  const factories = useQuery({ queryKey: ["factories"], queryFn: api.factories, staleTime: Infinity });
  const plans = useQuery({ queryKey: ["network-plans"], queryFn: api.networkPlans, staleTime: Infinity });
  const [factory, setFactory] = useState("ACME-VN01");
  const [start, setStart] = useState("2026-09-01");
  const [end, setEnd] = useState("2026-10-31");
  const run = useMutation({ mutationFn: () => api.drill(factory, start, end, plans.data?.selected_weight ?? 0.5) });
  const r = run.data;
  const lost = (a: number, b: number) => a - b;

  return (
    <>
      <PageHeader eyebrow="Disruption drill" title="What if a factory closes?"
        subtitle="Close one factory for a period and re-plan every buying window. The rule engine moves lots down the backup chain or sends them to the planner; the optimiser re-plans the whole network. Both are compared with their normal plans." />

      <Card className="mb-5 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <Select label="Factory" value={factory} onChange={(e) => setFactory(e.target.value)}>
            {(factories.data ?? []).map((f) => <option key={f.factory_id} value={f.factory_id}>{short(f.factory_id)} · {f.country}</option>)}
          </Select>
          <label className="flex flex-col gap-1 text-xs text-muted">Closed from
            <input type="date" className={fieldClass} value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label className="flex flex-col gap-1 text-xs text-muted">to
            <input type="date" className={fieldClass} value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending || !plans.data}>
            <Play size={14} /> Run drill
          </Button>
          <span className="text-xs text-faint">Takes about a minute: the whole year is re-planned twice.</span>
        </div>
      </Card>

      {run.isPending && <Loading label={`Closing ${short(factory)} and re-planning…`} />}
      {run.error && <ErrorBox error={run.error} />}
      {r && !run.isPending && (
        <>
          <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi icon={Factory} label="Closure" value={`${short(r.factory)} · ${r.weeks_closed} weeks`} sub={`${r.start} to ${r.end}`} />
            <Kpi label="Lots in production there (normal plan)" value={int(r.affected_lots)} sub={`${int(r.affected_units)} units`} />
            <Kpi label="Units lost · rule engine" value={int(lost(r.plans.rules.units_bought, r.plans.rules_disrupted.units_bought))}
              sub={`on time ${pct(r.plans.rules.on_time_pct_of_firm, 1)} → ${pct(r.plans.rules_disrupted.on_time_pct_of_firm, 1)}`} />
            <Kpi label="Units lost · optimiser" value={int(lost(r.plans.optimiser.units_bought, r.plans.optimiser_disrupted.units_bought))}
              sub={`on time ${pct(r.plans.optimiser.on_time_pct_of_firm, 1)} → ${pct(r.plans.optimiser_disrupted.on_time_pct_of_firm, 1)}`} />
          </div>
          <Card className="mb-5 p-5">
            <SectionTitle hint="normal plan vs closure, both approaches">Response</SectionTitle>
            <PlanCompare rows={r.plans} highlight="optimiser_disrupted" columns={[
              { key: "rules", label: "Rules", sub: "normal" }, { key: "rules_disrupted", label: "Rules", sub: "closure" },
              { key: "optimiser", label: "Optimiser", sub: "normal" }, { key: "optimiser_disrupted", label: "Optimiser", sub: "closure" }]} />
          </Card>
          <Card className="p-5">
            <SectionTitle hint="units by factory with the closure">Where the work goes</SectionTitle>
            <div className="grid gap-4 md:grid-cols-2">
              {(["rules_disrupted", "optimiser_disrupted"] as const).map((k) => {
                const base = k === "rules_disrupted" ? r.by_factory.rules : r.by_factory.optimiser;
                return (
                  <div key={k}>
                    <div className="mb-2 text-sm font-medium">{k === "rules_disrupted" ? "Rule engine" : "Optimiser"}</div>
                    {r.by_factory[k].map((f) => {
                      const before = base.find((b) => b.factory_id === f.factory_id)?.units ?? 0;
                      const delta = f.units - before;
                      return (
                        <div key={f.factory_id} className="flex justify-between border-b border-line/60 py-1.5 text-sm last:border-0">
                          <span>{short(f.factory_id)}</span>
                          <span className="font-num">{int(f.units)} <span className={delta >= 0 ? "text-good" : "text-bad"}>({delta >= 0 ? "+" : ""}{int(delta)})</span></span>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </Card>
        </>
      )}
      {!r && !run.isPending && !run.error && (
        <Card className="p-5 text-sm text-muted">Pick a factory and a period, then run the drill. The closure is treated as known from the start of planning.</Card>
      )}
    </>
  );
}
