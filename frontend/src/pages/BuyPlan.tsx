import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon, ArrowRight, CalendarCheck2, CalendarClock, Clock, DollarSign, Factory, Hourglass, Package, Search, ShieldAlert,
} from "lucide-react";
import { api } from "../api/client";
import type { Lot, Plan, Requisition, TrendPoint } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { Badge, Button, Card, ErrorBox, GlowKpi, Loading, PageHeader, Tabs, cx, fieldClass } from "../components/ui";
import { useRun } from "../lib/run";
import { date, int, load, money, moneyShort, pct } from "../lib/format";
import { LotBadges, LotDrawer } from "./LotDrawer";

type View = "purchases" | "review" | "unresolved" | "future" | "waiting";

function delta(cur: number, base: number, fmt: (x: number) => string, manual: boolean) {
  if (!manual || Math.abs(cur - base) < 1e-6) return null;
  return `${cur > base ? "+" : "−"}${fmt(Math.abs(cur - base))} vs auto`;
}

const win = (w: string) => w.replace("WIN-", "");

function KpiGrid({ p, trend }: { p: Plan; trend: TrendPoint[] }) {
  const k = p.kpis, base = p.kpis_automatic, manual = p.manual_changes > 0, draft = !p.is_buying_run;
  const pts = (f: (t: TrendPoint) => number) => trend.map((t) => ({ x: t.buying_window, y: f(t) }));
  const common = { highlight: p.buying_window, xLabel: win };
  return (
    <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <GlowKpi tone="green" icon={Package} label={draft ? "Lots in draft" : "Lots to buy"} value={int(k.lots)}
        sub={<span>{int(k.review_lots)} need review</span>}
        delta={delta(k.lots, base.lots, int, manual)} deltaGood={k.lots >= base.lots}
        points={pts((t) => t.lots)} format={int} {...common} />
      <GlowKpi tone="amber" icon={Factory} label="Units" value={int(k.units_bought)}
        sub={<span>{pct(k.backup_routed_pct, 0)} of lots on a backup</span>}
        delta={delta(k.units_bought, base.units_bought, int, manual)} deltaGood={k.units_bought >= base.units_bought}
        points={pts((t) => t.units_bought)} format={int} {...common} />
      <GlowKpi tone="violet" icon={DollarSign} label="Production cost" value={moneyShort(k.production_cost_usd)}
        sub={<span>{money(k.cost_per_unit_usd)} per unit</span>}
        delta={delta(k.production_cost_usd, base.production_cost_usd, moneyShort, manual)} deltaGood={k.production_cost_usd <= base.production_cost_usd}
        points={pts((t) => t.production_cost_usd)} format={moneyShort} {...common} />
      <GlowKpi tone="blue" icon={Clock} label="Units on time" value={pct(k.on_time_pct)}
        sub={<span>{int(k.units_on_time)} units by their RDD</span>}
        hint="Share of units whose expected arrival is on or before the requested delivery date"
        points={pts((t) => t.on_time_pct)} format={(v) => pct(v)} {...common} />
    </div>
  );
}

const flowParts = [
  { key: "bought", label: "Bought", color: "var(--color-status-good)", icon: CalendarCheck2 },
  { key: "review", label: "Needs review", color: "var(--color-status-warning)", icon: ShieldAlert },
  { key: "unresolved", label: "Unresolved", color: "var(--color-status-critical)", icon: AlertOctagon },
  { key: "waiting", label: "Waiting", color: "var(--color-series-1)", icon: Hourglass },
  { key: "future", label: "Moved to Future", color: "var(--color-axis)", icon: CalendarClock },
] as const;

function DemandFlow({ p }: { p: Plan }) {
  const total = flowParts.reduce((a, f) => a + p.units[f.key], 0) || 1;
  return (
    <Card className="mb-5 p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[15px] font-semibold tracking-tight">Where the open demand goes <span className="font-normal text-muted">{p.is_buying_run ? "this window" : "in this draft"}</span></div>
        <div className="font-mono text-[11px] text-faint">{int(total)} units in play</div>
      </div>
      <div className="flex h-2.5 gap-[2px] overflow-hidden rounded-full">
        {flowParts.map((f) => {
          const v = p.units[f.key];
          return v > 0 ? (
            <div key={f.key} title={`${f.label}: ${int(v)} units (${pct((v / total) * 100)})`}
              className="h-full transition-[flex-grow] duration-500 first:rounded-l-full last:rounded-r-full hover:brightness-110"
              style={{ flexGrow: v, background: f.color, boxShadow: `0 0 12px ${f.color}` }} />
          ) : null;
        })}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 lg:grid-cols-5">
        {flowParts.map(({ key, label, color, icon: Icon }) => (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `color-mix(in oklab, ${color} 16%, transparent)`, color }}>
              <Icon size={13} />
            </span>
            <div className="leading-tight">
              <div className="text-muted">{label}</div>
              <div className="font-num text-[13px] text-ink">{int(p.units[key])} <span className="text-faint">· {pct((p.units[key] / total) * 100, 0)}</span></div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

const lotColumns: Column<Lot>[] = [
  { key: "lot_id", header: "Lot", render: (l) => <span className="font-mono text-xs text-muted">{l.lot_id.split("-").pop()}</span> },
  { key: "article_id", header: "Article", render: (l) => <span className="font-medium">{l.article_id}</span> },
  { key: "market_destination", header: "Market", render: (l) => <Badge>{l.market_destination}</Badge> },
  { key: "consolidated_qty", header: "Units", align: "right", render: (l) => <span className="font-num">{int(l.consolidated_qty)}</span> },
  { key: "assigned_factory", header: "Factory", render: (l) => <span className="font-mono text-xs text-muted">{l.assigned_factory.replace("ACME-", "")}</span> },
  { key: "util_after_pct", header: "Factory load", align: "right", title: "Busiest production week at the assigned factory, including this lot",
    render: (l) => (
      <span className="inline-flex items-center justify-end gap-2">
        <span className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-sidebar sm:block">
          <span className="block h-full rounded-full" style={{
            width: `${Math.min(l.util_after_pct, 120) / 1.2}%`,
            background: l.util_after_pct > 100 ? "var(--color-status-critical)" : l.util_after_pct >= 85 ? "var(--color-status-warning)" : "var(--color-status-good)",
          }} />
        </span>
        <span className={cx("font-num w-12", l.util_after_pct > 100 ? "font-semibold text-bad" : l.util_after_pct >= 85 ? "text-warn" : "")}>{load(l.util_after_pct)}</span>
      </span>
    ) },
  { key: "suggested_rdd", header: "Suggested RDD", render: (l) => date(l.suggested_rdd) },
  { key: "on_time", header: "Arrival", render: (l) => (l.on_time ? <Badge tone="good" dot>On time</Badge> : <Badge tone="bad" dot>Late</Badge>) },
  { key: "total_cost_usd", header: "Cost", align: "right", render: (l) => <span className="font-num">{money(l.total_cost_usd)}</span> },
  { key: "decision", header: "Decision", render: (l) => (l.decision === "Buy" ? <span className="text-muted">Buy</span>
      : l.decision === "Review" ? <Badge tone="warn" dot>Review</Badge> : <Badge tone="bad" dot>{l.decision}</Badge>) },
  { key: "flags", header: "Flags", value: (l) => (l.warnings ? 1 : 0), render: (l) => <div className="flex gap-1"><LotBadges lot={{ ...l, decision: "Buy" }} /></div> },
];

const reqColumns = (withRelease: boolean): Column<Requisition>[] => [
  { key: "pr_id", header: "Requisition", render: (r) => <span className="font-mono text-xs">{r.pr_id}</span> },
  { key: "article_id", header: "Article" },
  { key: "market_destination", header: "Market", render: (r) => <Badge>{r.market_destination}</Badge> },
  { key: "requested_qty", header: "Units", align: "right", render: (r) => int(r.requested_qty) },
  { key: "rdd_original", header: "RDD", render: (r) => date(r.rdd_original) },
  ...(withRelease ? [{ key: "release_primary", header: "Release date", render: (r: Requisition) => date(r.release_primary) }] : []),
  { key: "reason", header: "Reason", render: (r) => <span className="inline-block min-w-[360px] whitespace-normal text-muted">{r.reason}</span> },
];

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={cx("rounded-full border px-3 py-1.5 text-xs font-medium transition",
        active ? "border-accent/40 bg-accent-soft text-accent" : "border-line bg-panel text-muted hover:text-ink")}>
      {children}
    </button>
  );
}

const field = fieldClass;

export function BuyPlan() {
  const { runId, run, setRunId, openLot, setOpenLot } = useRun();
  const [view, setView] = useState<View>("purchases");
  const [selected, setSelected] = useState<Lot | null>(null);
  const [q, setQ] = useState("");
  const [market, setMarket] = useState("");
  const [factory, setFactory] = useState("");
  const [onlyWarnings, setOnlyWarnings] = useState(false);
  const [onlyManual, setOnlyManual] = useState(false);

  const plan = useQuery({ queryKey: ["plan", runId], queryFn: () => api.plan(runId) });
  const trend = useQuery({ queryKey: ["trend"], queryFn: api.trend, staleTime: Infinity });
  const reqs = useQuery({
    queryKey: ["reqs", runId, view],
    queryFn: () => api.requisitions(runId, view as "unresolved" | "future" | "waiting"),
    enabled: view !== "purchases" && view !== "review",
  });

  // a lot chosen in the command palette
  useEffect(() => {
    if (!openLot || !plan.data) return;
    const lot = plan.data.lots.find((l) => l.lot_id === openLot);
    if (lot) { setView(lot.decision === "Review" ? "review" : "purchases"); setSelected(lot); }
    setOpenLot(null);
  }, [openLot, plan.data, setOpenLot]);

  const lots = useMemo(() => {
    const all = plan.data?.lots ?? [];
    const needle = q.trim().toLowerCase();
    return all.filter((l) =>
      (view === "review" ? l.decision === "Review" : l.decision !== "Review") &&
      (!market || l.market_destination === market) &&
      (!factory || l.assigned_factory === factory) &&
      (!onlyWarnings || l.warnings) &&
      (!onlyManual || l.decision_type === "manual") &&
      (!needle || l.article_id.toLowerCase().includes(needle) || l.lot_id.toLowerCase().includes(needle)
        || l.pr_ids.toLowerCase().includes(needle)));
  }, [plan.data, view, q, market, factory, onlyWarnings, onlyManual]);

  if (plan.isLoading) return <Loading label="Loading the buy plan…" />;
  if (plan.error) return <ErrorBox error={plan.error} />;
  const p = plan.data!;
  const markets = [...new Set(p.lots.map((l) => l.market_destination))].sort();
  const factories = [...new Set(p.lots.map((l) => l.assigned_factory))].sort();
  const draft = !p.is_buying_run;
  const reviewCount = p.lots.filter((l) => l.decision === "Review").length;

  return (
    <>
      <PageHeader eyebrow={`${runId} · ${run?.season ?? ""} · range ${run?.range_version ?? ""}`}
        title={<span className="flex flex-wrap items-center gap-3">Buy plan <span className="text-gradient font-num">{win(p.buying_window)}</span>{draft
          && <span className="rounded-md border border-info/25 bg-info-soft px-2 py-0.5 font-mono text-xs font-medium text-info">DRAFT</span>}</span>}
        subtitle={<>Buying window {p.buying_window} on {date(p.buy_date)}. Every decision is automatic unless marked <Badge tone="manual">Manual</Badge>.</>} />

      {draft ? (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-2xl border border-info/25 bg-info-soft px-4 py-3 text-sm text-info">
          <CalendarClock size={18} className="shrink-0" />
          <div className="min-w-[260px] flex-1">
            <span className="font-semibold">Draft.</span> This week is between buying windows: it shows what the {p.buying_window} window
            would buy with the demand known today. Nothing is ordered and no capacity is reserved.
          </div>
          {p.buying_run_id && (
            <Button onClick={() => setRunId(p.buying_run_id!)}>Open buying run {p.buying_run_id} <ArrowRight size={14} /></Button>
          )}
        </div>
      ) : (
        <div className="mb-5 flex items-center gap-3 rounded-2xl border border-good/25 bg-good-soft px-4 py-3 text-sm text-good">
          <CalendarCheck2 size={18} className="shrink-0" />
          <span><span className="font-semibold">Buying run.</span> Purchases for {p.buying_window} are committed this week. Next window: {date(p.next_buy_date)}.</span>
        </div>
      )}

      <KpiGrid p={p} trend={trend.data ?? []} />
      {p.decision_issues?.map((issue) => <p key={issue} className="mb-3 rounded border border-warn/30 bg-warn-soft p-3 text-sm text-warn">{issue}</p>)}
      <DemandFlow p={p} />

      <Tabs value={view} onChange={setView} tabs={[
        { value: "purchases", label: draft ? "Draft purchases" : "Purchases", count: p.lots.length - reviewCount, icon: CalendarCheck2 },
        { value: "review", label: "Needs planner review", count: reviewCount, icon: ShieldAlert },
        { value: "unresolved", label: "Unresolved", count: p.counts.unresolved, icon: AlertOctagon },
        { value: "future", label: "Moved to Future", count: p.counts.future, icon: CalendarClock },
        { value: "waiting", label: "Waiting", count: p.counts.waiting, icon: Hourglass },
      ]} />

      {view === "purchases" || view === "review" ? (
        <>
          {view === "review" && (
            <div className="mb-3 flex items-start gap-2 rounded-2xl border border-warn/25 bg-warn-soft p-3 text-sm text-warn">
              <ShieldAlert size={16} className="mt-0.5 shrink-0" />
              These requests are still awaiting a decision, including outstanding requests from earlier windows.
              Review the warning, try another certified factory, delay, or cancel. They reserve no capacity until
              purchased. Choosing Buy rechecks eligibility, quantities and the hard capacity ceiling.
            </div>
          )}
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search PR, article or lot" className={cx(field, "w-60 pl-8")} />
            </div>
            <select value={market} onChange={(e) => setMarket(e.target.value)} className={field}>
              <option value="">All markets</option>
              {markets.map((m) => <option key={m}>{m}</option>)}
            </select>
            <select value={factory} onChange={(e) => setFactory(e.target.value)} className={field}>
              <option value="">All factories</option>
              {factories.map((f) => <option key={f}>{f}</option>)}
            </select>
            <Chip active={onlyWarnings} onClick={() => setOnlyWarnings((v) => !v)}>Only warnings</Chip>
            <Chip active={onlyManual} onClick={() => setOnlyManual((v) => !v)}>Only manual changes</Chip>
            <span className="ml-auto text-xs text-faint">Click a lot to see why · ⌘K to jump to one</span>
          </div>
          <DataTable rows={lots} columns={lotColumns} rowKey={(l) => l.lot_id} onRowClick={setSelected}
            selectedKey={selected?.lot_id} emptyText="No lots match these filters" />
        </>
      ) : (
        <>
          <div className="mb-3 rounded-2xl border border-line bg-panel p-3 text-sm text-muted">
            {view === "unresolved" && "Demand below a minimum quantity that could not wait for the next buying window. Shown separately; never treated as a purchase."}
            {view === "future" && "Wholesale demand without a confirmed sales order, moved to Future under the forecast exclusion rule."}
            {view === "waiting" && "Open demand that is not yet due in this window. It is carried to later runs and keeps its requisition ID, so it is never bought twice."}
          </div>
          {reqs.isLoading ? <Loading /> : reqs.error ? <ErrorBox error={reqs.error} /> : (
            <DataTable rows={reqs.data ?? []} columns={reqColumns(view === "waiting")} rowKey={(r) => r.pr_id} />
          )}
        </>
      )}

      <LotDrawer lot={selected} runId={runId} draft={draft} onClose={() => setSelected(null)} />
    </>
  );
}

