import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { api } from "../api/client";
import { Badge, Card, ErrorBox, Loading, PageHeader, SectionTitle, Stat } from "../components/ui";
import { int, num } from "../lib/format";

const labels: Record<string, string> = {
  every_pr_has_one_outcome: "Every requisition has exactly one outcome",
  no_pr_in_two_lots: "No requisition appears in two lots",
  bought_prs_match_lots: "Bought requisitions match the bought lots",
  review_prs_visible: "Requests needing review remain traceable",
  purchases_only_in_buying_windows: "Purchases are committed only in MID/EOM buying runs",
  no_overload: "Every factory production week respects the hard ceiling",
  units_add_up: "Units add up across all outcomes",
  lot_qty_matches_prs: "Lot quantities equal their requisitions",
};

const outcomeLabels: Record<string, string> = {
  BOUGHT: "Bought",
  FUTURE_FORECAST: "Moved to Future (forecast)",
  OPEN: "Waiting, not yet due",
  PLANNER_REVIEW: "Needs planner review (no factory capacity)",
  UNRESOLVED_MOQ: "Unresolved: below MOQ",
  UNRESOLVED_MPQ: "Unresolved: below MPQ",
};

export function Checks() {
  const checks = useQuery({ queryKey: ["checks"], queryFn: api.checks, staleTime: Infinity });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: Infinity });
  const issues = useQuery({ queryKey: ["issues"], queryFn: api.dataIssues, staleTime: Infinity });

  if (checks.isLoading) return <Loading label="Running checks…" />;
  if (checks.error) return <ErrorBox error={checks.error} />;
  const c = checks.data!;
  const total = Object.values(c.units_by_outcome).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHeader eyebrow="Validation" title="Data & checks" subtitle="Validation across all 100 runs, settings to confirm, and data findings." />
      <div className="mb-6 grid gap-3 md:grid-cols-3">
        <Stat label="Complete accounting" value={c.passed ? "Passed" : "Failed"} tone={c.passed ? "good" : "bad"} />
        <Stat label="Requisitions accounted for" value={`${int(c.prs_seen)} · ${int(c.units_seen)} units`} />
        <Stat label="Rule violations without a warning" value={c.rule_violations} tone={c.rule_violations ? "bad" : "good"} />
      </div>

      <div className="mb-6 grid gap-5 lg:grid-cols-2">
        <Card className="p-4">
          <SectionTitle>Accounting checks</SectionTitle>
          <ul className="space-y-2">
            {Object.entries(c.checks).map(([k, ok]) => (
              <li key={k} className="flex items-center gap-2 text-sm">
                {ok ? <CheckCircle2 size={16} className="text-good" /> : <XCircle size={16} className="text-bad" />}
                {labels[k] ?? k}
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-4">
          <SectionTitle>Where every unit went</SectionTitle>
          <div className="space-y-2.5">
            {Object.entries(c.units_by_outcome).map(([k, v]) => (
              <div key={k}>
                <div className="mb-1 flex justify-between text-sm"><span>{outcomeLabels[k] ?? k}</span><span className="tabular-nums text-muted">{int(v)}</span></div>
                <div className="h-2 rounded-full bg-sidebar"><div className="h-2 rounded-full bg-accent" style={{ width: `${(v / total) * 100}%` }} /></div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <SectionTitle>Settings to confirm with the client</SectionTitle>
      <Card className="mb-6 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-sidebar text-xs text-muted">
            <tr><th className="px-4 py-2 text-left font-medium">Topic</th><th className="px-4 py-2 text-left font-medium">Current setting</th><th className="px-4 py-2 text-left font-medium">Status</th></tr>
          </thead>
          <tbody>
            {(settings.data?.items ?? []).map((s) => (
              <tr key={s.topic} className="border-t border-line">
                <td className="px-4 py-2 font-medium">{s.topic}</td>
                <td className="px-4 py-2">{s.setting}</td>
                <td className="px-4 py-2">{s.status.startsWith("Client") ? <Badge tone="good">{s.status}</Badge> : <Badge tone="warn">{s.status}</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <SectionTitle>Data findings</SectionTitle>
          <div className="space-y-2">
            {(issues.data ?? []).map((i) => (
              <div key={i} className="flex items-start gap-2 rounded-lg border border-line bg-panel p-3 text-sm">
                <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" /> {i}
              </div>
            ))}
          </div>
        </div>
        <div>
          <SectionTitle hint="Different purchased volumes; total cost differences are not validated savings">Comparison with the as-is assignments</SectionTitle>
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-sidebar text-xs text-muted">
                <tr><th className="px-4 py-2 text-left font-medium">Metric</th><th className="px-4 py-2 text-right font-medium">Our plan</th><th className="px-4 py-2 text-right font-medium">As-is</th></tr>
              </thead>
              <tbody>
                {c.comparison.map((r) => (
                  <tr key={r.metric} className="border-t border-line">
                    <td className="px-4 py-2">{r.metric.replaceAll("_", " ")}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{num(r.our_plan, r.our_plan < 1000 ? 1 : 0)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{num(r.as_is_reference, r.as_is_reference < 1000 ? 1 : 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      </div>

      <div className="mt-6">
        <SectionTitle hint="Same requisitions and units as our plan buys">Evaluation against the client's baseline</SectionTitle>
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-sidebar text-xs text-muted">
              <tr><th className="px-4 py-2 text-left font-medium">Measure</th><th className="px-4 py-2 text-right font-medium">Baseline</th>
                <th className="px-4 py-2 text-right font-medium">Our plan</th><th className="px-2 py-2" /></tr>
            </thead>
            <tbody>
              {(c.baseline ?? []).map((r) => (
                <tr key={r.metric} className="border-t border-line">
                  <td className="px-4 py-2">{r.metric}{r.note && <div className="text-[11px] text-faint">{r.note}</div>}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{num(r.baseline, Math.abs(r.baseline) < 1000 ? 1 : 0)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{num(r.our_plan, Math.abs(r.our_plan) < 1000 ? 1 : 0)}</td>
                  <td className="px-2 py-2">{r.improved == null ? null : r.improved
                    ? <Badge tone="good">better</Badge> : <Badge tone="warn">worse</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-line px-4 py-2.5 text-xs text-faint">
            Baseline = the factory assignments recorded in fact_purchase_requisitions (client decision), on the same requisitions.
          </div>
        </Card>
      </div>
    </>
  );
}
