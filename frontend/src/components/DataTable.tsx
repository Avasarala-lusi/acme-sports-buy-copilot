import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { cx } from "./ui";

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  value?: (row: T) => string | number | boolean | null | undefined;
  align?: "left" | "right" | "center";
  width?: string;
  title?: string;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  selectedKey?: string | null;
  maxHeight?: string;
  emptyText?: string;
  pageSize?: number;
}

export function DataTable<T>({ rows, columns, rowKey, onRowClick, selectedKey, maxHeight = "65vh", emptyText = "No rows", pageSize = 200 }: Props<T>) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [limit, setLimit] = useState(pageSize);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    const get = col.value ?? ((r: T) => (r as Record<string, unknown>)[col.key] as string | number);
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va > vb ? 1 : va < vb ? -1 : 0) * sort.dir;
    });
  }, [rows, columns, sort]);

  const visible = sorted.slice(0, limit);
  const toggle = (key: string) =>
    setSort((s) => (s?.key === key ? (s.dir === 1 ? { key, dir: -1 } : null) : { key, dir: 1 }));

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-panel shadow-[var(--shadow-card)]">
      <div className="scroll-thin overflow-auto" style={{ maxHeight }}>
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-panel/90 backdrop-blur">
            <tr>
              {columns.map((c) => (
                <th key={c.key} style={{ width: c.width }} title={c.title}
                  onClick={() => toggle(c.key)}
                  className={cx("cursor-pointer select-none whitespace-nowrap border-b border-line px-3 py-3 font-mono text-[10.5px] font-normal uppercase tracking-[0.08em] text-faint hover:text-ink",
                    c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left")}>
                  <span className="inline-flex items-center gap-1">
                    {c.header}
                    {sort?.key === c.key && (sort.dir === 1 ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const k = rowKey(r);
              return (
                <tr key={k} onClick={onRowClick ? () => onRowClick(r) : undefined}
                  className={cx("border-b border-line/60 transition-colors last:border-0", onRowClick && "cursor-pointer hover:bg-sidebar/70",
                    selectedKey === k && "bg-accent-soft hover:bg-accent-soft")}>
                  {columns.map((c) => (
                    <td key={c.key}
                      className={cx("whitespace-nowrap px-3 py-3 text-[13px]", c.align === "right" ? "text-right tabular-nums" : c.align === "center" ? "text-center" : "text-left")}>
                      {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className="p-8 text-center text-sm text-muted">{emptyText}</div>}
      </div>
      <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-faint">
        <span>{Math.min(limit, rows.length).toLocaleString()} of {rows.length.toLocaleString()} rows</span>
        {limit < rows.length && (
          <button className="font-medium text-accent hover:underline" onClick={() => setLimit((l) => l + pageSize)}>Show more</button>
        )}
      </div>
    </div>
  );
}
