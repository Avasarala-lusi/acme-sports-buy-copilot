import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../api/client";
import type { Kpis, Lot, Requisition } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { Badge, Card, ErrorBox, Kpi, Loading, PageHeader, Tabs, cx } from "../components/ui";
import { useRun } from "../lib/run";
import { date, int, money, moneyShort, pct } from "../lib/format";
import { LotBadges, LotDrawer } from "./LotDrawer";

type View = "purchases" | "unresolved" | "future" | "waiting";

function delta(cur: number, base: number, fmt: (x: number) => string, manual: boolean) {
  if (!manual || Math.abs(cur - base) < 1e-6) return null;
  return `${cur > base ? "+" : "−"}${fmt(Math.abs(cur - base))} vs auto`;
}

function KpiRow({ k, base, manual }: { k: Kpis; base: Kpis; manual: boolean }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Kpi label="Lots to buy" value={int(k.lots)} delta={delta(k.lots, base.lots, int, manual)} deltaGood={k.lots >= base.lots} />
      <Kpi label="Units" value={int(k.units_bought)} delta={delta(k.units_bought, base.units_bought, int, manual)} deltaGood={k.units_bought >= base.units_bought} />
      <Kpi label="Production cost" value={moneyShort(k.production_cost_usd)}
        delta={delta(k.production_cost_usd, base.production_cost_usd, moneyShort, manual)} deltaGood={k.production_cost_usd <= base.production_cost_usd} />
      <Kpi label="Units on time" value={pct(k.on_time_pct)} hint="Share of units whose expected arrival is on or before the requested delivery date" />
      <Kpi label="Routed to backup" value={pct(k.backup_routed_pct, 0)} hint="Lots sent to the backup factory because the primary was at or above the capacity threshold" />
      <Kpi label="Unresolved units" value={int(k.unresolved_units)} hint="Demand that could not be bought under the rules and could not wait" />
    </div>
  );
}

const lotColumns: Column<Lot>[] = [
  { key: "lot_id", header: "Lot", render: (l) => <span className="font-mono text-xs">{l.lot_id.split("-").pop()}</span> },
  { key: "article_id", header: "Article", render: (l) => <span className="font-medium">{l.article_id}</span> },
  { key: "market_destination", header: "Market" },
  { key: "consolidated_qty", header: "Units", align: "right", render: (l) => int(l.consolidated_qty) },
  { key: "assigned_factory", header: "Factory" },
  { key: "suggested_rdd", header: "Suggested RDD", render: (l) => date(l.suggested_rdd) },
  { key: "on_time", header: "Arrival", render: (l) => (l.on_time ? <Badge tone="good">On time</Badge> : <Badge tone="bad">Late</Badge>) },
  { key: "total_cost_usd", header: "Cost", align: "right", render: (l) => money(l.total_cost_usd) },
  { key: "decision", header: "Decision", render: (l) => (l.decision === "Buy" ? <span className="text-muted">Buy</span> : <Badge tone="bad">{l.decision}</Badge>) },
  { key: "flags", header: "Flags", value: (l) => (l.warnings ? 1 : 0), render: (l) => <div className="flex gap-1"><LotBadges lot={{ ...l, decision: "Buy" }} /></div> },
];

const reqColumns = (withRelease: boolean): Column<Requisition>[] => [
  { key: "pr_id", header: "Requisition", render: (r) => <span className="font-mono text-xs">{r.pr_id}</span> },
  { key: "article_id", header: "Article" },
  { key: "market_destination", header: "Market" },
  { key: "requested_qty", header: "Units", align: "right", render: (r) => int(r.requested_qty) },
  { key: "rdd_original", header: "RDD", render: (r) => date(r.rdd_original) },
  ...(withRelease ? [{ key: "release_primary", header: "Release date", render: (r: Requisition) => date(r.release_primary) }] : []),
  { key: "reason", header: "Reason", render: (r) => <span className="inline-block min-w-[360px] whitespace-normal text-muted">{r.reason}</span> },
];

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={cx("rounded-full border px-3 py-1 text-xs font-medium transition",
        active ? "border-accent bg-accent-soft text-accent" : "border-line bg-panel text-muted hover:text-ink")}>
      {children}
    </button>
  );
}

export function BuyPlan() {
  const { runId, run } = useRun();
  const [view, setView] = useState<View>("purchases");
  const [selected, setSelected] = useState<Lot | null>(null);
  const [q, setQ] = useState("");
  const [market, setMarket] = useState("");
  const [factory, setFactory] = useState("");
  const [onlyWarnings, setOnlyWarnings] = useState(false);
  const [onlyManual, setOnlyManual] = useState(false);

  const plan = useQuery({ queryKey: ["plan", runId], queryFn: () => api.plan(runId) });
  const reqs = useQuery({
    queryKey: ["reqs", runId, view],
    queryFn: () => api.requisitions(runId, view as "unresolved" | "future" | "waiting"),
    enabled: view !== "purchases",
  });

  const lots = useMemo(() => {
    const all = plan.data?.lots ?? [];
    const needle = q.trim().toLowerCase();
    return all.filter((l) =>
      (!market || l.market_destination === market) &&
      (!factory || l.assigned_factory === factory) &&
      (!onlyWarnings || l.warnings) &&
      (!onlyManual || l.decision_type === "manual") &&
      (!needle || l.article_id.toLowerCase().includes(needle) || l.lot_id.toLowerCase().includes(needle)));
  }, [plan.data, q, market, factory, onlyWarnings, onlyManual]);

  if (plan.isLoading) return <Loading label="Loading the buy plan…" />;
  if (plan.error) return <ErrorBox error={plan.error} />;
  const p = plan.data!;
  const markets = [...new Set(p.lots.map((l) => l.market_destination))].sort();
  const factories = [...new Set(p.lots.map((l) => l.assigned_factory))].sort();

  return (
    <>
      <PageHeader title="Buy plan"
        subtitle={<>{runId} · {run?.season} · range {run?.range_version} · decisions are automatic unless marked <Badge tone="manual">Manual</Badge></>} />
      <KpiRow k={p.kpis} base={p.kpis_automatic} manual={p.manual_changes > 0} />

      <Tabs value={view} onChange={setView} tabs={[
        { value: "purchases", label: "Purchases", count: p.lots.length },
        { value: "unresolved", label: "Unresolved demand", count: p.counts.unresolved },
        { value: "future", label: "Moved to Future", count: p.counts.future },
        { value: "waiting", label: "Waiting, not yet due", count: p.counts.waiting },
      ]} />

      {view === "purchases" ? (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search article or lot"
                className="w-56 rounded-lg border border-line bg-panel py-1.5 pl-8 pr-3 text-sm outline-none focus:border-accent" />
            </div>
            <select value={market} onChange={(e) => setMarket(e.target.value)}
              className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm">
              <option value="">All markets</option>
              {markets.map((m) => <option key={m}>{m}</option>)}
            </select>
            <select value={factory} onChange={(e) => setFactory(e.target.value)}
              className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm">
              <option value="">All factories</option>
              {factories.map((f) => <option key={f}>{f}</option>)}
            </select>
            <Chip active={onlyWarnings} onClick={() => setOnlyWarnings((v) => !v)}>Only warnings</Chip>
            <Chip active={onlyManual} onClick={() => setOnlyManual((v) => !v)}>Only manual changes</Chip>
            <span className="ml-auto text-xs text-faint">Click a lot to see why and to decide</span>
          </div>
          <DataTable rows={lots} columns={lotColumns} rowKey={(l) => l.lot_id} onRowClick={setSelected}
            selectedKey={selected?.lot_id} emptyText="No lots match these filters" />
        </>
      ) : (
        <>
          <Card className="mb-3 p-3 text-sm text-muted">
            {view === "unresolved" && "Demand that could not be bought under the rules and could not wait. Shown separately; never treated as a purchase."}
            {view === "future" && "Wholesale demand without a confirmed sales order, moved to Future under the forecast exclusion rule."}
            {view === "waiting" && "Open demand that is not yet due. It is carried to later runs and keeps its requisition ID, so it is never bought twice."}
          </Card>
          {reqs.isLoading ? <Loading /> : reqs.error ? <ErrorBox error={reqs.error} /> : (
            <DataTable rows={reqs.data ?? []} columns={reqColumns(view === "waiting")} rowKey={(r) => r.pr_id} />
          )}
        </>
      )}

      <LotDrawer lot={selected} runId={runId} onClose={() => setSelected(null)} />
    </>
  );
}
