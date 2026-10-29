import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./index.css";
import { Layout } from "./components/Layout";
import { RunProvider } from "./lib/run";
import { ThemeProvider } from "./lib/theme";
import { BuyPlan } from "./pages/BuyPlan";
import { WhatIf } from "./pages/WhatIf";
import { PullForward } from "./pages/PullForward";
import { Export } from "./pages/Export";
import { Checks } from "./pages/Checks";
import { Planned } from "./pages/Planned";
import { Impact } from "./pages/Impact";
import { Loading } from "./components/ui";

// The chart library is large; load the capacity page only when it is opened.
const Capacity = lazy(() => import("./pages/Capacity").then((m) => ({ default: m.Capacity })));
// The globe (three.js) is larger still; load it only on the network page.
const Forecast = lazy(() => import("./pages/Forecast").then((m) => ({ default: m.Forecast })));
const Network = lazy(() => import("./pages/Network").then((m) => ({ default: m.Network })));

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1, staleTime: 30_000 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
      <RunProvider>
        <HashRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<BuyPlan />} />
              <Route path="what-if" element={<WhatIf />} />
              <Route path="pull-forward" element={<PullForward />} />
              <Route path="capacity" element={<Suspense fallback={<Loading />}><Capacity /></Suspense>} />
              <Route path="forecast" element={<Suspense fallback={<Loading />}><Forecast /></Suspense>} />
              <Route path="network" element={<Suspense fallback={<Loading />}><Network /></Suspense>} />
              <Route path="impact" element={<Impact />} />
              <Route path="export" element={<Export />} />
              <Route path="checks" element={<Checks />} />
              <Route path="planned" element={<Planned />} />
            </Route>
          </Routes>
        </HashRouter>
      </RunProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
