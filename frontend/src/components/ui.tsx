import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Loader2 } from "lucide-react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-line bg-panel", className)}>{children}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">{children}</h2>
      {hint && <span className="text-xs text-faint">{hint}</span>}
    </div>
  );
}

type Tone = "neutral" | "good" | "bad" | "warn" | "info" | "manual" | "accent";
const tones: Record<Tone, string> = {
  neutral: "bg-sidebar text-muted border-line",
  good: "bg-good-soft text-good border-transparent",
  bad: "bg-bad-soft text-bad border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  info: "bg-info-soft text-info border-transparent",
  manual: "bg-manual-soft text-manual border-transparent",
  accent: "bg-accent-soft text-accent border-transparent",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title}
      className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-xs font-medium", tones[tone])}>
      {children}
    </span>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:brightness-110 border-transparent",
  secondary: "bg-panel text-ink border-line hover:bg-sidebar",
  ghost: "bg-transparent text-muted border-transparent hover:bg-sidebar hover:text-ink",
  danger: "bg-panel text-bad border-line hover:bg-bad-soft",
};

export function Button({ variant = "secondary", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button {...props}
      className={cx("inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant], className)} />
  );
}

export function Select({ label, className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className={cx("flex flex-col gap-1 text-xs font-medium text-muted", className)}>
      {label}
      <select {...props}
        className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent">
        {children}
      </select>
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-sidebar p-0.5">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={cx("rounded-md px-3 py-1 text-sm font-medium transition",
            value === o.value ? "bg-panel text-ink shadow-sm" : "text-muted hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { value: T; label: string; count?: number }[]; onChange: (v: T) => void }) {
  return (
    <div className="mb-4 flex gap-5 border-b border-line">
      {tabs.map((t) => (
        <button key={t.value} onClick={() => onChange(t.value)}
          className={cx("-mb-px border-b-2 pb-2.5 text-sm font-medium transition",
            value === t.value ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink")}>
          {t.label}
          {t.count != null && <span className="ml-1.5 rounded-full bg-sidebar px-1.5 text-xs text-muted">{t.count.toLocaleString()}</span>}
        </button>
      ))}
    </div>
  );
}

export function Kpi({ label, value, delta, deltaGood, hint }: { label: string; value: string; delta?: string | null; deltaGood?: boolean; hint?: string }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted" title={hint}>{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {delta && (
        <span className={cx("mt-1.5 inline-flex items-center gap-0.5 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium",
          deltaGood ? "bg-good-soft text-good" : "bg-bad-soft text-bad")}>
          {deltaGood ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
          {delta}
        </span>
      )}
    </Card>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-muted">
      <Loader2 size={16} className="animate-spin" /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-bad/20 bg-bad-soft p-3 text-sm text-bad">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <div>
        <div className="font-medium">Couldn't load this view</div>
        <div className="text-bad/80">{error instanceof Error ? error.message : String(error)}. Is the API running on port 8000?</div>
      </div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong p-8 text-center">
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className="rounded-lg border border-line p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx("mt-1 text-lg font-semibold", tone === "good" && "text-good", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>{value}</div>
    </div>
  );
}
