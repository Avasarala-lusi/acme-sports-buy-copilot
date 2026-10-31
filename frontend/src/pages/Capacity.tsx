import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { Card, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useRun } from "../lib/run";
import { useToken } from "../lib/theme";

// Color follows the factory, never its rank: slot n of the validated categorical palette per factory.
const FACTORY_ORDER = ["ACME-VN01", "ACME-BD02", "ACME-ID03", "ACME-CN04", "ACME-TR05", "ACME-IN06"];

export function Capacity() {
  const { runId } = useRun();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: Infinity });
  const cap = useQuery({ queryKey: ["capacity", runId], queryFn: () => api.capacity(runId) });
  const threshold = settings.data?.thresholds.backup_threshold_pct ?? 85;
  const limit = settings.data?.thresholds.hard_limit_pct ?? 100;
  const series = [1, 2, 3, 4, 5, 6].map((n) => useToken(`--color-series-${n}`)); // eslint-disable-line react-hooks/rules-of-hooks
  const grid = useToken("--color-grid"), axis = useToken("--color-axis"), ink = useToken("--color-ink");
  const panel = useToken("--color-panel"), line = useToken("--color-line");
  const warn = useToken("--color-status-warning"), critical = useToken("--color-status-critical");

  const { data, factories } = useMemo(() => {
    const rows = cap.data ?? [];
    const factories = [...new Set(rows.map((r) => r.factory_id))].sort((a, b) => FACTORY_ORDER.indexOf(a) - FACTORY_ORDER.indexOf(b));
    const byWeek = new Map<string, Record<string, number | string>>();
    for (const r of rows) {
      const key = r.week.slice(0, 10);
      const entry = byWeek.get(key) ?? { week: key };
      entry[r.factory_id] = Math.round(r.utilization_pct);
      byWeek.set(key, entry);
    }
    return { data: [...byWeek.values()].sort((a, b) => String(a.week).localeCompare(String(b.week))), factories };
  }, [cap.data]);

  if (cap.isLoading) return <Loading />;
  if (cap.error) return <ErrorBox error={cap.error} />;
  const color = (f: string) => series[(FACTORY_ORDER.indexOf(f) + FACTORY_ORDER.length) % FACTORY_ORDER.length] || axis;
  return (
    <>
      <PageHeader eyebrow="Rolling capacity ledger" title="Capacity"
        subtitle={`Weekly load from our assignments, including this week's lots (a preview in a draft week). Every purchase, including last-chance demand, must stay within ${limit}%.`} />
      <Card className="p-5">
        <div className="h-[480px]">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 16, right: 24, bottom: 0, left: 0 }}>
              <CartesianGrid stroke={grid} vertical={false} />
              <XAxis dataKey="week" tick={{ fontSize: 11, fill: axis }} tickLine={false} axisLine={{ stroke: grid }}
                tickFormatter={(w: string) => w.slice(5)} minTickGap={28} />
              <YAxis tick={{ fontSize: 11, fill: axis }} tickLine={false} axisLine={false} unit="%" width={48} />
              <Tooltip formatter={(v: number) => `${v}%`} labelFormatter={(w: string) => `Week of ${w}`}
                contentStyle={{ background: panel, border: `1px solid ${line}`, borderRadius: 12, fontSize: 12, color: ink }}
                labelStyle={{ color: ink, fontWeight: 600 }} itemSorter={(i) => -Number(i.value)} />
              <Legend wrapperStyle={{ fontSize: 12, color: ink }} iconType="plainline" />
              <ReferenceLine y={threshold} stroke={warn} strokeDasharray="5 4"
                label={{ value: `${threshold}% threshold`, fontSize: 11, fill: axis, position: "insideTopRight" }} />
              <ReferenceLine y={limit} stroke={critical} strokeDasharray="2 3"
                label={{ value: `${limit}% limit`, fontSize: 11, fill: axis, position: "insideTopLeft" }} />
              {factories.map((f) => (
                <Line key={f} dataKey={f} name={f.replace("ACME-", "")} stroke={color(f)} strokeWidth={2} dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: panel }} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </>
  );
}
