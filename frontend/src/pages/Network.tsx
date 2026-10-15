import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Globe, { type GlobeMethods } from "react-globe.gl";
import { Globe2, Pause, Play } from "lucide-react";
import { api } from "../api/client";
import type { Route } from "../api/types";
import { Badge, ErrorBox, Loading, PageHeader, cx } from "../components/ui";
import { useRun } from "../lib/run";
import { useToken } from "../lib/theme";
import { int, load, moneyShort, pct } from "../lib/format";

// Representative hub positions: each factory's country manufacturing hub and each market's main gateway city.
const FACTORY_HUB: Record<string, { lat: number; lng: number; city: string }> = {
  "ACME-VN01": { lat: 10.82, lng: 106.63, city: "Ho Chi Minh City, VN" },
  "ACME-BD02": { lat: 23.81, lng: 90.41, city: "Dhaka, BD" },
  "ACME-ID03": { lat: -6.2, lng: 106.85, city: "Jakarta, ID" },
  "ACME-CN04": { lat: 23.02, lng: 113.75, city: "Dongguan, CN" },
  "ACME-TR05": { lat: 41.01, lng: 28.98, city: "Istanbul, TR" },
  "ACME-IN06": { lat: 11.1, lng: 77.34, city: "Tiruppur, IN" },
};
const MARKET_HUB: Record<string, { lat: number; lng: number; name: string }> = {
  US: { lat: 34.05, lng: -118.24, name: "United States" },
  MX: { lat: 19.43, lng: -99.13, name: "Mexico" },
  BR: { lat: -23.55, lng: -46.63, name: "Brazil" },
  CO: { lat: 4.71, lng: -74.07, name: "Colombia" },
  CL: { lat: -33.45, lng: -70.67, name: "Chile" },
  PE: { lat: -12.05, lng: -77.04, name: "Peru" },
  AR: { lat: -34.6, lng: -58.38, name: "Argentina" },
};
// Color follows the factory (same slots as the capacity chart).
const FACTORY_ORDER = ["ACME-VN01", "ACME-BD02", "ACME-ID03", "ACME-CN04", "ACME-TR05", "ACME-IN06"];

type Filter = "all" | "backup" | "review";
type Arc = Route & { startLat: number; startLng: number; endLat: number; endLng: number; kind: "bought" | "review" };

const short = (f: string) => f.replace("ACME-", "");

export function Network() {
  const { runId } = useRun();
  const net = useQuery({ queryKey: ["network", runId], queryFn: () => api.network(runId) });
  const series = [1, 2, 3, 4, 5, 6].map((n) => useToken(`--color-series-${n}`)); // eslint-disable-line react-hooks/rules-of-hooks
  const critical = useToken("--color-status-critical");
  const globe = useRef<GlobeMethods | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 620 });
  const [filter, setFilter] = useState<Filter>("all");
  const [factory, setFactory] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [spin, setSpin] = useState(true);

  const color = (f: string) => series[FACTORY_ORDER.indexOf(f)] || "#888";

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const g = globe.current;
    if (!g) return;
    const c = g.controls();
    c.autoRotate = spin;
    c.autoRotateSpeed = 0.45;
    c.enableZoom = true;
  }, [spin, net.data]);

  const routes = useMemo(() => {
    const all = net.data?.routes ?? [];
    return all.filter((r) =>
      (!factory || r.factory_id === factory) &&
      (filter === "all" || (filter === "backup" ? r.backup_units > 0 : r.review_units > 0)));
  }, [net.data, filter, factory]);

  const arcs = useMemo<Arc[]>(() => routes.flatMap((r) => {
    const a = FACTORY_HUB[r.factory_id], b = MARKET_HUB[r.market];
    if (!a || !b) return [];
    const base = { ...r, startLat: a.lat, startLng: a.lng, endLat: b.lat, endLng: b.lng };
    const out: Arc[] = [];
    if (r.bought_units > 0 && filter !== "review") out.push({ ...base, kind: "bought" });
    if (r.review_units > 0 && filter !== "backup") out.push({ ...base, kind: "review" });
    return out;
  }), [routes, filter]);

  const maxUnits = Math.max(1, ...arcs.map((a) => (a.kind === "review" ? a.review_units : a.bought_units)));
  const key = (r: Route) => `${r.factory_id}>${r.market}`;

  const focus = (r: Route) => {
    setActive(key(r));
    setSpin(false);
    const a = FACTORY_HUB[r.factory_id], b = MARKET_HUB[r.market];
    // look at the start of the route; the arc runs over the horizon towards the market
    // centre the camera on the great-circle midpoint so the whole arc is in view
    const rad = Math.PI / 180, v = (p: { lat: number; lng: number }) =>
      [Math.cos(p.lat * rad) * Math.cos(p.lng * rad), Math.cos(p.lat * rad) * Math.sin(p.lng * rad), Math.sin(p.lat * rad)];
    const [x1, y1, z1] = v(a), [x2, y2, z2] = v(b);
    const [x, y, z] = [x1 + x2, y1 + y2, z1 + z2];
    const lat = Math.atan2(z, Math.hypot(x, y)) / rad, lng = Math.atan2(y, x) / rad;
    const span = Math.acos(Math.max(-1, Math.min(1, x1 * x2 + y1 * y2 + z1 * z2))) / rad;
    globe.current?.pointOfView({ lat, lng, altitude: span > 120 ? 3.2 : 2.3 }, 1200);
  };

  if (net.isLoading) return <Loading label="Loading the network…" />;
  if (net.error) return <ErrorBox error={net.error} />;
  const n = net.data!;
  const totals = n.routes.reduce((t, r) => ({
    units: t.units + r.bought_units, backup: t.backup + r.backup_units, review: t.review + r.review_units,
  }), { units: 0, backup: 0, review: 0 });
  const factories = n.factories.map((f) => f.factory_id).sort((a, b) => FACTORY_ORDER.indexOf(a) - FACTORY_ORDER.indexOf(b));
  const markets = [...new Set(n.routes.map((r) => r.market))];

  return (
    <>
      <PageHeader eyebrow={`${runId} · factory → market`} title="Network"
        subtitle="Where this week's lots are made and where they ship. Arc width follows units; color follows the factory. Red arcs are lots waiting for planner review." />

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        {/* ---------------- globe */}
        <div className="relative overflow-hidden rounded-2xl border border-line bg-[#04050a]" style={{ minHeight: 620 }}>
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_50%_45%,rgba(45,212,180,0.10),transparent_70%)]" />
          <div ref={box} className="absolute inset-0">
            <Globe
              ref={globe}
              width={size.w}
              height={size.h}
              backgroundColor="rgba(0,0,0,0)"
              globeImageUrl={`${import.meta.env.BASE_URL}globe/earth-night.jpg`}
              bumpImageUrl={`${import.meta.env.BASE_URL}globe/earth-topology.png`}
              showAtmosphere
              atmosphereColor="#2dd4b4"
              atmosphereAltitude={0.18}
              arcsData={arcs}
              arcColor={(d: object) => {
                const a = d as Arc;
                const dim = active && key(a) !== active;
                const c = a.kind === "review" ? critical : color(a.factory_id);
                return dim ? ["rgba(255,255,255,0.04)", "rgba(255,255,255,0.04)"] : [`${c}ee`, `${c}33`];
              }}
              arcStroke={(d: object) => {
                const a = d as Arc;
                if (active && key(a) === active) return 1.8;
                return 0.15 + 1.1 * Math.sqrt((a.kind === "review" ? a.review_units : a.bought_units) / maxUnits);
              }}
              arcAltitude={(d: object) => (active && key(d as Arc) === active ? 0.45 : 0.22)}
              arcDashLength={(d: object) => ((d as Arc).kind === "review" ? 0.08 : 0.5)}
              arcDashGap={(d: object) => ((d as Arc).kind === "review" ? 0.06 : 0.12)}
              arcDashInitialGap={() => Math.random()}
              arcDashAnimateTime={(d: object) => ((d as Arc).kind === "review" ? 0 : 3200)}
              arcLabel={(d: object) => {
                const a = d as Arc;
                return `<div style="font:12px Geist Variable,system-ui;background:#0f0f12;border:1px solid #2c2c33;border-radius:10px;padding:8px 10px;color:#ececf1">
                  <b>${short(a.factory_id)} → ${MARKET_HUB[a.market]?.name ?? a.market}</b><br/>
                  ${a.kind === "review"
                    ? `<span style="color:${critical}">Needs review · ${int(a.review_units)} units</span>`
                    : `${int(a.bought_units)} units · ${moneyShort(a.cost_usd)}${a.backup_units ? ` · ${int(a.backup_units)} on backup` : ""}`}
                </div>`;
              }}
              onArcClick={(d: object) => focus(d as Arc)}
              pointsData={factories.map((f) => ({ id: f, ...FACTORY_HUB[f] }))}
              pointColor={(d: object) => color((d as { id: string }).id)}
              pointAltitude={0.02}
              pointRadius={0.55}
              labelsData={[
                ...factories.map((f) => ({ ...FACTORY_HUB[f], text: short(f), kind: "factory", id: f })),
                ...markets.map((m) => ({ ...MARKET_HUB[m], text: m, kind: "market", id: m })),
              ]}
              labelText={(d: object) => (d as { text: string }).text}
              labelSize={(d: object) => ((d as { kind: string }).kind === "factory" ? 1.15 : 1.0)}
              labelDotRadius={(d: object) => ((d as { kind: string }).kind === "factory" ? 0 : 0.35)}
              labelColor={(d: object) => ((d as { kind: string; id: string }).kind === "factory" ? color((d as { id: string }).id) : "rgba(236,236,241,0.9)")}
              labelResolution={3}
              labelAltitude={0.015}
              ringsData={markets.map((m) => MARKET_HUB[m])}
              ringColor={() => (t: number) => `rgba(45,212,180,${1 - t})`}
              ringMaxRadius={3.2}
              ringPropagationSpeed={1.6}
              ringRepeatPeriod={1400}
              onGlobeReady={() => globe.current?.pointOfView({ lat: 8, lng: 160, altitude: 1.9 }, 0)}
            />
          </div>

          {/* overlay: stats + controls */}
          <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-wrap items-start justify-between gap-3 p-4">
            <div className="pointer-events-auto grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 backdrop-blur-md">
              {[
                ["Shipping", int(totals.units), "units bought"],
                ["On a backup", int(totals.backup), "units rerouted"],
                ["For review", int(totals.review), "units, not bought"],
              ].map(([k, v, s]) => (
                <div key={k} className="bg-[#07080d]/80 px-4 py-2.5">
                  <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/50">{k}</div>
                  <div className="font-num text-lg text-white">{v}</div>
                  <div className="text-[10.5px] text-white/40">{s}</div>
                </div>
              ))}
            </div>
            <div className="pointer-events-auto flex gap-1 rounded-xl border border-white/10 bg-[#07080d]/80 p-1 backdrop-blur-md">
              {(["all", "backup", "review"] as Filter[]).map((f) => (
                <button key={f} onClick={() => { setFilter(f); setActive(null); }}
                  className={cx("rounded-lg px-3 py-1 text-xs font-medium capitalize transition",
                    filter === f ? "bg-white/10 text-white" : "text-white/50 hover:text-white")}>
                  {f === "all" ? "All routes" : f === "backup" ? "Backup" : "Review"}
                </button>
              ))}
              <button onClick={() => setSpin((v) => !v)} title={spin ? "Pause rotation" : "Rotate"}
                className="grid w-8 place-items-center rounded-lg text-white/60 hover:text-white">{spin ? <Pause size={13} /> : <Play size={13} />}</button>
            </div>
          </div>

          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap gap-1.5 p-4">
            {factories.map((f) => (
              <button key={f} onClick={() => { setFactory((x) => (x === f ? null : f)); setActive(null); }}
                className={cx("pointer-events-auto inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 font-mono text-[11px] backdrop-blur-md transition",
                  factory === f ? "border-white/30 bg-white/15 text-white" : "border-white/10 bg-[#07080d]/70 text-white/70 hover:text-white",
                  factory && factory !== f && "opacity-40")}>
                <i className="h-2 w-2 rounded-full" style={{ background: color(f), boxShadow: `0 0 8px ${color(f)}` }} />
                {short(f)} <span className="text-white/40">{FACTORY_HUB[f]?.city.split(",")[1]}</span>
              </button>
            ))}
            <span className="ml-auto self-center font-mono text-[10px] text-white/35">drag to rotate · scroll to zoom · positions are representative hubs</span>
          </div>
        </div>

        {/* ---------------- route list */}
        <div className="flex max-h-[620px] flex-col overflow-hidden rounded-2xl border border-line bg-panel">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <div className="flex items-center gap-2 text-[15px] font-semibold tracking-tight"><Globe2 size={15} className="text-accent" /> Routes</div>
            <span className="font-mono text-[11px] text-faint">{routes.length} shown</span>
          </div>
          <div className="scroll-thin flex-1 overflow-y-auto p-2">
            {routes.map((r) => {
              const on = active === key(r);
              const share = r.units / Math.max(1, ...routes.map((x) => x.units));
              return (
                <button key={key(r)} onClick={() => (on ? setActive(null) : focus(r))}
                  className={cx("mb-1 w-full rounded-xl border p-3 text-left transition",
                    on ? "border-accent/40 bg-accent-soft" : "border-transparent hover:border-line hover:bg-sidebar/60")}>
                  <div className="flex items-center gap-2 text-[13px]">
                    <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: color(r.factory_id), boxShadow: `0 0 8px ${color(r.factory_id)}` }} />
                    <span className="font-mono">{short(r.factory_id)}</span>
                    <span className="text-faint">→</span>
                    <span className="font-medium">{MARKET_HUB[r.market]?.name ?? r.market}</span>
                    <span className="font-num ml-auto text-ink">{int(r.units)}</span>
                  </div>
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-sidebar">
                    <div className="h-full rounded-full" style={{ width: `${share * 100}%`, background: color(r.factory_id) }} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                    <span className="font-mono">{r.lots} lots · {r.articles} articles · {moneyShort(r.cost_usd)}</span>
                    {r.backup_units > 0 && <Badge tone="info">{int(r.backup_units)} backup</Badge>}
                    {r.review_units > 0 && <Badge tone="bad">{int(r.review_units)} review</Badge>}
                    {r.late_lots > 0 && <Badge tone="warn">{r.late_lots} late</Badge>}
                    <span className="ml-auto font-mono text-faint" title="Busiest production week at the factory, with these lots">load {load(r.max_load_pct)}</span>
                  </div>
                  {on && (
                    <div className="mt-2 font-mono text-[11px] text-faint">
                      {FACTORY_HUB[r.factory_id]?.city} → {MARKET_HUB[r.market]?.name} · on time {pct((r.on_time_units / Math.max(1, r.bought_units)) * 100, 0)}
                    </div>
                  )}
                </button>
              );
            })}
            {routes.length === 0 && <div className="p-6 text-center text-sm text-muted">No routes match this filter</div>}
          </div>
        </div>
      </div>
    </>
  );
}
