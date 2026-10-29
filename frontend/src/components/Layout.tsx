import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3, TrendingUp, CircleDollarSign, CalendarClock, Globe2, ChevronLeft, ChevronRight, ClipboardCheck, Download, FlaskConical, Layers, ListChecks,
  Monitor, Moon, RotateCcw, Search, ShoppingCart, Sparkles, Sun,
} from "lucide-react";
import { api } from "../api/client";
import { useRun } from "../lib/run";
import { useTheme, type ThemeChoice } from "../lib/theme";
import { date, shortDate } from "../lib/format";
import { CommandPalette } from "./CommandPalette";
import { cx } from "./ui";

const nav = [
  { to: "/", label: "Buy plan", icon: ListChecks, end: true },
  { to: "/what-if", label: "Test a change", icon: FlaskConical },
  { to: "/pull-forward", label: "Pull-forward", icon: Layers },
  { to: "/capacity", label: "Capacity", icon: BarChart3 },
  { to: "/forecast", label: "Forecast", icon: TrendingUp },
  { to: "/network", label: "Network", icon: Globe2 },
  { to: "/impact", label: "Delivery impact", icon: CircleDollarSign },
  { to: "/export", label: "Export", icon: Download },
  { to: "/checks", label: "Data & checks", icon: ClipboardCheck },
];
const pages = [...nav.map(({ to, label }) => ({ to, label })), { to: "/planned", label: "Planned capabilities" }];
const hints: Record<string, string> = {
  "/": "what to buy, from which factory, and why",
  "/what-if": "test a hold, delay or factory switch on a copy",
  "/pull-forward": "move demand out of overloaded windows",
  "/capacity": "weekly factory load from our assignments",
  "/network": "which factory ships where this week",
  "/forecast": "demand that has not arrived yet, and the load it will bring",
  "/impact": "who receives late or undelivered demand, and what it is worth",
  "/export": "fact_buy_plan_suggestions",
  "/checks": "validation, settings and data findings",
  "/planned": "what comes next",
};
const icons: Record<string, typeof ListChecks> = Object.fromEntries([...nav.map((n) => [n.to, n.icon]), ["/planned", Sparkles]]);

function NavItem({ to, label, icon: Icon, end }: { to: string; label: string; icon: typeof ListChecks; end?: boolean }) {
  return (
    <NavLink to={to} end={end}
      className={({ isActive }) => cx("flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition",
        isActive ? "bg-sidebar font-medium text-ink" : "text-muted hover:bg-sidebar/60 hover:text-ink")}>
      {({ isActive }) => (<><Icon size={15} className={isActive ? "text-accent" : "text-faint"} /> {label}</>)}
    </NavLink>
  );
}

function ThemeToggle() {
  const { choice, setChoice } = useTheme();
  const opts: { v: ThemeChoice; icon: typeof Sun; label: string }[] = [
    { v: "light", icon: Sun, label: "Light" }, { v: "system", icon: Monitor, label: "System" }, { v: "dark", icon: Moon, label: "Dark" },
  ];
  return (
    <div className="flex rounded-lg border border-line bg-panel p-0.5" role="radiogroup" aria-label="Theme">
      {opts.map(({ v, icon: Icon, label }) => (
        <button key={v} role="radio" aria-checked={choice === v} title={label} onClick={() => setChoice(v)}
          className={cx("grid h-6 w-6 place-items-center rounded-md transition", choice === v ? "bg-sidebar text-ink" : "text-faint hover:text-ink")}>
          <Icon size={14} />
        </button>
      ))}
    </div>
  );
}

export function Layout() {
  const { runs, run, runId, setRunId } = useRun();
  const qc = useQueryClient();
  const location = useLocation();
  const [palette, setPalette] = useState(false);
  const { data: plan } = useQuery({ queryKey: ["plan", runId], queryFn: () => api.plan(runId) });
  const revert = useMutation({
    mutationFn: () => api.revertWeek(runId),
    onSuccess: () => qc.invalidateQueries(),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const idx = runs.findIndex((r) => r.run_id === runId);
  const step = (d: number) => { const r = runs[idx + d]; if (r) setRunId(r.run_id); };
  const nextBuying = runs.slice(idx + 1).find((r) => r.is_buying_run);
  const current = pages.find((p) => (p.to === "/" ? location.pathname === "/" : location.pathname.startsWith(p.to)));
  const page = current?.label ?? "";
  const pageHint = current ? hints[current.to] : "";
  const PageIcon = current ? icons[current.to] : undefined;

  return (
    <div className="flex h-full">
      {/* ---------------- sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-canvas md:flex">
        <div className="flex items-center gap-2 px-4 pb-4 pt-4">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-[#04110e]"><ShoppingCart size={14} strokeWidth={2.5} /></div>
          <span className="text-[15px] font-semibold tracking-[-0.02em]">ACME<span className="text-faint">/</span>buy</span>
        </div>

        <div className="px-3">
          <div className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-[13px]">
            <span className="grid h-5 w-5 place-items-center rounded bg-sidebar font-mono text-[10px] text-muted">TV</span>
            <span className="flex-1 truncate">Team Vantage</span>
            <span className="rounded border border-line px-1 font-mono text-[10px] text-faint">FW25</span>
          </div>
          <button onClick={() => setPalette(true)}
            className="mt-2 flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-muted hover:bg-sidebar hover:text-ink">
            <Search size={15} className="text-faint" /> Search
            <kbd className="ml-auto rounded border border-line px-1 font-mono text-[10px] text-faint">⌘K</kbd>
          </button>
        </div>

        <nav className="mt-3 flex-1 space-y-0.5 px-3">
          <div className="px-2.5 pb-1 pt-2 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Plan</div>
          {nav.slice(0, 2).map((n) => <NavItem key={n.to} {...n} />)}
          <div className="px-2.5 pb-1 pt-4 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Capacity</div>
          {nav.slice(2, 7).map((n) => <NavItem key={n.to} {...n} />)}
          <div className="px-2.5 pb-1 pt-4 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Deliver</div>
          {nav.slice(7).map((n) => <NavItem key={n.to} {...n} />)}
          <div className="px-2.5 pb-1 pt-4 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Labs</div>
          <NavLink to="/planned"
            className={({ isActive }) => cx("flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition",
              isActive ? "bg-sidebar font-medium text-ink" : "text-muted hover:bg-sidebar/60 hover:text-ink")}>
            <Sparkles size={15} className="text-faint" /> Planned capabilities
            <span className="ml-auto rounded bg-manual-soft px-1.5 font-mono text-[10px] text-manual">soon</span>
          </NavLink>
        </nav>

        {plan && plan.manual_changes > 0 && (
          <div className="mx-3 mb-2 rounded-xl border border-manual/25 bg-manual-soft p-3 text-xs">
            <div className="font-medium text-manual">{plan.manual_changes} manual change{plan.manual_changes > 1 ? "s" : ""} this week</div>
            <button className="mt-1.5 inline-flex items-center gap-1.5 text-muted hover:text-ink" onClick={() => revert.mutate()} disabled={revert.isPending}>
              <RotateCcw size={12} /> Revert to automatic plan
            </button>
          </div>
        )}
        {run && (
          <div className="mx-3 mb-3 rounded-xl border border-line p-3">
            <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
              <span className="flex items-center gap-1.5"><CalendarClock size={12} /> {run.is_buying_run ? "Buying run" : "Draft week"}</span>
              {plan && <span>{plan.buying_window.replace("WIN-", "")}</span>}
            </div>
            <dl className="space-y-1 text-xs">
              {[
                ["Freeze", run.mrp_freeze_datetime_utc],
                ["Go / No-Go", run.go_nogo_date],
                ["PO execution", run.po_execution_date],
                ["Factory confirms", run.factory_confirm_deadline],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <dt className="text-muted">{k}</dt>
                  <dd className="font-mono text-[11px] text-ink">{shortDate(v)}</dd>
                </div>
              ))}
            </dl>
            {nextBuying && (
              <button onClick={() => setRunId(nextBuying.run_id)}
                className="mt-2.5 w-full rounded-lg border border-line py-1 text-xs text-muted hover:border-accent/40 hover:text-accent">
                Next buying run · {nextBuying.run_id.replace("MRP-", "")} →
              </button>
            )}
          </div>
        )}
      </aside>

      {/* ---------------- main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-canvas/85 px-6 backdrop-blur-xl">
          <div className="flex min-w-0 items-center gap-2 text-[13px]">
            {PageIcon && <PageIcon size={15} className="text-faint" />}
            <span className="truncate font-medium">{page}</span>
            <span className="hidden truncate text-faint lg:inline">· {pageHint}</span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center rounded-lg border border-line bg-panel">
              <button aria-label="Previous week" disabled={idx <= 0} onClick={() => step(-1)}
                className="grid h-8 w-7 place-items-center text-muted hover:text-ink disabled:opacity-30"><ChevronLeft size={15} /></button>
              <label className="sr-only" htmlFor="run">MRP run</label>
              <select id="run" value={runId} onChange={(e) => setRunId(e.target.value)}
                className="h-8 max-w-[240px] cursor-pointer border-x border-line bg-transparent px-2 font-mono text-xs outline-none">
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.is_buying_run ? "● " : "○ "}{r.run_id} · {date(r.mrp_freeze_datetime_utc)}
                  </option>
                ))}
              </select>
              <button aria-label="Next week" disabled={idx >= runs.length - 1} onClick={() => step(1)}
                className="grid h-8 w-7 place-items-center text-muted hover:text-ink disabled:opacity-30"><ChevronRight size={15} /></button>
            </div>
            {plan && (
              plan.is_buying_run
                ? <span className="hidden items-center gap-1.5 rounded-lg border border-good/25 bg-good-soft px-2.5 py-1.5 font-mono text-[11px] text-good sm:inline-flex">
                    <i className="h-1.5 w-1.5 animate-pulse rounded-full bg-good shadow-[0_0_8px_var(--color-good)]" /> BUYING · {plan.buying_window.replace("WIN-", "")}</span>
                : <button onClick={() => plan.buying_run_id && setRunId(plan.buying_run_id)} title="Open the buying run for this window"
                    className="hidden items-center gap-1.5 rounded-lg border border-info/25 bg-info-soft px-2.5 py-1.5 font-mono text-[11px] text-info hover:brightness-110 sm:inline-flex">
                    <i className="h-1.5 w-1.5 rounded-full bg-info" /> DRAFT · {plan.buying_window.replace("WIN-", "")}</button>
            )}
            <ThemeToggle />
          </div>
        </header>

        <main className="scroll-thin relative flex-1 overflow-y-auto">
          <div className="page-glow pointer-events-none absolute inset-x-0 top-0 h-72" />
          <div key={location.pathname + runId} className="relative mx-auto max-w-[1440px] px-6 py-7 animate-fade-up md:px-8">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} pages={pages} />
    </div>
  );
}
