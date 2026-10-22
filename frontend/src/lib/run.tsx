import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Run } from "../api/types";

interface RunContextValue {
  runs: Run[];
  run: Run | undefined;
  runId: string;
  setRunId: (id: string) => void;
  /** a lot to open in the buy plan (set by the command palette) */
  openLot: string | null;
  setOpenLot: (id: string | null) => void;
}

const RunContext = createContext<RunContextValue | null>(null);
const STORAGE_KEY = "buy-planner.run";

export function RunProvider({ children }: { children: ReactNode }) {
  const { data: runs = [] } = useQuery({ queryKey: ["runs"], queryFn: api.runs, staleTime: Infinity });
  const [runId, setRunId] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? "MRP-WK019";
    } catch {
      return "MRP-WK019";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, runId);
    } catch {
      /* storage unavailable */
    }
  }, [runId]);

  const [openLot, setOpenLot] = useState<string | null>(null);
  const run = runs.find((r) => r.run_id === runId);
  return <RunContext.Provider value={{ runs, run, runId, setRunId, openLot, setOpenLot }}>{children}</RunContext.Provider>;
}

export function useRun() {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error("useRun must be used inside RunProvider");
  return ctx;
}
