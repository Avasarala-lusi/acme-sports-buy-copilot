import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { date, pct } from "../lib/format";

export function ForecastWarning({ runId, lotId, factory }: { runId: string; lotId: string; factory: string }) {
  const q = useQuery({ queryKey: ["forecast-decision", runId, lotId, factory],
    queryFn: () => api.forecastDecision(runId, lotId, factory), enabled: !!factory });
  if (q.isLoading) return <p className="text-sm text-muted">Checking future factory pressure…</p>;
  if (q.error) return <p className="rounded border border-warn/30 p-3 text-sm text-warn">Forecast warning unavailable: {q.error.message}. Purchase eligibility and hard capacity are still checked when saving.</p>;
  const d = q.data;
  if (!d) return null;
  const knownRisk = d.weeks.some(w => w.known_after_pct >= d.threshold_pct);
  const upperRisk = d.weeks.some(w => w.forecast_after_pct < d.threshold_pct && w.forecast_p90_pct >= d.threshold_pct);
  return <div className="rounded-xl border border-line p-3 text-sm">
    <p className="font-medium">If this lot is bought at {d.factory_id}</p>
    <p className="mt-1 text-muted">Committed load: {pct(d.committed_before_pct, 1)} → {pct(d.committed_after_pct, 1)} in its busiest production week.</p>
    {d.hard_capacity_blocked ? <p className="mt-2 text-bad">This assignment exceeds the hard capacity limit. Choose another feasible option; approval cannot override it.</p>
      : d.forecast_warning ? <p className="mt-2 text-warn">Forecast demand raises projected load above {d.threshold_pct}% during this lot’s production. Consider another certified factory or review the affected weeks before approving.</p>
      : knownRisk ? <p className="mt-2 text-warn">Known open demand already projects load above {d.threshold_pct}%. It is not yet all committed; review the competing demand before approving.</p>
      : upperRisk ? <p className="mt-2 text-warn">The central estimate stays below {d.threshold_pct}%, but the higher-demand scenario crosses it. Review the buffer before approving.</p>
      : <p className="mt-2 text-muted">No additional forecast threshold warning for this proposal. This is not a guarantee of available future capacity.</p>}
    <div className="mt-2 overflow-x-auto"><table className="w-full text-xs">
      <thead><tr className="text-left text-faint"><th>Production week</th><th>Committed</th><th>With known open</th><th>With forecast</th></tr></thead>
      <tbody>{d.weeks.map(w => <tr key={w.week} className="border-t border-line"><td className="py-1">{date(w.week)}</td><td>{pct(w.committed_after_pct, 0)}</td><td>{pct(w.known_after_pct, 0)}</td><td>{pct(w.forecast_after_pct, 0)}</td></tr>)}</tbody>
    </table></div>
    <p className="mt-2 text-xs text-faint">Includes this proposal once. Known-open and forecast demand are advisory pressure, not reserved capacity. Forecast warnings do not block an otherwise valid purchase. Model: {d.model}.</p>
  </div>;
}
