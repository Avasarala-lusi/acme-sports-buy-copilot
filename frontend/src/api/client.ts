import type {
  Checks, Customer, DelayResult, LotDecision, Factory, Features, HoldResult, LotRequisition, Overrides, Plan,
  PullForward, CapacityRow, Requisition, Run, Settings, SwapResult, TrendPoint, Network,
} from "./types";

// Dev uses the Vite proxy (/api -> :8000). The built app is served by the API itself (same origin).
export const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "/api" : "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const body = (data: unknown) => ({ body: JSON.stringify(data) });

export const api = {
  runs: () => request<Run[]>("/runs"),
  plan: (run: string) => request<Plan>(`/plan/${run}`),
  requisitions: (run: string, status: "unresolved" | "future" | "waiting") =>
    request<Requisition[]>(`/runs/${run}/requisitions?status=${status}`),
  customers: (run: string) => request<Customer[]>(`/runs/${run}/customers`),
  lotRequisitions: (run: string, lot: string) => request<LotRequisition[]>(`/lots/${run}/${lot}/requisitions`),
  factories: () => request<Factory[]>("/factories"),
  settings: () => request<Settings>("/settings"),
  dataIssues: () => request<string[]>("/data-issues"),
  checks: () => request<Checks>("/checks"),
  trend: () => request<TrendPoint[]>("/trend"),
  network: (run: string) => request<Network>(`/network/${run}`),
  features: () => request<Features>("/features"),
  pullForward: (run: string) => request<PullForward>(`/pull-forward/${run}`),
  capacity: (run: string) => request<CapacityRow[]>(`/capacity/${run}`),

  holdScenario: (run: string, customer_id: string) =>
    request<HoldResult>("/scenario", { method: "POST", ...body({ run_id: run, type: "hold_customer", customer_id }) }),
  delayScenario: (run: string, factory: string, days: number) =>
    request<DelayResult>("/scenario", { method: "POST", ...body({ run_id: run, type: "delay", factory, days }) }),
  swapScenario: (run: string, lot_id: string, target_factory: string) =>
    request<SwapResult>("/scenario", { method: "POST", ...body({ run_id: run, type: "swap", lot_id, target_factory }) }),

  overrides: (run: string) => request<Overrides>(`/overrides/${run}`),
  setLot: (run: string, lot: string, decision: LotDecision, factory: string | null, note: string) =>
    request<Overrides>(`/overrides/${run}/lots/${lot}`, { method: "PUT", ...body({ decision, factory, note }) }),
  revertLot: (run: string, lot: string) => request<Overrides>(`/overrides/${run}/lots/${lot}`, { method: "DELETE" }),
  hold: (run: string, customer_id: string) =>
    request<Overrides>(`/overrides/${run}/holds`, { method: "POST", ...body({ customer_id }) }),
  releaseHold: (run: string, customer: string) =>
    request<Overrides>(`/overrides/${run}/holds/${customer}`, { method: "DELETE" }),
  revertWeek: (run: string) => request<Overrides>(`/overrides/${run}`, { method: "DELETE" }),

  exportUrl: (run: string, format: "csv" | "xlsx") => `${API_BASE}/export/${run}?format=${format}`,
  exportAllUrl: () => `${API_BASE}/export-all`,
};
