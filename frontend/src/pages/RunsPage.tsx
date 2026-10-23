import { Link, useSearchParams } from "react-router-dom";

import { useProfiles, useRuns } from "../api/hooks";
import { ErrorNotice, Loading, StatusBadge } from "../components/common";
import { compactMoney, dateTime, percent } from "../lib/format";

interface SummaryHeadline {
  success?: { probability?: number };
  legacy_after_tax?: { real?: { p50?: number } };
  final_net_worth_real?: number;
  shortfall_years?: number[];
}

export function headline(run: {
  kind: string;
  status: string;
  summary?: Record<string, unknown> | null;
  error?: string | null;
}) {
  const summary = (run.summary ?? {}) as SummaryHeadline;
  if (run.status === "failed") return run.error ?? "failed";
  if (run.status !== "complete") return "";
  if (run.kind === "monte_carlo") {
    return `${percent(summary.success?.probability)} success · median legacy ${compactMoney(summary.legacy_after_tax?.real?.p50)}`;
  }
  const shortfalls = (summary.shortfall_years ?? []).length;
  return `final net worth ${compactMoney(summary.final_net_worth_real)} (today $)${shortfalls ? ` · ${shortfalls} short years` : ""}`;
}

export function RunTable({
  filters,
}: {
  filters: { profile?: string; scenario?: string; kind?: string; limit?: number };
}) {
  const runs = useRuns(filters);
  if (runs.isPending) return <Loading />;
  if (runs.error) return <ErrorNotice error={runs.error} />;
  if (!runs.data?.length) return <div className="muted">No runs yet.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Scenario</th>
            <th>Kind</th>
            <th>Status</th>
            <th>Result</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.data.map((run) => (
            <tr key={run.id}>
              <td>
                <Link to={`/runs/${run.id}`}>#{run.id}</Link>
              </td>
              <td>
                <Link to={`/profiles/${run.profile}/scenarios/${run.scenario}`} className="secondary">
                  {run.profile}/{run.scenario}
                </Link>
              </td>
              <td className="secondary">
                {run.kind === "monte_carlo"
                  ? `Monte Carlo · ${run.n_sims?.toLocaleString()} paths · seed ${run.seed}`
                  : "Deterministic"}
              </td>
              <td>
                <StatusBadge status={run.status} />
                {run.progress && run.status === "running" && (
                  <span className="small muted">
                    {" "}
                    {percent(run.progress.done / Math.max(1, run.progress.total), 0)}
                  </span>
                )}
              </td>
              <td className="secondary" style={{ whiteSpace: "normal" }}>
                {headline(run)}
              </td>
              <td className="secondary">{dateTime(run.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RunsPage() {
  const [params, setParams] = useSearchParams();
  const profiles = useProfiles();
  const profile = params.get("profile") ?? undefined;
  const kind = params.get("kind") ?? undefined;
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };
  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Run history</h1>
          <div className="subtitle">Every run is stored with the exact document revisions it used.</div>
        </div>
      </div>
      <div className="row">
        <select aria-label="Profile filter" value={profile ?? ""} onChange={(e) => set("profile", e.target.value)}>
          <option value="">All profiles</option>
          {profiles.data?.map((p) => (
            <option key={p.name}>{p.name}</option>
          ))}
        </select>
        <select aria-label="Kind filter" value={kind ?? ""} onChange={(e) => set("kind", e.target.value)}>
          <option value="">All kinds</option>
          <option value="monte_carlo">Monte Carlo</option>
          <option value="deterministic">Deterministic</option>
        </select>
      </div>
      <section className="card">
        <RunTable filters={{ profile, kind, limit: 200 }} />
      </section>
    </div>
  );
}
