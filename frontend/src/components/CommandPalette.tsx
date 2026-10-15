import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarDays, CornerDownLeft, FileText, Package, Search } from "lucide-react";
import type { Plan } from "../api/types";
import { useRun } from "../lib/run";
import { date } from "../lib/format";
import { cx } from "./ui";

export interface PageItem { to: string; label: string }

type Item = { id: string; group: string; label: string; hint?: string; icon: typeof Search; run: () => void };

export function CommandPalette({ open, onClose, pages }: { open: boolean; onClose: () => void; pages: PageItem[] }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const qc = useQueryClient();
  const { runs, runId, setRunId, setOpenLot } = useRun();

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const plan = qc.getQueryData<Plan>(["plan", runId]);
    const all: Item[] = [
      ...pages.map((p) => ({ id: `p${p.to}`, group: "Pages", label: p.label, icon: FileText, run: () => nav(p.to) })),
      ...runs.map((r) => ({
        id: `r${r.run_id}`, group: "Weeks", label: `${r.run_id}${r.is_buying_run ? " · buying run" : " · draft"}`,
        hint: date(r.mrp_freeze_datetime_utc), icon: CalendarDays, run: () => setRunId(r.run_id),
      })),
      ...(plan?.lots ?? []).map((l) => ({
        id: `l${l.lot_id}`, group: `Lots in ${runId}`, label: `${l.lot_id.split("-").pop()} · ${l.article_id} · ${l.market_destination}`,
        hint: `${l.assigned_factory} · ${l.consolidated_qty.toLocaleString()} units`, icon: Package,
        run: () => { nav("/"); setOpenLot(l.lot_id); },
      })),
    ];
    const needle = q.trim().toLowerCase();
    const hits = needle ? all.filter((i) => `${i.label} ${i.hint ?? ""}`.toLowerCase().includes(needle)) : all.filter((i) => i.group === "Pages");
    return hits.slice(0, 40);
  }, [q, pages, runs, runId, qc, nav, setRunId, setOpenLot]);

  if (!open) return null;
  const choose = (i: Item | undefined) => { if (i) { i.run(); onClose(); } };
  let lastGroup = "";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh] backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-panel shadow-[var(--shadow-pop)] animate-fade-up"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Search size={16} className="text-faint" />
          <input ref={input} value={q} placeholder="Jump to a page, week (e.g. WK025) or lot (e.g. HD-17100)…"
            onChange={(e) => { setQ(e.target.value); setActive(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
              if (e.key === "Enter") choose(items[active]);
              if (e.key === "Escape") onClose();
            }}
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-faint" />
          <kbd className="rounded-md border border-line px-1.5 text-[10px] text-faint">ESC</kbd>
        </div>
        <div className="scroll-thin max-h-[52vh] overflow-y-auto p-2">
          {items.length === 0 && <div className="p-6 text-center text-sm text-muted">No matches</div>}
          {items.map((i, n) => {
            const header = i.group !== lastGroup ? (lastGroup = i.group) : null;
            const Icon = i.icon;
            return (
              <div key={i.id}>
                {header && <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-faint">{header}</div>}
                <button onMouseEnter={() => setActive(n)} onClick={() => choose(i)}
                  className={cx("flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-sm",
                    n === active ? "bg-accent-soft text-ink" : "text-muted")}>
                  <Icon size={15} className={n === active ? "text-accent" : "text-faint"} />
                  <span className="flex-1 truncate">{i.label}</span>
                  {i.hint && <span className="text-xs text-faint">{i.hint}</span>}
                  {n === active && <CornerDownLeft size={13} className="text-faint" />}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
