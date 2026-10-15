import { useId, useState, type ButtonHTMLAttributes, type CSSProperties, type ReactNode, type SelectHTMLAttributes } from "react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, type LucideIcon } from "lucide-react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Card({ children, className, style }: { children: ReactNode; className?: string; style?: CSSProperties }) {
  return <div style={style} className={cx("rounded-2xl border border-line bg-panel shadow-[var(--shadow-card)]", className)}>{children}</div>;
}

export function PageHeader({ title, subtitle, actions, eyebrow, icon: Icon }: {
  title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode; icon?: LucideIcon;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 animate-fade-up">
      <div className="min-w-0">
        {eyebrow && <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.16em] text-accent">{eyebrow}</div>}
        <h1 className="flex items-center gap-3 text-[30px] font-semibold leading-tight tracking-[-0.03em]">
          {Icon && <span className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-sidebar text-accent"><Icon size={18} /></span>}
          {title}
        </h1>
        {subtitle && <p className="mt-2 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-[15px] font-semibold tracking-tight">{children}</h2>
      {hint && <span className="text-xs text-faint">{hint}</span>}
    </div>
  );
}

type Tone = "neutral" | "good" | "bad" | "warn" | "info" | "manual" | "accent";
const tones: Record<Tone, string> = {
  neutral: "bg-sidebar text-muted ring-line-strong/60",
  good: "bg-good-soft text-good ring-good/20",
  bad: "bg-bad-soft text-bad ring-bad/20",
  warn: "bg-warn-soft text-warn ring-warn/25",
  info: "bg-info-soft text-info ring-info/20",
  manual: "bg-manual-soft text-manual ring-manual/20",
  accent: "bg-accent-soft text-accent ring-accent/20",
};
const dots: Record<Tone, string> = {
  neutral: "bg-faint", good: "bg-good", bad: "bg-bad", warn: "bg-warn", info: "bg-info", manual: "bg-manual", accent: "bg-accent",
};

export function Badge({ tone = "neutral", children, title, dot }: { tone?: Tone; children: ReactNode; title?: string; dot?: boolean }) {
  return (
    <span title={title}
      className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset", tones[tone])}>
      {dot && <i className={cx("h-1.5 w-1.5 rounded-full", dots[tone])} />}
      {children}
    </span>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<ButtonVariant, string> = {
  primary: "border-transparent bg-accent text-[#04110e] shadow-[0_0_0_1px_color-mix(in_oklab,var(--color-accent)_40%,transparent),0_8px_24px_-8px_color-mix(in_oklab,var(--color-accent)_70%,transparent)] hover:brightness-110",
  secondary: "border-line bg-panel text-ink hover:border-line-strong hover:bg-sidebar",
  ghost: "border-transparent bg-transparent text-muted hover:bg-sidebar hover:text-ink",
  danger: "border-line bg-panel text-bad hover:bg-bad-soft",
};

export function Button({ variant = "secondary", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button {...props}
      className={cx("inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] font-medium transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant], className)} />
  );
}

export const fieldClass = "rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-ink outline-none transition placeholder:text-faint hover:border-line-strong focus:border-accent focus:ring-4 focus:ring-accent/10";

export function Select({ label, className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className={cx("flex flex-col gap-1.5 text-xs font-medium text-muted", className)}>
      {label}
      <select {...props} className={fieldClass}>{children}</select>
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex gap-1">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={cx("rounded-lg border px-3 py-1.5 text-[13px] font-medium transition",
            value === o.value ? "border-line-strong bg-sidebar text-ink" : "border-transparent text-muted hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { value: T; label: string; count?: number; tone?: Tone; icon?: LucideIcon }[]; onChange: (v: T) => void }) {
  return (
    <div className="scroll-thin mb-4 flex gap-1 overflow-x-auto border-b border-line pb-3">
      {tabs.map((t) => {
        const active = value === t.value;
        const Icon = t.icon;
        return (
          <button key={t.value} onClick={() => onChange(t.value)}
            className={cx("inline-flex shrink-0 items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-medium transition",
              active ? "border-line-strong bg-sidebar text-ink" : "border-transparent text-muted hover:text-ink")}>
            {Icon && <Icon size={14} className={active ? "text-accent" : ""} />}
            {t.label}
            {t.count != null && (
              <span className={cx("font-num text-[11px]", active ? "text-ink" : "text-faint")}>{t.count.toLocaleString()}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export type KpiTone = "green" | "amber" | "violet" | "blue" | "teal" | "rose";

/** Tinted KPI card with a glowing trend chart (one series; the card's label names it). */
export function GlowKpi({ label, value, tone, icon: Icon, sub, delta, deltaGood, points, highlight, format, xLabel, hint }: {
  label: string; value: string; tone: KpiTone; icon?: LucideIcon; sub?: ReactNode; delta?: string | null; deltaGood?: boolean;
  points: { x: string; y: number }[]; highlight?: string; format: (v: number) => string; xLabel?: (x: string) => string; hint?: string;
}) {
  return (
    <div className="glow-card p-5" style={{ "--tone": `var(--color-tone-${tone})` } as CSSProperties}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[13px] font-medium text-ink/90" title={hint}>{label}</div>
        {Icon && <Icon size={15} style={{ color: "var(--tone)" }} />}
      </div>
      <div className="font-num mt-3 text-[34px] font-medium leading-none">{value}</div>
      <div className="mt-2 flex min-h-5 flex-wrap items-center gap-2 text-xs text-muted">
        {sub}
        {delta && (
          <span className={cx("inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
            deltaGood ? "bg-good-soft text-good" : "bg-bad-soft text-bad")}>
            {deltaGood ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{delta}
          </span>
        )}
      </div>
      <AreaTrend points={points} highlight={highlight} format={format} xLabel={xLabel} />
    </div>
  );
}

/** Area trend with a glowing line, hover crosshair and readout. */
export function AreaTrend({ points, highlight, format, xLabel, height = 92 }: {
  points: { x: string; y: number }[]; highlight?: string; format: (v: number) => string; xLabel?: (x: string) => string; height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const id = `area${useId().replace(/:/g, "")}`;
  if (points.length < 2) return <div style={{ height: height + 20 }} />;
  const W = 300, H = height, top = 8, bottom = 4;
  const ys = points.map((p) => p.y);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const sx = (i: number) => (i / (points.length - 1)) * W;
  const sy = (v: number) => H - bottom - (hi === lo ? 0.5 : (v - lo) / (hi - lo)) * (H - top - bottom);
  const d = points.map((p, i) => {
    if (!i) return `M${sx(0)},${sy(p.y)}`;
    const x0 = sx(i - 1), x1 = sx(i), y0 = sy(points[i - 1].y), y1 = sy(p.y), mx = (x0 + x1) / 2;
    return `C${mx},${y0} ${mx},${y1} ${x1},${y1}`;
  }).join("");
  const hiIdx = highlight ? points.findIndex((p) => p.x === highlight) : -1;
  const shown = hover ?? (hiIdx >= 0 ? hiIdx : points.length - 1);
  const fmtX = xLabel ?? ((x: string) => x);
  return (
    <div className="relative mt-4 -mx-1">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full overflow-visible" style={{ height: H }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setHover(Math.max(0, Math.min(points.length - 1, Math.round(((e.clientX - r.left) / r.width) * (points.length - 1)))));
        }}>
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--tone)" stopOpacity="0.35" />
            <stop offset="1" stopColor="var(--tone)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} stroke="var(--color-grid)" strokeWidth="1" vectorEffect="non-scaling-stroke" strokeDasharray="2 4" />
        ))}
        <path d={`${d}L${W},${H}L0,${H}Z`} fill={`url(#${id})`} />
        <path d={d} fill="none" stroke="var(--tone)" strokeWidth="2" vectorEffect="non-scaling-stroke" className="glow-line" />
        <line x1={sx(shown)} x2={sx(shown)} y1="0" y2={H} stroke="var(--tone)" strokeOpacity="0.45" strokeWidth="1" vectorEffect="non-scaling-stroke" strokeDasharray="3 3" />
      </svg>
      <span className="pointer-events-none absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-4 ring-[color-mix(in_oklab,var(--tone)_25%,transparent)]"
        style={{ left: `${(sx(shown) / W) * 100}%`, top: sy(points[shown].y), background: "var(--tone)" }} />
      <div className="mt-2 flex items-center justify-between font-mono text-[10.5px] text-faint">
        <span>{fmtX(points[0].x)}</span>
        <span className="rounded-md border border-line bg-panel/80 px-1.5 py-0.5 text-muted">
          {fmtX(points[shown].x)} · <span className="text-ink">{format(points[shown].y)}</span>
        </span>
        <span>{fmtX(points[points.length - 1].x)}</span>
      </div>
    </div>
  );
}

/** Plain KPI card, for secondary numbers. */
export function Kpi({ label, value, delta, deltaGood, hint, icon: Icon, sub }: {
  label: string; value: string; delta?: string | null; deltaGood?: boolean; hint?: string; icon?: LucideIcon; sub?: ReactNode;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium text-muted" title={hint}>{label}</div>
        {Icon && <Icon size={14} className="text-faint" />}
      </div>
      <div className="font-num mt-2 text-2xl font-medium">{value}</div>
      {sub && <div className="mt-1 text-xs text-faint">{sub}</div>}
      {delta && (
        <span className={cx("mt-2 inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
          deltaGood ? "bg-good-soft text-good" : "bg-bad-soft text-bad")}>
          {deltaGood ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{delta}
        </span>
      )}
    </Card>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-xl", className)} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="space-y-3 py-2" aria-busy="true" aria-label={label}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-44 rounded-2xl" />)}
      </div>
      <Skeleton className="h-10" />
      <Skeleton className="h-64 rounded-2xl" />
      <div className="font-mono text-xs text-faint">{label}</div>
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="flex items-start gap-2 rounded-2xl border border-bad/25 bg-bad-soft p-4 text-sm text-bad">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <div>
        <div className="font-medium">Couldn't load this view</div>
        <div className="opacity-80">{error instanceof Error ? error.message : String(error)}. Is the API running on port 8000?</div>
      </div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="dot-grid rounded-2xl border border-dashed border-line-strong p-10 text-center">
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx("font-num mt-1 text-lg font-medium", tone === "good" && "text-good", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>{value}</div>
    </div>
  );
}

/** Factory load before and after a lot, with the threshold and limit marked. */
export function LoadBar({ before, after, threshold, limit }: { before: number; after: number; threshold: number; limit: number }) {
  const max = Math.max(120, Math.ceil(after / 10) * 10);
  const x = (v: number) => `${(Math.min(v, max) / max) * 100}%`;
  const tone = after > limit ? "var(--color-status-critical)" : after >= threshold ? "var(--color-status-warning)" : "var(--color-status-good)";
  return (
    <div>
      <div className="relative h-2.5 rounded-full bg-sidebar">
        <div className="absolute inset-y-0 left-0 rounded-l-full bg-line-strong" style={{ width: x(before) }} />
        <div className="absolute inset-y-0 rounded-r-full" style={{ left: `calc(${x(before)} + 2px)`, width: `calc(${x(after)} - ${x(before)} - 2px)`, background: tone, minWidth: 2, boxShadow: `0 0 10px ${tone}` }} />
        <i className="absolute -top-1 h-[18px] w-px bg-warn" style={{ left: x(threshold) }} title={`${threshold}% threshold`} />
        <i className="absolute -top-1 h-[18px] w-0.5 bg-ink" style={{ left: x(limit) }} title={`${limit}% limit`} />
      </div>
      <div className="relative mt-1 h-4 font-mono text-[10.5px] text-faint">
        <span className="absolute -translate-x-1/2" style={{ left: x(threshold) }}>{threshold}%</span>
        <span className="absolute -translate-x-1/2" style={{ left: x(limit) }}>{limit}%</span>
      </div>
    </div>
  );
}
