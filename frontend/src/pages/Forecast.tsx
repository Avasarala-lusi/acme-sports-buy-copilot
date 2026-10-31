import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertTriangle, Gauge, Target, TrendingUp } from "lucide-react";
import { api } from "../api/client";
import { Badge, Card, ErrorBox, Kpi, Loading, PageHeader, SectionTitle, cx } from "../components/ui";
import { useRun } from "../lib/run";
import { useToken } from "../lib/theme";
import { int, pct } from "../lib/format";

const FACTORIES = ["ACME-VN01", "ACME-BD02", "ACME-ID03", "ACME-CN04", "ACME-TR05", "ACME-IN06"];
const MODEL_NAMES: Record<string, string> = {
  stage_seasonal: "Stage-seasonal", extra_trees: "Extra Trees (challenger)", gradient_boosting: "Gradient boosting",
  random_forest: "Random Forest", xgboost: "XGBoost", sarimax: "SARIMAX (stage regressors)",
  seasonal_naive: "Same week last year", moving_average: "4-week moving average",
};
const STAGE_NAMES: Record<string, string> = { "0-1": "FW V1", "0-2": "FW V2", "0-3": "FW V3", "1-1": "SS V1", "1-2": "SS V2", "1-3": "SS V3" };
const pval = (p: number) => (p < 1e-10 ? "p < 10⁻¹⁰" : `p = ${p.toExponential(1)}`);
const short = (f: string) => f.replace("ACME-", "");
const day = (iso: string) => iso.slice(0, 10);

export function Forecast() {
  const { runId } = useRun();
  const [model, setModel] = useState("");
  const [factory, setFactory] = useState<string>("ALL");
  const fc = useQuery({ queryKey: ["forecast", runId, model], queryFn: () => api.forecast(runId, model || undefined) });
  const bt = useQuery({ queryKey: ["backtest"], queryFn: api.backtest, staleTime: Infinity });
  const seas = useQuery({ queryKey: ["seasonality"], queryFn: api.seasonality, staleTime: Infinity });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: Infinity });
  const s1 = useToken("--color-series-1"), s2 = useToken("--color-series-2"), s3 = useToken("--color-series-3");
  const grid = useToken("--color-grid"), axis = useToken("--color-axis"), ink = useToken("--color-ink");
  const panel = useToken("--color-panel"), line = useToken("--color-line");
  const warn = useToken("--color-status-warning"), critical = useToken("--color-status-critical");
  const threshold = settings.data?.thresholds.backup_threshold_pct ?? 85;
  const limit = settings.data?.thresholds.hard_limit_pct ?? 100;

  const intake = useMemo(() => {
    if (!fc.data) return [];
    const pick = (f: string) => factory === "ALL" || f === factory;
    const rows = new Map<string, Record<string, number | string | null>>();
    for (const h of fc.data.history.filter((h) => pick(h.factory) && h.week > fc.data!.origin_week - 30)) {
      const r = rows.get(day(h.date)) ?? { date: day(h.date), history: 0 };
      r.history = (r.history as number) + h.units;
      rows.set(day(h.date), r);
    }
    for (const i of fc.data.intake.filter((i) => pick(i.factory))) {
      const r = rows.get(day(i.date)) ?? { date: day(i.date), p50: 0, lo: 0, hi: 0, actual: null };
      r.p50 = ((r.p50 as number) ?? 0) + i.p50;
      r.lo = ((r.lo as number) ?? 0) + i.p10;
      r.hi = ((r.hi as number) ?? 0) + i.p90;
      if (i.actual != null) r.actual = ((r.actual as number) ?? 0) + i.actual;
      rows.set(day(i.date), r);
    }
    return [...rows.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)))
      .map((r) => ({ ...r, band: r.lo != null && r.hi != null ? [r.lo, r.hi] : undefined }));
  }, [fc.data, factory]);

  const loadRows = useMemo(() => (fc.data?.load ?? [])
    .filter((l) => l.factory_id === (factory === "ALL" ? "ACME-CN04" : factory))
    .map((l) => ({
      week: day(l.week),
      committed: (l.committed_units / l.capacity) * 100,
      known: (l.known_open_units / l.capacity) * 100,
      forecast: (l.forecast_units / l.capacity) * 100,
      p90: l.forecast_p90_pct,
    })), [fc.data, factory]);

  if (fc.isLoading) return <Loading label="Forecasting demand that has not arrived yet…" />;
  if (fc.error) return <ErrorBox error={fc.error} />;
  const f = fc.data!;
  const next = f.intake.reduce((t, i) => ({ p10: t.p10 + i.p10, p50: t.p50 + i.p50, p90: t.p90 + i.p90 }), { p10: 0, p50: 0, p90: 0 });
  const warnings = f.windows.filter((w) => w.early_warning);
  const windows = [...new Set(f.windows.map((w) => w.window))];
  const overall = bt.data?.overall ?? [];
  const best = overall.find(x => x.model === bt.data?.selected_model);
  const baseline = overall.find((o) => o.model === "seasonal_naive");
  const loadFactory = factory === "ALL" ? "ACME-CN04" : factory;
  const tooltip = { contentStyle: { background: panel, border: `1px solid ${line}`, borderRadius: 12, fontSize: 12, color: ink }, labelStyle: { color: ink, fontWeight: 600 } };

  return (
    <>
      <PageHeader eyebrow={`Forecast · ${MODEL_NAMES[f.model] ?? f.model} model · weeks up to ${f.origin_week}`} title="Demand & load forecast"
        subtitle={`Estimates demand for the next ${f.horizon_weeks} weeks using history available at ${runId}, then projects factory pressure over four buying windows (about eight weeks). Forecast demand is not a purchase or a capacity reservation. Saved planner decisions are included.`} />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <label>Forecast method <select className="ml-2 rounded border border-line bg-panel p-2" value={model || f.model} onChange={e => setModel(e.target.value)}>
          {Object.entries(MODEL_NAMES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <span className="text-xs text-faint">Method preview only. Purchase-decision warnings use the configured default method.</span>
      </div>

      {f.stage_coverage_pct < 100 && (
        <div className="mb-4 flex items-start gap-2 rounded-2xl border border-warn/25 bg-warn-soft p-3 text-sm text-warn">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>
            Only {f.stage_coverage_pct.toFixed(0)}% of these forecast weeks have an earlier season of the same buying stage in the data
            up to {runId}. For the rest the forecast falls back to the recent level, so future peaks may be missed.
            More history may help, but reliability must be judged from historical tests rather than a fixed week number.
          </span>
        </div>
      )}
      {f.intake.some(x => x.fallback_reason) && <p className="mb-4 rounded border border-warn/30 p-3 text-sm text-warn">Some predictions use a simpler fallback: {[...new Set(f.intake.map(x => x.fallback_reason).filter(Boolean))].join("; ")}</p>}
      {f.intake.some(x => x.fit_warning) && <details className="mb-4 text-sm text-warn"><summary>Model fit warnings: interpret this preview cautiously</summary><p>{[...new Set(f.intake.map(x => x.fit_warning).filter(Boolean))].join("; ")}</p></details>}
      {f.intake.some(x => x.calibration_samples < 30) && <p className="mb-4 text-sm text-muted">Some uncertainty ranges use an assumed 60–140% span because there are too few past forecast errors. They are not validated probability guarantees.</p>}
      <div className="mb-4 flex flex-wrap gap-1.5">
        {["ALL", ...FACTORIES].map((x) => (
          <button key={x} onClick={() => setFactory(x)}
            className={cx("rounded-lg border px-2.5 py-1 font-mono text-xs transition",
              factory === x ? "border-line-strong bg-sidebar text-ink" : "border-transparent text-muted hover:text-ink")}>
            {x === "ALL" ? "Whole network" : short(x)}
          </button>
        ))}
      </div>

      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={TrendingUp} label={`Demand still to arrive · next ${f.horizon_weeks} weeks`} value={int(next.p50)}
          sub={`Summed lower–upper estimates: ${int(next.p10)} – ${int(next.p90)} units`} />
        <Kpi icon={AlertTriangle} label="Early warnings" value={String(warnings.length)}
          sub="Windows fine on known demand that cross 85% with the forecast" />
        <Kpi icon={Target} label="Selection-period winner · WAPE" value={best ? pct(best.wape_pct, 1) : "…"}
          sub={baseline && best ? `${MODEL_NAMES[best.model]} · same week last year ${pct(baseline.wape_pct, 1)}` : "walk-forward, only past weeks"} />
        <Kpi icon={Gauge} label="Final-period range coverage" value={bt.data?.coverage_pct != null ? pct(bt.data.coverage_pct, 1) : "…"}
          sub="Configured default: observed coverage of the nominal 80% range" />
      </div>

      <div className="mb-5 grid gap-4 xl:grid-cols-2">
        <Card className="p-5">
          <SectionTitle hint={factory === "ALL" ? "all factories" : short(factory)}>Weekly new demand</SectionTitle>
          <div className="h-[300px]">
            <ResponsiveContainer>
              <ComposedChart data={intake} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={grid} vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: axis }} tickLine={false} axisLine={{ stroke: grid }} tickFormatter={(d: string) => d.slice(5)} minTickGap={28} />
                <YAxis tick={{ fontSize: 11, fill: axis }} tickLine={false} axisLine={false} width={56} tickFormatter={(v: number) => `${Math.round(v / 1000)}k`} />
                <Tooltip {...tooltip} formatter={(v: number | number[], n: string) => [Array.isArray(v) ? `${int(v[0])} – ${int(v[1])}` : int(v), n]} />
                <Legend wrapperStyle={{ fontSize: 12, color: ink }} />
                <Area dataKey="band" name={factory === "ALL" ? "Summed lower–upper estimates" : "Nominal P10–P90 range"} stroke="none" fill={s1} fillOpacity={0.15} isAnimationActive={false} />
                <Line dataKey="history" name="Received" stroke={ink} strokeOpacity={0.75} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line dataKey="p50" name="Forecast" stroke={s1} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-faint">Future actual demand is hidden in this operational view. Forecasts use only earlier demand and the assumed-known buying-stage calendar.</p>
        </Card>

        <Card className="p-5">
          <SectionTitle hint={`${short(loadFactory)}${factory === "ALL" ? " (pick a factory above)" : ""}`}>Load over the next four windows</SectionTitle>
          <div className="h-[300px]">
            <ResponsiveContainer>
              <ComposedChart data={loadRows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={grid} vertical={false} />
                <XAxis dataKey="week" tick={{ fontSize: 11, fill: axis }} tickLine={false} axisLine={{ stroke: grid }} tickFormatter={(d: string) => d.slice(5)} minTickGap={28} />
                <YAxis tick={{ fontSize: 11, fill: axis }} tickLine={false} axisLine={false} unit="%" width={48} />
                <Tooltip {...tooltip} formatter={(v: number, n: string) => [`${v.toFixed(0)}%`, n]} />
                <Legend wrapperStyle={{ fontSize: 12, color: ink }} />
                <Area dataKey="committed" name="Committed" stackId="l" stroke={s1} fill={s1} fillOpacity={0.55} isAnimationActive={false} />
                <Area dataKey="known" name="Known open demand" stackId="l" stroke={s2} fill={s2} fillOpacity={0.45} isAnimationActive={false} />
                <Area dataKey="forecast" name="Forecast demand" stackId="l" stroke={s3} fill={s3} fillOpacity={0.35} isAnimationActive={false} />
                <Line dataKey="p90" name="Upper demand scenario" stroke={s3} strokeDasharray="3 3" dot={false} isAnimationActive={false} />
                <ReferenceLine y={threshold} stroke={warn} strokeDasharray="5 4" label={{ value: `${threshold}%`, fontSize: 11, fill: axis, position: "insideTopRight" }} />
                <ReferenceLine y={limit} stroke={critical} strokeDasharray="2 3" label={{ value: `${limit}%`, fontSize: 11, fill: axis, position: "insideTopLeft" }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-faint">Saved commitments plus known-open and forecast pressure. Open/forecast demand is projected at primary factories before routing; values above 100% are warnings, not committed overloads.</p>
          <p className="mt-1 text-xs text-faint">Summed lower/upper estimates are scenarios, not calibrated probabilities for total network load. Final-period range coverage is measured per factory and forecast week.</p>
        </Card>
      </div>

      {seas.data && (
        <Card className="mb-5 p-5">
          <SectionTitle hint={`${seas.data.weeks} weeks of weekly demand, whole network`}>Is demand seasonal? The evidence</SectionTitle>
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-line p-3">
              <div className="text-xs text-muted">Autocorrelation at 52 weeks</div>
              <div className="font-num mt-1 text-lg">{seas.data.acf_lag52.toFixed(2)} <span className="text-xs text-faint">vs bound {seas.data.acf_bound_95.toFixed(2)}</span></div>
              <div className="text-[11px] text-faint">{seas.data.acf_lag52_significant ? "Suggests annual repetition; limited evidence" : "No clear annual signal"}</div>
            </div>
            <div className="rounded-xl border border-line p-3">
              <div className="text-xs text-muted">Demand differs by buying stage (Kruskal-Wallis)</div>
              <div className="font-num mt-1 text-lg">H = {seas.data.kruskal_stage_h.toFixed(0)} <span className="text-xs text-faint">{pval(seas.data.kruskal_stage_p)}</span></div>
              <div className="text-[11px] text-faint">by calendar month: H = {seas.data.kruskal_month_h.toFixed(0)}, {pval(seas.data.kruskal_month_p)}</div>
            </div>
            <div className="rounded-xl border border-line p-3">
              <div className="text-xs text-muted">Average weekly demand by stage ({seas.data.stage_ratio_max_min.toFixed(0)}× swing)</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {Object.entries(seas.data.stage_mean_units).map(([k, v]) => (
                  <Badge key={k}>{STAGE_NAMES[k] ?? k} · {Math.round(v / 1000)}k</Badge>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card className="overflow-hidden">
          <div className="border-b border-line px-5 py-3"><SectionTitle hint="busiest week in each window">Known vs forecast load by window</SectionTitle></div>
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-faint">
                <tr><th className="px-4 py-2.5 text-left font-normal">Factory</th>
                  {windows.map((w) => <th key={w} className="px-3 py-2.5 text-center font-normal">{w.replace("WIN-", "")}</th>)}</tr>
              </thead>
              <tbody>
                {FACTORIES.map((fac) => (
                  <tr key={fac} className="border-t border-line">
                    <td className="px-4 py-2.5 font-mono text-xs">{short(fac)}</td>
                    {windows.map((w) => {
                      const c = f.windows.find((x) => x.window === w && x.factory_id === fac);
                      if (!c) return <td key={w} />;
                      return (
                        <td key={w} className="px-3 py-2 text-center">
                          <div className="font-num text-[13px]">
                            <span className="text-muted">{c.known_peak_pct.toFixed(0)}</span>
                            <span className="text-faint"> → </span>
                            <span className={c.forecast_peak_pct > limit ? "text-bad" : c.forecast_peak_pct >= threshold ? "text-warn" : "text-good"}>{c.forecast_peak_pct.toFixed(0)}%</span>
                          </div>
                          {c.early_warning && <Badge tone="warn">early warning</Badge>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-line px-5 py-2.5 text-xs text-faint">Known demand only → with the forecast. An early warning means the window looks fine today but will cross {threshold}%.</div>
        </Card>

        <Card className="overflow-hidden">
          <div className="border-b border-line px-5 py-3">
            <SectionTitle hint={bt.data ? `${bt.data.origins} forecast dates, ${bt.data.horizon_weeks} weeks ahead` : "running…"}>Model comparison (walk-forward)</SectionTitle>
          </div>
          {bt.isLoading ? <div className="p-5"><Loading label="Running the backtest (first time only)…" /></div> : (
            <table className="w-full text-sm">
              <thead className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-faint">
                <tr><th className="px-4 py-2.5 text-left font-normal">Model</th>
                  {["1-4 weeks", "5-8 weeks", `9-${bt.data?.horizon_weeks ?? 17} weeks`].map((b) => <th key={b} className="px-3 py-2.5 text-right font-normal">{b}</th>)}
                  <th className="px-4 py-2.5 text-right font-normal">All</th><th className="px-3 py-2.5 text-right font-normal">Fallback</th></tr>
              </thead>
              <tbody>
                {overall.map((o) => (
                  <tr key={o.model} className={cx("border-t border-line", o.model === bt.data?.default_model && "bg-accent-soft")}>
                    <td className="px-4 py-2">{MODEL_NAMES[o.model] ?? o.model}{o.model === bt.data?.default_model && <Badge tone="accent">in use</Badge>}</td>
                    {["1-4 weeks", "5-8 weeks", `9-${bt.data?.horizon_weeks ?? 17} weeks`].map((b) => {
                      const v = bt.data?.by_horizon.find((x) => x.model === o.model && x.band === b);
                      return <td key={b} className="font-num px-3 py-2 text-right text-muted">{v ? `${v.wape_pct.toFixed(1)}%` : "—"}</td>;
                    })}
                    <td className="font-num px-4 py-2 text-right">{o.wape_pct.toFixed(1)}%</td>
                    <td className="font-num px-3 py-2 text-right">{pct(o.fallback_pct, 0)}{!o.complete && " incomplete"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="border-t border-line px-5 py-2.5 text-xs text-faint">
            WAPE = absolute error ÷ actual demand, per factory and week (lower is better). The ML models learn a correction to the stage
            baseline; SARIMAX uses the stages as regressors (a 52-week seasonal ARIMA term needs two full years before each forecast).
            The selection winner is a recommendation, not an automatic configuration change. Fallback rates are shown below. About 100 weeks provide fewer than two full annual cycles; these research results use the historical archive, not future information in the selected-run forecast.
          </div>
          {bt.error && <div className="p-4"><ErrorBox error={bt.error} /></div>}
          {seas.error && <div className="p-4 text-sm text-warn">Seasonality assessment unavailable: {seas.error.message}</div>}
          {bt.data && <div className="border-t border-line p-4 text-sm">
            <p className="mb-2">Final evaluation: weeks {bt.data.holdout_first_week}–{bt.data.holdout_last_week}, excluded from selection. Lower WAPE is better; a single final period remains limited evidence.</p>
            <table className="w-full text-xs"><thead><tr className="text-left text-faint"><th>Model</th><th>Final WAPE</th><th>Fallback rows</th></tr></thead><tbody>
              {bt.data.holdout_overall.map(row => <tr key={row.model} className="border-t border-line"><td className="py-1">{MODEL_NAMES[row.model]}{!row.complete && " (incomplete)"}</td><td>{pct(row.wape_pct, 1)}</td><td>{pct(row.fallback_pct, 0)}</td></tr>)}
            </tbody></table>
            {bt.data.failures.length > 0 && <p className="mt-2 text-warn">Some model fits could not run: {bt.data.failures.map(x => `${x.model}: ${x.error}`).join("; ")}</p>}
          </div>}
        </Card>
      </div>
    </>
  );
}
