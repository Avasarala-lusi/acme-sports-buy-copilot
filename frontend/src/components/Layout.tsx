import { NavLink, Outlet } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, CalendarClock, ClipboardCheck, Download, FlaskConical, Layers, ListChecks, RotateCcw, Sparkles } from "lucide-react";
import { api } from "../api/client";
import { useRun } from "../lib/run";
import { date, shortDate } from "../lib/format";
import { Button, cx } from "./ui";

const nav = [
  { to: "/", label: "Buy plan", icon: ListChecks, end: true },
  { to: "/what-if", label: "Test a change", icon: FlaskConical },
  { to: "/pull-forward", label: "Pull-forward", icon: Layers },
  { to: "/capacity", label: "Capacity", icon: BarChart3 },
  { to: "/export", label: "Export", icon: Download },
  { to: "/checks", label: "Data & checks", icon: ClipboardCheck },
];

export function Layout() {
  const { runs, run, runId, setRunId } = useRun();
  const qc = useQueryClient();
  const { data: plan } = useQuery({ queryKey: ["plan", runId], queryFn: () => api.plan(runId) });
  const revert = useMutation({
    mutationFn: () => api.revertWeek(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plan", runId] }),
  });

  return (
    <div className="flex h-full">
      <aside className="flex w-64 shrink-0 flex-col border-r border-line bg-sidebar">
        <div className="flex items-center gap-2 px-5 pb-4 pt-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-white">A</div>
          <div>
            <div className="text-sm font-semibold leading-tight">Acme Sports</div>
            <div className="text-xs text-muted">Buy Planner</div>
          </div>
        </div>

        <div className="px-4">
          <label className="text-xs font-medium text-muted" htmlFor="run">MRP run</label>
          <select id="run" value={runId} onChange={(e) => setRunId(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm outline-none focus:border-accent">
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id} · {date(r.mrp_freeze_datetime_utc)} · {r.season} {r.range_version}
              </option>
            ))}
          </select>
        </div>

        {run && (
          <div className="mx-4 mt-4 rounded-lg border border-line bg-panel p-3">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted">
              <CalendarClock size={14} /> Buy week
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
                  <dd className="font-medium">{shortDate(v)}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        <nav className="mt-4 flex-1 space-y-0.5 px-3">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
                isActive ? "bg-panel text-ink shadow-sm" : "text-muted hover:bg-panel/60 hover:text-ink")}>
              <Icon size={16} /> {label}
            </NavLink>
          ))}
          <div className="px-3 pb-1 pt-4 text-xs font-semibold uppercase tracking-wide text-faint">Coming next</div>
          <NavLink to="/planned"
            className={({ isActive }) => cx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
              isActive ? "bg-panel text-ink shadow-sm" : "text-muted hover:bg-panel/60 hover:text-ink")}>
            <Sparkles size={16} /> Planned capabilities
          </NavLink>
        </nav>

        {plan && plan.manual_changes > 0 && (
          <div className="m-4 rounded-lg border border-manual/20 bg-manual-soft p-3 text-xs">
            <div className="font-semibold text-manual">{plan.manual_changes} manual change{plan.manual_changes > 1 ? "s" : ""} this week</div>
            <Button variant="ghost" className="mt-2 w-full justify-start px-0 text-manual hover:bg-transparent"
              onClick={() => revert.mutate()} disabled={revert.isPending}>
              <RotateCcw size={14} /> Revert to automatic plan
            </Button>
          </div>
        )}
        <div className="px-5 pb-4 text-[11px] text-faint">Thresholds and client decisions: config/thresholds.yaml</div>
      </aside>

      <main className="scroll-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1400px] px-8 py-7">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
