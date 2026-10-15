import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpFromLine, CircleSlash, Clock, Factory, Hourglass, Layers, Scale } from "lucide-react";
import { api } from "../api/client";
import type { Decision, Lot, LotDecision } from "../api/types";
import { Drawer } from "../components/Drawer";
import { Badge, Button, LoadBar, Loading, Segmented, Select, Stat, Tabs, cx } from "../components/ui";
import { DataTable } from "../components/DataTable";
import { date, int, load, money, splitList } from "../lib/format";

const ruleIcon = (text: string) => {
  if (text.startsWith("Rule 1")) return Clock;
  if (text.startsWith("Rule 2")) return Layers;
  if (text.startsWith("Rule 3")) return Scale;
  if (text.startsWith("Rule 4")) return ArrowUpFromLine;
  if (text.startsWith("Rule 5")) return CircleSlash;
  if (text.startsWith("Rule 6")) return Hourglass;
  return Factory;
};

export function LotBadges({ lot }: { lot: Lot }) {
  return (
    <>
      {lot.decision === "Review" && <Badge tone="warn" dot>Needs review</Badge>}
      {lot.decision !== "Buy" && lot.decision !== "Review" && <Badge tone="bad" dot>{lot.decision}</Badge>}
      {lot.capacity_status === "Over capacity (last chance)" && <Badge tone="bad">Over capacity</Badge>}
      {lot.decision_type === "manual" && <Badge tone="manual">Manual</Badge>}
      {lot.backup_routed && <Badge tone="info">Backup</Badge>}
      {lot.is_piggyback_applied && <Badge tone="accent">Piggyback</Badge>}
      {lot.last_chance && <Badge tone="warn">Last chance</Badge>}
      {lot.warnings && <Badge tone="warn"><AlertTriangle size={11} /> {splitList(lot.warnings).length}</Badge>}
    </>
  );
}

type Tab = "why" | "requisitions" | "decision";

export function LotDrawer({ lot, runId, draft, onClose }: { lot: Lot | null; runId: string; draft: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("why");
  const qc = useQueryClient();
  const [decision, setDecision] = useState<LotDecision>("Buy");
  const [factory, setFactory] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (lot) {
      setDecision(lot.decision);
      setFactory(lot.assigned_factory);
      setNote("");
    }
  }, [lot]);

  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: Infinity });
  const reqs = useQuery({
    queryKey: ["lotReqs", runId, lot?.lot_id],
    queryFn: () => api.lotRequisitions(runId, lot!.lot_id),
    enabled: !!lot && tab === "requisitions",
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["plan", runId] });
  const save = useMutation({
    mutationFn: () => api.setLot(runId, lot!.lot_id, decision, factory, note),
    onSuccess: () => { refresh(); onClose(); },
  });
  const revert = useMutation({
    mutationFn: () => api.revertLot(runId, lot!.lot_id),
    onSuccess: () => { refresh(); onClose(); },
  });

  if (!lot) return null;
  const rules = splitList(lot.reason);
  const warnings = splitList(lot.warnings);

  return (
    <Drawer open={!!lot} onClose={onClose}
      title={<span className="font-mono">{lot.lot_id}</span>}
      subtitle={<><span>{lot.article_id} · {lot.market_destination} · {lot.category}</span>{draft && <Badge tone="info">Draft</Badge>}<LotBadges lot={lot} /></>}>
      <div className="mb-5 grid grid-cols-2 gap-2">
        <Stat label="Units" value={int(lot.consolidated_qty)} />
        <Stat label={lot.decision === "Review" ? "Proposed factory" : "Factory"} value={<span className="text-base">{lot.assigned_factory}{lot.backup_routed && <span className="text-xs font-normal text-muted"> (primary {lot.primary_factory})</span>}</span>} />
        <Stat label="Production cost" value={money(lot.total_cost_usd)} />
        <Stat label="Buying window" value={<span className="text-base">{lot.buying_window} <span className="text-xs font-normal text-muted">{lot.plan_status}</span></span>} />
        <Stat label="Arrival vs RDD" tone={lot.on_time ? "good" : "bad"}
          value={<span className="text-base">{date(lot.expected_arrival)} <span className="text-xs font-normal text-muted">RDD {date(lot.earliest_rdd)}</span></span>} />
      </div>

      <div className="mb-5 rounded-xl border border-line p-3.5">
        <div className="mb-2.5 flex items-baseline justify-between gap-2 text-xs">
          <span className="text-muted">Load at {lot.assigned_factory} · busiest production week</span>
          <span className={cx("font-semibold tabular", lot.util_after_pct > 100 ? "text-bad" : lot.util_after_pct >= 85 ? "text-warn" : "text-good")}>
            {load(lot.util_before_pct)} → {load(lot.util_after_pct)} with this lot
          </span>
        </div>
        <LoadBar before={lot.util_before_pct} after={lot.util_after_pct}
          threshold={settings.data?.thresholds.backup_threshold_pct ?? 85} limit={settings.data?.thresholds.hard_limit_pct ?? 100} />
        <div className="text-xs text-faint">{lot.capacity_status} · grey = already planned, colour = this lot</div>
      </div>

      <Tabs value={tab} onChange={setTab} tabs={[
        { value: "why", label: "Why" },
        { value: "requisitions", label: "Requisitions", count: lot.n_prs },
        { value: "decision", label: "Decision" },
      ]} />

      {tab === "why" && (
        <div className="space-y-4">
          {lot.override_note && (
            <div className="rounded-lg border border-manual/20 bg-manual-soft p-3 text-sm text-manual">
              <span className="font-semibold">Manual change: </span>{lot.override_note}
            </div>
          )}
          <ol className="relative">
            {rules.map((r, i) => {
              const Icon = ruleIcon(r);
              const [head, ...rest] = r.split(": ");
              const last = i === rules.length - 1;
              return (
                <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
                  {!last && <span className="absolute left-[15px] top-8 h-[calc(100%-24px)] w-px bg-line" />}
                  <div className="relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border border-line bg-panel text-accent shadow-[var(--shadow-card)]">
                    <Icon size={15} />
                  </div>
                  <div className="pt-1 text-sm">
                    <div className="font-semibold">{rest.length ? head : `Step ${i + 1}`}</div>
                    <div className="text-muted">{rest.length ? rest.join(": ") : r}</div>
                  </div>
                </li>
              );
            })}
          </ol>
          {warnings.length > 0 && (
            <div className="space-y-1.5">
              {warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 rounded-xl border border-warn/20 bg-warn-soft p-3 text-sm text-warn">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" /> {w}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "requisitions" && (reqs.isLoading ? <Loading /> : (
        <DataTable rows={reqs.data ?? []} rowKey={(r) => r.pr_id} maxHeight="50vh" columns={[
          { key: "pr_id", header: "Requisition", render: (r) => <span className="font-mono text-xs">{r.pr_id}</span> },
          { key: "size_id", header: "Size" },
          { key: "channel_id", header: "Channel", render: (r) => (r.channel_id === "01" ? "Wholesale" : "DTC") },
          { key: "requested_qty", header: "Units", align: "right", render: (r) => int(r.requested_qty) },
          { key: "rdd_original", header: "RDD", render: (r) => date(r.rdd_original) },
          { key: "customer_id", header: "Customer", render: (r) => r.customer_id ?? "Forecast" },
          { key: "nsv", header: "Sales value", align: "right", render: (r) => money(r.nsv) },
        ]} />
      ))}

      {tab === "decision" && draft && (
        <p className="rounded-lg bg-info-soft p-3 text-sm text-info">
          This is a draft lot. Lots and their IDs can change every week until the buying run, so decisions are made there.
        </p>
      )}
      {tab === "decision" && !draft && (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Decisions are saved separately from the automatic plan and marked as manual. Exports use the decided plan.
          </p>
          {lot.auto_decision === "Review" && (
            <p className="rounded-lg bg-warn-soft p-3 text-sm text-warn">
              No certified factory had room for this lot. Choosing Buy approves it although the factory will be over its limit;
              switching to a factory with room or No-Go are the alternatives.
            </p>
          )}
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted">Go / No-Go</div>
            <Segmented value={decision as Decision} onChange={setDecision}
              options={[{ value: "Buy", label: "Buy" }, { value: "No-Go", label: "No-Go" }, { value: "Delay", label: "Delay" }]} />
          </div>
          <Select label="Factory (certified for this article)" value={factory} onChange={(e) => setFactory(e.target.value)}>
            {lot.certified_factories.map((f) => <option key={f} value={f}>{f}{f === lot.primary_factory ? " (primary)" : ""}</option>)}
          </Select>
          <label className="flex flex-col gap-1 text-xs font-medium text-muted">
            Note
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Why is this changed? (shown on the lot)"
              className="rounded-lg border border-line px-2.5 py-2 text-sm text-ink outline-none focus:border-accent" />
          </label>
          {(save.error || revert.error) && <div className="text-sm text-bad">{String((save.error ?? revert.error) as Error)}</div>}
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>
              {lot.auto_decision === "Review" && decision === "Buy" ? "Approve purchase" : "Save decision"}
            </Button>
            {lot.decision_type === "manual" && (
              <Button variant="danger" onClick={() => revert.mutate()} disabled={revert.isPending}>Revert to automatic</Button>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}
