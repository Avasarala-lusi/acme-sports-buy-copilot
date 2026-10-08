import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";

export function Drawer({ open, onClose, title, subtitle, children }: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-ink/20" onClick={onClose} />
      <aside role="dialog" aria-modal="true"
        className="absolute right-0 top-0 flex h-full w-full max-w-[560px] flex-col border-l border-line bg-panel shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <div className="text-base font-semibold">{title}</div>
            {subtitle && <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-muted">{subtitle}</div>}
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-muted hover:bg-sidebar hover:text-ink">
            <X size={18} />
          </button>
        </header>
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </aside>
    </div>
  );
}
