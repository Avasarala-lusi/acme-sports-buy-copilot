import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CheckCircle2 } from "lucide-react";
import { api } from "../api/client";
import type { Lot } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, Segmented, Select, Stat, cx } from "../components/ui";
import { useRun } from "../lib/run";
import { date, int, money } from "../lib/format";

type Mode = "hold" | "delay" | "swap";

export function WhatIf() {
  const { runId } = useRun();
  const [mode, setMode] = useState<Mode>("hold");
  const plan = useQuery({ queryKey: ["plan", runId], queryFn: () => api.plan(runId) });

  return (
    <>
      <PageHeader title="Test a change"
        subtitle="Scenarios run on a copy of this week's automatic plan. Nothing changes until you apply it; applied changes are saved as manual decisions." />
      <div className="mb-5">
        <Segmented value={mode} onChange={setMode} options={[
          { value: "hold", label: "Hold a customer" },
          { value: "delay", label: "Delay production" },
          { value: "swap", label: "Switch factories" },
        ]} />
      </div>
      {plan.isLoading ? <Loading /> : plan.error ? <ErrorBox error={plan.error} /> : (
        <>
          {mode === "hold" && <HoldScenario runId={runId} />}
          {mode === "delay" && <DelayScenario runId={runId} lots={plan.data!.lots} />}
          {mode === "swap" && <SwapScenario runId={runId} lots={plan.data!.lots} />}
        </>
      )}
    </>
  );
}

function Layout2({ controls, children }: { controls: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
      <Card className="h-fit space-y-4 p-4">{controls}</Card>
      <div className="min-w-0 space-y-4">{children}</div>
    </div>
  );
}

function HoldScenario({ runId }: { runId: string }) {
  const qc = useQueryClient();
  const customers = useQuery({ queryKey: ["customers", runId], queryFn: () => api.customers(runId) });
  const overrides = useQuery({ queryKey: ["overrides", runId], queryFn: () => api.overrides(runId) });
  const [customer, setCustomer] = useState("");
  useEffect(() => {
    if (customers.data?.length && !customers.data.some((c) => c.customer_id === customer)) setCustomer(customers.data[0].customer_id);
  }, [customers.data, customer]);

  const result = useQuery({
    queryKey: ["hold", runId, customer],
    queryFn: () => api.holdScenario(runId, customer),
    enabled: !!customer,
  });
  const held = overrides.data?.held_customers.includes(customer) ?? false;
  const apply = useMutation({
    mutationFn: () => (held ? api.releaseHold(runId, customer) : api.hold(runId, customer)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan", runId] });
      qc.invalidateQueries({ queryKey: ["overrides", runId] });
    },
  });

  const r = result.data;
  return (
    <Layout2 controls={
      <>
        <Select label="Customer" value={customer} onChange={(e) => setCustomer(e.target.value)}>
          {(customers.data ?? []).map((c) => (
            <option key={c.customer_id} value={c.customer_id}>
              {c.customer_id}{c.credit_rating ? ` · rating ${c.credit_rating}` : ""} · {c.n_prs} requisitions
            </option>
          ))}
        </Select>
        <p className="text-xs text-muted">Removes this customer's units from every lot this week and shows the sales value at risk.</p>
        <Button variant={held ? "danger" : "primary"} className="w-full" disabled={!customer || apply.isPending} onClick={() => apply.mutate()}>
          {held ? "Release hold" : "Apply hold to plan"}
        </Button>
        {held && <Badge tone="manual">Hold applied to the plan</Badge>}
      </>
    }>
      {result.isLoading ? <Loading /> : result.error ? <ErrorBox error={result.error} /> : r && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Lots affected" value={r.lots_affected} />
            <Stat label="Sales value at risk" value={money(r.nsv_at_risk_usd)} tone={r.nsv_at_risk_usd ? "bad" : undefined} />
            <Stat label="Lots below MOQ after hold" value={r.moq_alerts.length} tone={r.moq_alerts.length ? "warn" : "good"} />
          </div>
          {r.moq_alerts.length > 0 && (
            <div className="flex items-start gap-2 rounded-lg bg-warn-soft p-3 text-sm text-warn">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              Some lots fall below the minimum order quantity after the hold. A suggested fix is shown for each.
            </div>
          )}
          <DataTable rows={r.lots} rowKey={(l) => l.lot_id} maxHeight="50vh" emptyText="This customer has no units in this week's lots" columns={[
            { key: "lot_id", header: "Lot", render: (l) => <span className="font-mono text-xs">{l.lot_id}</span> },
            { key: "article_id", header: "Article" },
            { key: "market_destination", header: "Market" },
            { key: "qty_before", header: "Before", align: "right", render: (l) => int(l.qty_before) },
            { key: "qty_after", header: "After", align: "right", render: (l) => <span className="font-semibold">{int(l.qty_after)}</span> },
            { key: "nsv_at_risk_usd", header: "Sales value at risk", align: "right", render: (l) => money(l.nsv_at_risk_usd) },
            { key: "moq_ok", header: "Minimum", render: (l) => (l.moq_ok ? <Badge tone="good">OK</Badge> : <Badge tone="warn">Below MOQ</Badge>) },
            { key: "fix", header: "Suggested fix", render: (l) => <span className="inline-block min-w-[300px] whitespace-normal text-muted">{l.fix ?? "—"}</span> },
          ]} />
        </>
      )}
    </Layout2>
  );
}

function DelayScenario({ runId, lots }: { runId: string; lots: Lot[] }) {
  const factories = useMemo(() => [...new Set(lots.map((l) => l.assigned_factory))].sort(), [lots]);
  const [factory, setFactory] = useState(factories[0] ?? "");
  const [days, setDays] = useState(14);
  useEffect(() => {
    if (!factories.includes(factory)) setFactory(factories[0] ?? "");
  }, [factories, factory]);
  const result = useQuery({
    queryKey: ["delay", runId, factory, days],
    queryFn: () => api.delayScenario(runId, factory, days),
    enabled: !!factory,
  });
  const r = result.data;
  return (
    <Layout2 controls={
      <>
        <Select label="Factory" value={factory} onChange={(e) => setFactory(e.target.value)}>
          {factories.map((f) => <option key={f}>{f}</option>)}
        </Select>
        <label className="block text-xs font-medium text-muted">
          Delay: <span className="text-ink">{days} days</span>
          <input type="range" min={1} max={60} value={days} onChange={(e) => setDays(Number(e.target.value))}
            className="mt-2 w-full accent-[#b04812]" />
        </label>
        <p className="text-xs text-muted">A delay is a risk check, not a decision. Use "Switch factories" or a Go/No-Go decision to act on it.</p>
      </>
    }>
      {result.isLoading ? <Loading /> : result.error ? <ErrorBox error={result.error} /> : r && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Lots arriving late" value={`${r.lots_late} of ${r.lots.length}`} tone={r.lots_late ? "bad" : "good"} />
            <Stat label="Sales value at risk" value={money(r.nsv_at_risk_usd)} tone={r.nsv_at_risk_usd ? "bad" : undefined} />
          </div>
          <DataTable rows={r.lots} rowKey={(l) => l.lot_id} maxHeight="40vh" columns={[
            { key: "lot_id", header: "Lot", render: (l) => <span className="font-mono text-xs">{l.lot_id}</span> },
            { key: "article_id", header: "Article" },
            { key: "market_destination", header: "Market" },
            { key: "rdd", header: "RDD", render: (l) => date(l.rdd) },
            { key: "arrival_before", header: "Arrival before", render: (l) => date(l.arrival_before) },
            { key: "arrival_after", header: "Arrival after", render: (l) => date(l.arrival_after) },
            { key: "late_after", header: "Status", render: (l) => (l.late_after ? <Badge tone="bad">Late</Badge> : <Badge tone="good">On time</Badge>) },
            { key: "nsv_at_risk_usd", header: "At risk", align: "right", render: (l) => money(l.nsv_at_risk_usd) },
          ]} />
          <Card className="p-4">
            <div className="mb-2 text-sm font-semibold">Affected customers</div>
            <div className="flex flex-wrap gap-2">
              {r.customers.length === 0 && <span className="text-sm text-muted">None</span>}
              {r.customers.slice(0, 12).map((c) => (
                <Badge key={c.customer_id ?? "forecast"} tone="neutral">{c.customer_id ?? "Forecast"} · {money(c.nsv_at_risk_usd)}</Badge>
              ))}
            </div>
          </Card>
        </>
      )}
    </Layout2>
  );
}

function SwapScenario({ runId, lots }: { runId: string; lots: Lot[] }) {
  const qc = useQueryClient();
  const factoriesQ = useQuery({ queryKey: ["factories"], queryFn: api.factories, staleTime: Infinity });
  const [lotId, setLotId] = useState(lots[0]?.lot_id ?? "");
  const lot = lots.find((l) => l.lot_id === lotId) ?? lots[0];
  const options = (factoriesQ.data ?? []).map((f) => f.factory_id).filter((f) => f !== lot?.assigned_factory);
  const certified = lot?.certified_factories ?? [];
  const [target, setTarget] = useState("");
  useEffect(() => {
    const firstCertified = options.find((f) => certified.includes(f)) ?? options[0] ?? "";
    if (!options.includes(target)) setTarget(firstCertified);
  }, [lotId, options.join(","), certified.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const result = useQuery({
    queryKey: ["swap", runId, lot?.lot_id, target],
    queryFn: () => api.swapScenario(runId, lot!.lot_id, target),
    enabled: !!lot && !!target,
  });
  const apply = useMutation({
    mutationFn: () => api.setLot(runId, lot!.lot_id, lot!.decision, target, ""),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plan", runId] }),
  });

  if (!lot) return <Empty title="No lots this week" />;
  const r = result.data;
  return (
    <Layout2 controls={
      <>
        <Select label="Lot" value={lot.lot_id} onChange={(e) => setLotId(e.target.value)}>
          {lots.map((l) => <option key={l.lot_id} value={l.lot_id}>{l.lot_id.split("-").pop()} · {l.article_id} · {l.market_destination} · {l.assigned_factory}</option>)}
        </Select>
        <Select label={`Move from ${lot.assigned_factory} to`} value={target} onChange={(e) => setTarget(e.target.value)}>
          {options.map((f) => (
            <option key={f} value={f}>{f}{certified.includes(f) ? "" : " (not certified)"}</option>
          ))}
        </Select>
        {r && r.valid && (
          <Button variant="primary" className="w-full" disabled={apply.isPending || apply.isSuccess} onClick={() => apply.mutate()}>
            {apply.isSuccess ? "Switch applied" : `Apply switch to ${target}`}
          </Button>
        )}
      </>
    }>
      {result.isLoading ? <Loading /> : result.error ? <ErrorBox error={result.error} /> : r && (
        !r.valid ? (
          <div className="flex items-start gap-2 rounded-lg border border-bad/20 bg-bad-soft p-4 text-sm text-bad">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {r.message}
          </div>
        ) : (
          <>
            <div className="grid items-stretch gap-3 md:grid-cols-[1fr_auto_1fr]">
              <Card className="p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted">Current</div>
                <div className="mt-1 text-lg font-semibold">{r.from_factory}</div>
                <dl className="mt-3 space-y-1.5 text-sm">
                  <Row k="Cost" v={money(r.cost_before_usd)} />
                  <Row k="Cost multiplier" v={r.cost_multiplier_before.toFixed(2)} />
                  <Row k="Arrival" v={date(r.arrival_before)} />
                </dl>
              </Card>
              <div className="hidden items-center md:flex"><ArrowRight className="text-faint" /></div>
              <Card className="border-accent/40 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-accent">After switch</div>
                <div className="mt-1 text-lg font-semibold">{r.to_factory}</div>
                <dl className="mt-3 space-y-1.5 text-sm">
                  <Row k="Cost" v={<>{money(r.cost_after_usd)} <Delta value={r.cost_delta_usd} /></>} />
                  <Row k="Cost multiplier" v={r.cost_multiplier_after.toFixed(2)} />
                  <Row k="Arrival" v={<>{date(r.arrival_after)} {r.on_time_after ? <Badge tone="good">On time</Badge> : <Badge tone="bad">Late</Badge>}</>} />
                </dl>
              </Card>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Lead-time change" value={`${r.lead_time_delta_days > 0 ? "+" : ""}${r.lead_time_delta_days} days`} tone={r.lead_time_delta_days > 0 ? "warn" : "good"} />
              <Stat label="Target factory load" value={`${r.target_utilization_pct.toFixed(0)}%`} tone={r.capacity_warning ? "warn" : "good"} />
              <Stat label="Minimum order still met" value={r.moq_still_met ? <span className="inline-flex items-center gap-1"><CheckCircle2 size={16} /> Yes</span> : "No"} tone={r.moq_still_met ? "good" : "bad"} />
            </div>
            {r.capacity_warning && (
              <div className="rounded-lg bg-warn-soft p-3 text-sm text-warn">{r.to_factory} is above the capacity threshold in those production weeks.</div>
            )}
          </>
        )
      )}
    </Layout2>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex justify-between gap-3"><dt className="text-muted">{k}</dt><dd className="font-medium">{v}</dd></div>;
}

function Delta({ value }: { value: number }) {
  if (!value) return null;
  return <span className={cx("ml-1 text-xs font-semibold", value > 0 ? "text-bad" : "text-good")}>{value > 0 ? "+" : "−"}{money(Math.abs(value))}</span>;
}
