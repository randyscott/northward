import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { useProfiles } from "./api/hooks";
import { Loading } from "./components/common";
import { Layout, rememberedProfile } from "./components/Layout";
import { BalancesPage } from "./pages/BalancesPage";
import { ComparePage } from "./pages/ComparePage";
import { ProfileOverview } from "./pages/ProfileOverview";
import { ProfilesPage } from "./pages/ProfilesPage";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { ScenarioPage } from "./pages/ScenarioPage";

// The editor pages carry Monaco; load them only when opened.
const DocumentPage = lazy(() => import("./pages/DocumentPage"));
const RulesPage = lazy(() => import("./pages/RulesPage"));

function Home() {
  const profiles = useProfiles();
  if (profiles.isPending) return <Loading />;
  const names = profiles.data?.map((p) => p.name) ?? [];
  const remembered = rememberedProfile();
  const target = remembered && names.includes(remembered) ? remembered : names[0];
  return <Navigate to={target ? `/profiles/${target}` : "/profiles"} replace />;
}

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="profiles" element={<ProfilesPage />} />
        <Route path="profiles/:profile" element={<ProfileOverview />} />
        <Route path="profiles/:profile/balances" element={<BalancesPage />} />
        <Route
          path="profiles/:profile/documents/*"
          element={
            <Suspense fallback={<Loading what="Loading the editor" />}>
              <DocumentPage />
            </Suspense>
          }
        />
        <Route path="profiles/:profile/scenarios/:scenario" element={<ScenarioPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:runId" element={<RunPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route
          path="rules/*"
          element={
            <Suspense fallback={<Loading />}>
              <RulesPage />
            </Suspense>
          }
        />
        <Route path="*" element={<div className="muted">There's no page here.</div>} />
      </Route>
    </Routes>
  );
}
