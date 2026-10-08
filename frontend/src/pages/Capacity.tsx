import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { Card, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useRun } from "../lib/run";

const COLORS = ["#b04812", "#1d5fa8", "#1f7a4d", "#6b3fa0", "#946200", "#5e6975"];

export function Capacity() {
  const { runId } = useRun();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: Infinity });
  const cap = useQuery({ queryKey: ["capacity", runId], queryFn: () => api.capacity(runId) });
  const threshold = settings.data?.thresholds.backup_threshold_pct ?? 85;

  const { data, factories } = useMemo(() => {
    const rows = cap.data ?? [];
    const factories = [...new Set(rows.map((r) => r.factory_id))].sort();
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
  return (
    <>
      <PageHeader title="Capacity"
        subtitle="Weekly load per factory from our own assignments (rolling ledger), around the selected week. The dashed line is the backup threshold." />
      <Card className="p-4">
        <div className="h-[460px]">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#e7e4dc" vertical={false} />
              <XAxis dataKey="week" tick={{ fontSize: 11, fill: "#5e6975" }} tickFormatter={(w: string) => w.slice(5)} minTickGap={24} />
              <YAxis tick={{ fontSize: 11, fill: "#5e6975" }} unit="%" />
              <Tooltip formatter={(v: number) => `${v}%`} labelFormatter={(w: string) => `Week of ${w}`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <ReferenceLine y={threshold} stroke="#b42318" strokeDasharray="5 4" label={{ value: `${threshold}% threshold`, fontSize: 11, fill: "#b42318", position: "insideTopRight" }} />
              {factories.map((f, i) => (
                <Line key={f} dataKey={f} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </>
  );
}
