import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CircleDollarSign, Clock, Gauge } from "lucide-react";
import { api } from "../api/client";
import type { RiskLot } from "../api/types";
import { DataTable } from "../components/DataTable";
import { Badge, Card, ErrorBox, Kpi, Loading, PageHeader, SectionTitle, Segmented, cx } from "../components/ui";
import { useRun } from "../lib/run";
import { date, int, moneyShort, pct } from "../lib/format";

const BAND_COLORS: Record<string, string> = {
  "below 50%": "var(--color-status-critical)", "50-80%": "var(--color-status-warning)",
  "80-95%": "var(--color-series-2)", "95% or more": "var(--color-status-good)",
};
const short = (f: string) => f.replace("ACME-", "");

export function Risk() {
  const { runId } = useRun();
  const [scope, setScope] = useState<"all" | "run">("all");
  const q = useQuery({ queryKey: ["risk", scope === "run" ? runId : null], queryFn: () => api.risk(scope === "run" ? runId : undefined) });

  const header = (
    <PageHeader eyebrow="On-time probability · lead-time variation" title="How likely is each lot to arrive on time?"
      subtitle="The plan uses quoted lead times. Real production and shipping vary, so this simulates each lot's lead times within its factory's published range and shows the chance it arrives by the requested date, weighted by sales value."
      actions={<Segmented value={scope} onChange={setScope} options={[{ value: "all", label: "Whole plan" }, { value: "run", label: runId }]} />} />
  );
  if (q.isLoading) return <>{header}<Loading label="Simulating lead times…" /></>;
  if (q.error) return <>{header}<ErrorBox error={q.error} /></>;
  const r = q.data!;
  if (!r.lots) return <>{header}<Card className="p-5 text-sm text-muted">No lots are bought in {runId}: it is not a buying run, or nothing was due. Pick a buying run, or view the whole plan.</Card></>;
  const total = r.bands.reduce((t, b) => t + b.units, 0) || 1;

  return (
    <>
      {header}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Clock} label="On time · planned → expected" value={`${pct(r.planned_on_time_pct, 0)} → ${pct(r.expected_on_time_pct, 0)}`}
          sub={`of ${int(r.units)} bought units, ${int(r.lots)} lots`} />
        <Kpi icon={CircleDollarSign} label="Sales value at risk" value={moneyShort(r.nsv_at_risk_usd)}
          sub={`${pct(r.value_weighted_on_time_pct, 0)} of ${moneyShort(r.nsv_usd)} expected on time`} />
        <Kpi icon={AlertTriangle} label="Planned on time, but below 80% likely" value={int(r.planned_on_time_but_at_risk_lots)}
          sub="lots with little or no buffer before the requested date" />
        <Kpi icon={Gauge} label="Assumed variation" value={`−${r.assumption.early_share_of_range * 100}% / +${r.assumption.late_share_of_range * 100}%`}
          sub="of each factory's quoted lead-time range (delays larger than gains)" />
      </div>

      <div className="mb-5 grid gap-4 xl:grid-cols-[1.1fr_1fr]">
        <Card className="p-5">
          <SectionTitle hint="units by chance of arriving on time">Confidence</SectionTitle>
          <div className="flex h-3 gap-[2px] overflow-hidden rounded-full">
            {r.bands.filter((b) => b.units).map((b) => (
              <div key={b.band} title={`${b.band}: ${int(b.units)} units`} style={{ flexGrow: b.units, background: BAND_COLORS[b.band] }} />
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {r.bands.map((b) => (
              <div key={b.band} className="rounded-xl border border-line p-3">
                <div className="flex items-center gap-1.5 text-xs text-muted"><i className="h-2 w-2 rounded-full" style={{ background: BAND_COLORS[b.band] }} />{b.band}</div>
                <div className="font-num mt-1 text-lg">{pct(b.units / total * 100, 0)}</div>
                <div className="text-[11px] text-faint">{int(b.lots)} lots · {int(b.units)} units</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">Most of the gap comes from lots planned to arrive on, or a day or two before, the requested date: correct on paper, but with no buffer for a late shipment. A few days of buffer on high-value lots would protect most of the value at risk.</p>
        </Card>
        <Card className="p-5">
          <SectionTitle hint="planned vs expected, with the delay range used">By factory</SectionTitle>
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-2 font-medium">Factory</th><th className="py-2 text-right font-medium">Units</th>
              <th className="py-2 text-right font-medium">Planned</th><th className="py-2 text-right font-medium">Expected</th>
              <th className="py-2 text-right font-medium">Delay P10 / P50 / P90</th></tr></thead>
            <tbody>
              {r.by_factory.map((f) => {
                const d = r.factories.find((x) => x.factory_id === f.assigned_factory);
                return (
                  <tr key={f.assigned_factory} className="border-b border-line/60 last:border-0">
                    <td className="py-2">{short(f.assigned_factory)}</td>
                    <td className="font-num py-2 text-right">{int(f.units)}</td>
                    <td className="font-num py-2 text-right text-muted">{pct(f.planned_on_time_pct, 0)}</td>
                    <td className={cx("font-num py-2 text-right", f.expected_on_time_pct < 50 ? "text-bad" : "text-ink")}>{pct(f.expected_on_time_pct, 0)}</td>
                    <td className="font-num py-2 text-right text-faint">{d ? `${d.delay_p10_days.toFixed(0)} / +${d.delay_p50_days.toFixed(0)} / +${d.delay_p90_days.toFixed(0)} d` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </div>

      <SectionTitle hint="largest sales value at risk first">Lots to watch</SectionTitle>
      <DataTable<RiskLot> rows={r.riskiest} rowKey={(x) => x.lot_id} maxHeight="55vh" columns={[
        { key: "run_id", header: "Run" },
        { key: "article_id", header: "Article" },
        { key: "market_destination", header: "Market" },
        { key: "assigned_factory", header: "Factory", render: (x) => short(x.assigned_factory) },
        { key: "units", header: "Units", align: "right", render: (x) => <span className="font-num">{int(x.units)}</span> },
        { key: "earliest_rdd", header: "Requested", render: (x) => date(x.earliest_rdd) },
        { key: "min_slack_days", header: "Buffer", align: "right", render: (x) => <span className="font-num">{x.min_slack_days.toFixed(0)} d</span> },
        { key: "p_on_time", header: "Chance on time", align: "right",
          render: (x) => <Badge tone={x.p_on_time < 0.5 ? "bad" : x.p_on_time < 0.8 ? "warn" : "good"}>{pct(x.p_on_time * 100, 0)}</Badge> },
        { key: "nsv_at_risk_usd", header: "Value at risk", align: "right", render: (x) => <span className="font-num">{moneyShort(x.nsv_at_risk_usd)}</span> },
      ]} />
    </>
  );
}
