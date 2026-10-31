import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Activity, Gauge, LineChart, MessageSquare, ShieldAlert, SlidersHorizontal, Trophy } from "lucide-react";
import { api } from "../api/client";
import type { Features } from "../api/types";
import { Badge, Card, PageHeader } from "../components/ui";

const ROUTES: Partial<Record<keyof Features, string>> = {
  forecast: "/forecast", optimizer: "/optimizer", risk: "/risk", drill: "/drill", benchmark: "/benchmark", data_health: "/data-health",
};

const items: { key: keyof Features; icon: typeof Gauge; title: string; text: string }[] = [
  { key: "forecast", icon: LineChart, title: "Load forecast", text: "Predict each factory's load four buying windows ahead, so demand is pulled forward before a factory overloads." },
  { key: "optimizer", icon: SlidersHorizontal, title: "Cost vs. service planning", text: "Plan all six factories together and choose between the cheapest plan and the safest plan with a single slider." },
  { key: "risk", icon: Gauge, title: "On-time probability", text: "Simulate lead-time variation to show each lot's chance of arriving by its requested date, weighted by sales value." },
  { key: "drill", icon: Activity, title: "Disruption drill", text: "Close a factory for a period and compare how the rule-based plan and the optimised plan respond." },
  { key: "benchmark", icon: Trophy, title: "Planner benchmark", text: "Compare planning approaches on cost, on-time units and unresolved demand over seasons not used for tuning." },
  { key: "ask", icon: MessageSquare, title: "Ask in plain English", text: "Type a question such as \"What if Vietnam is two weeks late?\" and get the scenario and its impact." },
  { key: "data_health", icon: ShieldAlert, title: "Data health monitoring", text: "Automatically flag unusual records in each data load before they affect the plan." },
];

export function Planned() {
  const features = useQuery({ queryKey: ["features"], queryFn: api.features, staleTime: Infinity });
  return (
    <>
      <PageHeader eyebrow="Upcoming work" title="Capabilities" subtitle="This release focuses on the core Buy Plan workflow and forecasting. Other capabilities remain prototypes for later weeks and are not part of the current validated release." />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map(({ key, icon: Icon, title, text }) => {
          const on = features.data?.[key] ?? false;
          const card = (
            <Card className={on ? "h-full p-5 transition hover:border-line-strong" : "h-full p-5"}>
              <div className="mb-3 flex items-center justify-between">
                <div className="grid h-9 w-9 place-items-center rounded-lg bg-accent-soft text-accent"><Icon size={18} /></div>
                {on ? <Badge tone="good">Available</Badge> : <Badge tone="neutral">Coming soon</Badge>}
              </div>
              <div className="font-semibold">{title}</div>
              <p className="mt-1 text-sm text-muted">{text}</p>
            </Card>
          );
          return on && ROUTES[key] ? <Link key={key} to={ROUTES[key]!}>{card}</Link> : <div key={key}>{card}</div>;
        })}
      </div>
    </>
  );
}
