import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, unwrap } from "../api/client";
import { useDocument } from "../api/hooks";
import { ErrorNotice, Loading } from "../components/common";
import { compactMoney } from "../lib/format";
import { RunTable } from "./RunsPage";

interface ScenarioData {
  description?: string;
  rule_set?: string;
  horizon?: { start_year?: number; end_age?: number; end_year?: number };
  market?: { preset?: string };
  levers?: {
    ss_claim_ages?: Record<string, number | { years: number; months?: number }>;
    roth_conversions?: { kind?: string };
    mortality?: { kind?: string };
    withdrawal_order?: string[];
    cash_reserve?: { account: string; amount: number } | null;
  };
  overrides?: Record<string, Record<string, unknown>>;
}

/** A claiming age as written in YAML: 67, or {years: 67, months: 6}. */
export function claimAge(age: number | { years: number; months?: number }): string {
  if (typeof age === "number") return String(age);
  return age.months ? `${age.years} and ${age.months} month${age.months === 1 ? "" : "s"}` : String(age.years);
}

function Facts({ data }: { data: ScenarioData }) {
  const levers = data.levers ?? {};
  const claims = Object.entries(levers.ss_claim_ages ?? {});
  const overrides = Object.entries(data.overrides ?? {}).flatMap(([doc, paths]) =>
    Object.entries(paths).map(([path, value]) => `${doc}: ${path} = ${JSON.stringify(value)}`),
  );
  const rows: [string, string][] = [
    [
      "Horizon",
      `${data.horizon?.start_year ?? "?"} until ${data.horizon?.end_year ? `year ${data.horizon.end_year}` : `age ${data.horizon?.end_age ?? 95}`}`,
    ],
    ["Market", data.market?.preset ?? "forward_conservative (default)"],
    ["Rules", data.rule_set ?? "latest"],
    [
      "Social Security",
      claims.length ? claims.map(([m, age]) => `${m} at ${claimAge(age)}`).join(", ") : "full retirement age (default)",
    ],
    ["Roth conversions", levers.roth_conversions?.kind ?? "none"],
    ["Mortality", levers.mortality?.kind ?? "none (everyone reaches the horizon)"],
    ["Withdrawal order", (levers.withdrawal_order ?? ["taxable", "deferred", "roth", "hsa"]).join(" → ")],
    [
      "Cash reserve",
      levers.cash_reserve
        ? `${compactMoney(levers.cash_reserve.amount)} (today's dollars) kept in ${levers.cash_reserve.account}`
        : "none",
    ],
  ];
  return (
    <table>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label}>
            <td className="secondary" style={{ width: 160 }}>
              {label}
            </td>
            <td>{value}</td>
          </tr>
        ))}
        <tr>
          <td className="secondary">Overrides</td>
          <td style={{ whiteSpace: "normal" }}>
            {overrides.length ? (
              overrides.map((o) => (
                <div key={o} className="mono">
                  {o}
                </div>
              ))
            ) : (
              <span className="muted">none</span>
            )}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

export function ScenarioPage() {
  const { profile = "", scenario = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const doc = useDocument(profile, `scenarios/${scenario}`);
  const [sims, setSims] = useState(5000);
  const [seed, setSeed] = useState(1);
  const [useCache, setUseCache] = useState(true);

  const deterministic = useMutation({
    mutationFn: () => unwrap(api.POST("/api/simulate/deterministic", { body: { profile, scenario, ledger: true } })),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${result.run.id}`);
    },
  });
  const monteCarlo = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/simulate/montecarlo", { body: { profile, scenario, n_sims: sims, seed, use_cache: useCache } }),
      ),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${run.id}`);
    },
  });

  if (doc.isPending) return <Loading />;
  if (doc.error) return <ErrorNotice error={doc.error} />;
  const data = doc.data!.data as ScenarioData;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="crumbs">
            <Link to={`/profiles/${profile}`}>{profile}</Link> / scenarios
          </div>
          <h1>{scenario}</h1>
          <div className="subtitle">{data.description ?? <span className="muted">No description</span>}</div>
        </div>
        <Link className="button" to={`/profiles/${profile}/documents/scenarios/${scenario}`}>
          Edit scenario
        </Link>
      </div>

      <div className="grid-2">
        <section className="card">
          <h2 style={{ marginBottom: 8 }}>Run</h2>
          <div className="stack">
            <div className="row">
              <button className="primary" onClick={() => monteCarlo.mutate()} disabled={monteCarlo.isPending}>
                Run Monte Carlo
              </button>
              <label className="field">
                Paths
                <input
                  type="number"
                  min={1}
                  max={100000}
                  step={500}
                  value={sims}
                  onChange={(e) => setSims(Number(e.target.value))}
                  className="number"
                  aria-label="Paths"
                />
              </label>
              <label className="field">
                Seed
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                  className="number"
                  style={{ width: 80 }}
                  aria-label="Seed"
                />
              </label>
            </div>
            <label className="inline small secondary">
              <input type="checkbox" checked={useCache} onChange={(e) => setUseCache(e.target.checked)} />
              Reuse a stored run with exactly the same inputs, seed, and paths
            </label>
            <div className="row">
              <button onClick={() => deterministic.mutate()} disabled={deterministic.isPending}>
                {deterministic.isPending ? "Running…" : "Run deterministic"}
              </button>
              <span className="small muted">One path at the preset's typical returns, with the full ledger.</span>
            </div>
            <ErrorNotice error={monteCarlo.error ?? deterministic.error} title="Couldn't start the run" />
          </div>
        </section>
        <section className="card">
          <h2 style={{ marginBottom: 8 }}>Settings</h2>
          <Facts data={data} />
        </section>
      </div>

      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Runs of this scenario</h2>
        <RunTable filters={{ profile, scenario, limit: 20 }} />
      </section>
    </div>
  );
}
