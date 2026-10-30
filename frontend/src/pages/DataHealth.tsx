import { useQuery } from "@tanstack/react-query";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, FileWarning, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import type { HealthFlag } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Badge, Card, ErrorBox, Kpi, Loading, PageHeader, SectionTitle } from "../components/ui";
import { useRun } from "../lib/run";
import { useToken } from "../lib/theme";
import { int, pct } from "../lib/format";

const TONE = { error: "bad", warning: "warn", info: "neutral" } as const;

export function DataHealth() {
  const { runId } = useRun();
  const q = useQuery({ queryKey: ["data-health", runId], queryFn: () => api.dataHealth(runId) });
  const s1 = useToken("--color-series-1"), s3 = useToken("--color-series-3");
  const grid = useToken("--color-grid"), axis = useToken("--color-axis"), ink = useToken("--color-ink");
  const panel = useToken("--color-panel"), line = useToken("--color-line");
  if (q.isLoading) return <Loading label="Checking every data load…" />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data!;
  const run = d.run!;
  const tooltip = { contentStyle: { background: panel, border: `1px solid ${line}`, borderRadius: 10, fontSize: 12 }, labelStyle: { color: ink } };

  return (
    <>
      <PageHeader eyebrow={`Data health · ${runId}`} title="Is this week's data load normal?"
        subtitle="Every requisition is checked when its run is loaded, and each run's volume is compared with earlier runs at the same point of the season (demand swings about 12× between stages). Flags are for review; they never change the plan." />

      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={ShieldCheck} label={`${runId} · records flagged`} value={`${int(run.flagged_records)} of ${int(run.records)}`}
          sub={`${run.errors} errors · ${run.warnings} warnings · ${run.info} for information`} />
        <Kpi icon={Activity} label={`${runId} · volume vs expected`}
          value={run.volume_change_pct == null ? "—" : `${run.volume_change_pct >= 0 ? "+" : ""}${pct(run.volume_change_pct, 0)}`}
          sub={run.expected_units == null ? "not enough history yet" : `${int(run.units)} vs ${int(run.expected_units)} units (${run.expected_basis})`} />
        <Kpi icon={FileWarning} label="All runs · records flagged" value={pct(d.flagged_pct, 1)} sub={`${int(d.flagged_records)} of ${int(d.records)} (errors and warnings)`} />
        <Kpi label="Runs with unusual volume" value={`${d.runs_with_volume_flag} of ${d.runs.length}`} sub="more than ±60% from the expected level" />
      </div>

      <div className="mb-5 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card className="p-5">
          <SectionTitle hint="units received per run vs the expected level">Volume by run</SectionTitle>
          <div className="h-[260px]">
            <ResponsiveContainer>
              <ComposedChart data={d.runs.map((r) => ({ ...r, flagged: r.volume_flag ? r.units : null, normal: r.volume_flag ? null : r.units }))}
                margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={grid} vertical={false} />
                <XAxis dataKey="week_number" tick={{ fontSize: 11, fill: axis }} tickLine={false} minTickGap={20} />
                <YAxis tick={{ fontSize: 11, fill: axis }} tickLine={false} axisLine={false} width={52} tickFormatter={(v: number) => `${Math.round(v / 1000)}k`} />
                <Tooltip {...tooltip} labelFormatter={(w) => `Week ${w}`} formatter={(v: number, n: string) => [int(v), n]} />
                <Legend wrapperStyle={{ fontSize: 12, color: ink }} />
                <Bar dataKey="normal" name="Units" stackId="u" fill={s1} isAnimationActive={false} />
                <Bar dataKey="flagged" name="Unusual volume" stackId="u" fill="var(--color-status-warning)" isAnimationActive={false} />
                <Line dataKey="expected_units" name="Expected" stroke={s3} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card className="p-5">
          <SectionTitle hint="all runs">Checks</SectionTitle>
          <div className="space-y-2">
            {d.checks.map((c) => (
              <div key={c.check} className="flex items-start justify-between gap-3 border-b border-line/60 pb-2 text-sm last:border-0">
                <div><Badge tone={TONE[c.severity]}>{c.severity}</Badge> <span className="text-muted">{c.description}</span></div>
                <span className="font-num whitespace-nowrap">{c.records ? int(c.records) : <span className="text-good">0</span>}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <SectionTitle hint={`${runId}: errors first`}>Flagged records this run</SectionTitle>
      <DataTable<HealthFlag> rows={run.flags} rowKey={(x) => `${x.pr_id}-${x.check}`} maxHeight="50vh" emptyText="Nothing unusual in this run's load" columns={[
        { key: "severity", header: "Severity", render: (x) => <Badge tone={TONE[x.severity]}>{x.severity}</Badge> },
        { key: "check", header: "Check", render: (x) => x.check.replaceAll("_", " ") },
        { key: "pr_id", header: "Requisition" },
        { key: "article_id", header: "Article" },
        { key: "market_destination", header: "Market" },
        { key: "requested_qty", header: "Units", align: "right", render: (x) => <span className="font-num">{int(x.requested_qty)}</span> },
        { key: "detail", header: "Detail", render: (x) => <span className="text-muted">{x.detail}</span> },
      ]} />
      {d.load_findings.length > 0 && (
        <Card className="mt-5 p-5">
          <SectionTitle hint="whole data set">Findings when the data was loaded</SectionTitle>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">{d.load_findings.map((f) => <li key={f}>{f}</li>)}</ul>
        </Card>
      )}
    </>
  );
}
