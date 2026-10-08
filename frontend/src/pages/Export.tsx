import { useQuery } from "@tanstack/react-query";
import { FileSpreadsheet, FileText } from "lucide-react";
import { api } from "../api/client";
import { DataTable } from "../components/DataTable";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useRun } from "../lib/run";
import { date, int } from "../lib/format";

export function Export() {
  const { runId } = useRun();
  const plan = useQuery({ queryKey: ["plan", runId], queryFn: () => api.plan(runId) });
  if (plan.isLoading) return <Loading />;
  if (plan.error) return <ErrorBox error={plan.error} />;
  const p = plan.data!;
  const rows = p.lots.filter((l) => l.decision === "Buy" && l.consolidated_qty > 0);

  return (
    <>
      <PageHeader title="Export" subtitle="The buy plan in the specification's output format (fact_buy_plan_suggestions)." />
      <div className="mb-5 grid gap-3 md:grid-cols-3">
        <DownloadCard href={api.exportUrl(runId, "csv")} icon={<FileText />} title="This week · CSV" text={`${rows.length} suggestions for ${runId}`} />
        <DownloadCard href={api.exportUrl(runId, "xlsx")} icon={<FileSpreadsheet />} title="This week · Excel" text="Buy plan, lot details and every decision" />
        <DownloadCard href={api.exportAllUrl()} icon={<FileText />} title="All weeks · CSV" text="Automatic plan for all 100 runs" />
      </div>
      {p.manual_changes > 0 && (
        <Card className="mb-4 p-3 text-sm text-muted">
          <Badge tone="manual">Manual</Badge> Exports for this week include {p.manual_changes} manual change(s). No-Go and Delay lots are left out of the buy plan.
        </Card>
      )}
      <DataTable rows={rows} rowKey={(l) => l.lot_id} columns={[
        { key: "suggestion_id", header: "suggestion_id", value: (l) => l.lot_id, render: (l) => <span className="font-mono text-xs">SUG-{l.lot_id}</span> },
        { key: "run_id", header: "run_id" },
        { key: "article_id", header: "article_id" },
        { key: "market_destination", header: "market_destination" },
        { key: "consolidated_qty", header: "consolidated_qty", align: "right", render: (l) => int(l.consolidated_qty) },
        { key: "suggested_rdd", header: "suggested_rdd", render: (l) => date(l.suggested_rdd) },
        { key: "assigned_factory", header: "assigned_factory" },
        { key: "is_piggyback_applied", header: "is_piggyback_applied", render: (l) => (l.is_piggyback_applied ? "true" : "false") },
        { key: "piggyback_source_window", header: "piggyback_source_window", render: (l) => l.piggyback_source_window ?? "" },
      ]} />
    </>
  );
}

function DownloadCard({ href, icon, title, text }: { href: string; icon: React.ReactNode; title: string; text: string }) {
  return (
    <a href={href} className="group flex items-center gap-3 rounded-xl border border-line bg-panel p-4 transition hover:border-accent">
      <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent-soft text-accent">{icon}</div>
      <div>
        <div className="text-sm font-semibold group-hover:text-accent">{title}</div>
        <div className="text-xs text-muted">{text}</div>
      </div>
    </a>
  );
}
