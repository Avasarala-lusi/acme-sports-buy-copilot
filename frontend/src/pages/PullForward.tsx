import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import { Badge, Card, ErrorBox, Loading, PageHeader, SectionTitle, cx } from "../components/ui";
import { useRun } from "../lib/run";
import { int, money } from "../lib/format";

const cellTone = (u: number, threshold: number) =>
  u >= 150 ? "bg-bad text-white dark:text-[#2a0b0a]" : u >= threshold ? "bg-bad-soft text-bad" : u >= 60 ? "bg-warn-soft text-warn" : "bg-good-soft text-good";

export function PullForward() {
  const { runId } = useRun();
  const [onlyActionable, setOnlyActionable] = useState(true);
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: Infinity });
  const pf = useQuery({ queryKey: ["pullForward", runId], queryFn: () => api.pullForward(runId) });
  const threshold = settings.data?.thresholds.backup_threshold_pct ?? 85;

  const grid = useMemo(() => {
    const w = pf.data?.windows ?? [];
    const windows = [...new Set(w.map((x) => x.window))];
    const factories = [...new Set(w.map((x) => x.factory_id))].sort();
    const cell = (f: string, win: string) => w.find((x) => x.factory_id === f && x.window === win);
    return { windows, factories, cell };
  }, [pf.data]);

  if (pf.isLoading) return <Loading label="Projecting factory load…" />;
  if (pf.error) return <ErrorBox error={pf.error} />;
  const recs = (pf.data?.recommendations ?? []).filter((r) => !onlyActionable || r.actionable);

  return (
    <>
      <PageHeader eyebrow="Spec 3.3 · capacity-driven" title="Pull-forward"
        subtitle={`Projected load for the next buying windows: planned lots plus open demand at its primary factory. A window whose busiest week reaches ${threshold}% gets recommendations, each tested together with the ones before it.`} />

      <SectionTitle hint="Busiest week in each window (average across its weeks below)">Factory load by buying window</SectionTitle>
      <Card className="mb-6 overflow-x-auto p-4">
        <table className="w-full border-separate border-spacing-1.5 text-sm">
          <thead>
            <tr>
              <th className="w-32 text-left text-xs font-medium text-muted">Factory</th>
              {grid.windows.map((w, i) => (
                <th key={w} className="text-center text-xs font-medium text-muted">{w.replace("WIN-", "")}{i === 0 && <div className="text-[10px] text-faint">current</div>}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.factories.map((f) => (
              <tr key={f}>
                <td className="font-medium">{f}</td>
                {grid.windows.map((w) => {
                  const c = grid.cell(f, w);
                  const u = c?.peak_utilization_pct ?? 0;
                  return (
                    <td key={w} title={c ? `${c.weeks} weeks, ${int(c.units)} units` : undefined}
                      className={cx("rounded-lg px-3 py-2 text-center font-semibold tabular-nums", cellTone(u, threshold))}>
                      {u.toFixed(0)}%
                      <div className="text-[10px] font-normal opacity-75">avg {(c?.avg_utilization_pct ?? 0).toFixed(0)}%</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
          <span className="inline-flex items-center gap-1"><i className="h-3 w-3 rounded bg-good-soft" /> under 60%</span>
          <span className="inline-flex items-center gap-1"><i className="h-3 w-3 rounded bg-warn-soft" /> 60–{threshold}%</span>
          <span className="inline-flex items-center gap-1"><i className="h-3 w-3 rounded bg-bad-soft" /> {threshold}% or more</span>
          <span className="inline-flex items-center gap-1"><i className="h-3 w-3 rounded bg-bad" /> 150% or more</span>
        </div>
      </Card>

      <SectionTitle hint={`${(pf.data?.recommendations ?? []).filter((r) => r.actionable).length} actionable of ${(pf.data?.recommendations ?? []).length} reviewed`}>
        Recommendations
      </SectionTitle>
      <label className="mb-3 inline-flex items-center gap-2 text-sm text-muted">
        <input type="checkbox" checked={onlyActionable} onChange={(e) => setOnlyActionable(e.target.checked)} className="accent-[#b04812]" />
        Only actionable (an earlier window has room, and MOQ and MPQ still hold after the move)
      </label>
      <DataTable rows={recs} rowKey={(r) => `${r.factory_id}-${r.overloaded_window}-${r.article_id}-${r.market_destination}`}
        emptyText="No actionable pull-forward this week" columns={[
          { key: "factory_id", header: "Factory" },
          { key: "overloaded_window", header: "Overloaded window", render: (r) => <>{r.overloaded_window} <Badge tone="bad">{r.overloaded_util_pct.toFixed(0)}%</Badge></> },
          { key: "article_id", header: "Article" },
          { key: "market_destination", header: "Market" },
          { key: "units", header: "Units", align: "right", render: (r) => int(r.units) },
          { key: "recommendation", header: "Recommendation", render: (r) => <span className="inline-block min-w-[320px] whitespace-normal">{r.recommendation}</span> },
          { key: "checks", header: "Checks", value: (r) => Number(r.capacity_ok) + Number(r.moq_ok_for_market) + Number(r.mpq_target_ok) + Number(r.mpq_source_ok),
            render: (r) => (
              <div className="flex gap-1">
                <Badge tone={r.capacity_ok ? "good" : "warn"} title="Busiest affected week stays below the threshold">Capacity</Badge>
                <Badge tone={r.moq_ok_for_market ? "good" : "warn"} title="Market reaches MOQ in the target window">MOQ</Badge>
                <Badge tone={r.mpq_target_ok && r.mpq_source_ok ? "good" : "warn"} title="MPQ holds in the target window and in what stays behind">MPQ</Badge>
              </div>
            ) },
          { key: "extra_cost_if_routed_to_backup_usd", header: "Backup instead", align: "right",
            title: "Extra cost if this demand is routed to the backup factory instead (negative = backup is cheaper)",
            render: (r) => money(r.extra_cost_if_routed_to_backup_usd) },
        ]} />
    </>
  );
}
