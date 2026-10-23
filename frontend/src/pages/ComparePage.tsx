// Compare two to four scenarios on the same Monte Carlo draws. The API queues any missing runs and answers 202 until
// they're all done; re-asking the same question is cheap (identical requests share runs), so this page simply polls.
import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, type Percentiles, type Results, unwrap } from "../api/client";
import { useProfile, useProfiles } from "../api/hooks";
import { LineChart } from "../components/charts";
import { ErrorNotice, Loading, ProgressBar, StatusBadge } from "../components/common";
import { useCurrentProfile } from "../components/Layout";
import { compactMoney, percent, signedMoney } from "../lib/format";

interface ComparisonRow {
  scenario: string;
  success_probability: number;
  legacy_after_tax_real: Percentiles;
  lifetime_taxes_real: Percentiles;
  vs_first: {
    succeeds_where_first_fails: number;
    fails_where_first_succeeds: number;
    legacy_after_tax_real_difference: Percentiles;
    legacy_higher_probability: number;
    lifetime_taxes_real_difference: Percentiles;
  };
}

const MAX_SCENARIOS = 4;

function Comparison({
  profile,
  scenarios,
  sims,
  seed,
}: {
  profile: string;
  scenarios: string[];
  sims: number;
  seed: number;
}) {
  const compare = useQuery({
    queryKey: ["compare", profile, scenarios, sims, seed],
    queryFn: () => unwrap(api.POST("/api/compare", { body: { profile, scenarios, n_sims: sims, seed } })),
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 1500 : false),
  });
  const runIds = compare.data?.status === "complete" ? compare.data.runs.map((r) => r.id) : [];
  const medians = useQueries({
    queries: runIds.map((id) => ({
      queryKey: ["results", id, {}, ["net_worth"]],
      queryFn: async () =>
        (await unwrap(
          api.GET("/api/runs/{run_id}/results", {
            params: { path: { run_id: id }, query: { buckets: ["net_worth"] } },
          }),
        )) as unknown as Results,
      staleTime: Infinity,
    })),
  });
  const chart = useMemo(() => {
    const loaded = medians.map((m) => m.data).filter((d): d is Results => !!d);
    if (loaded.length !== runIds.length || !loaded.length) return null;
    const years = loaded.reduce(
      (longest, d) => (d.years.length > longest.length ? d.years : longest),
      loaded[0]!.years,
    );
    return {
      years,
      series: loaded.map((d) => ({
        name: d.scenario,
        values: years.map((y) => d.bands?.net_worth?.real?.p50[d.years.indexOf(y)] ?? null),
      })),
    };
  }, [medians, runIds.length]);

  if (compare.isPending) return <Loading what="Starting the runs" />;
  if (compare.error) return <ErrorNotice error={compare.error} title="Couldn't compare these scenarios" />;
  const data = compare.data!;

  if (data.status === "pending") {
    return (
      <section className="card stack">
        <h2>Running the scenarios on the same {sims.toLocaleString()} paths…</h2>
        {data.runs.map((run) => (
          <div key={run.id} className="row">
            <span style={{ width: 200 }}>
              <Link to={`/runs/${run.id}`}>#{run.id}</Link> {run.scenario}
            </span>
            <StatusBadge status={run.status} />
            <div style={{ flex: 1 }}>
              {run.progress && <ProgressBar done={run.progress.done} total={run.progress.total} />}
            </div>
          </div>
        ))}
      </section>
    );
  }

  const rows = (data.comparison?.scenarios ?? []) as ComparisonRow[];
  const base = rows[0]?.scenario;
  return (
    <div className="stack">
      <section className="card">
        <div className="card-header">
          <h2>Results</h2>
          <span className="hint">
            Today's dollars. Differences are path by path against <strong>{base}</strong>, so they reflect the
            decisions, not luck.
          </span>
        </div>
        <div className="table-wrap">
          <table className="wrap-head">
            <thead>
              <tr>
                <th>Scenario</th>
                <th className="num">Success</th>
                <th className="num">Legacy, 10th</th>
                <th className="num">Legacy, median</th>
                <th className="num">Legacy, 90th</th>
                <th className="num">Lifetime taxes, median</th>
                <th className="num">Δ legacy, median</th>
                <th className="num">P(legacy higher)</th>
                <th className="num">Δ taxes, median</th>
                <th className="num">Succeeds where baseline fails</th>
                <th className="num">Fails where baseline succeeds</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.scenario}>
                  <td>
                    <Link to={`/runs/${data.runs[i]?.id}`}>{row.scenario}</Link>
                  </td>
                  <td className="num">{percent(row.success_probability)}</td>
                  <td className="num">{compactMoney(row.legacy_after_tax_real.p10)}</td>
                  <td className="num">{compactMoney(row.legacy_after_tax_real.p50)}</td>
                  <td className="num">{compactMoney(row.legacy_after_tax_real.p90)}</td>
                  <td className="num">{compactMoney(row.lifetime_taxes_real.p50)}</td>
                  {i === 0 ? (
                    [0, 1, 2, 3, 4].map((k) => (
                      <td key={k} className="num muted" title="the baseline">
                        –
                      </td>
                    ))
                  ) : (
                    <>
                      <td className="num">{signedMoney(row.vs_first.legacy_after_tax_real_difference.p50)}</td>
                      <td className="num">{percent(row.vs_first.legacy_higher_probability)}</td>
                      <td className="num">{signedMoney(row.vs_first.lifetime_taxes_real_difference.p50)}</td>
                      <td className="num">{percent(row.vs_first.succeeds_where_first_fails)}</td>
                      <td className="num">{percent(row.vs_first.fails_where_first_succeeds)}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {chart ? (
        <LineChart
          title="Median net worth"
          hint="Year-end, today's dollars"
          years={chart.years}
          series={chart.series}
        />
      ) : (
        <Loading what="Loading the chart" />
      )}
    </div>
  );
}

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const profiles = useProfiles();
  const current = useCurrentProfile();
  const profile = params.get("profile") ?? current ?? profiles.data?.[0]?.name ?? "";
  const detail = useProfile(profile || undefined);
  const chosen = params.getAll("scenario");
  const [picked, setPicked] = useState<string[]>(chosen);
  const [sims, setSims] = useState(Number(params.get("sims") ?? 2000));
  const [seed, setSeed] = useState(Number(params.get("seed") ?? 1));
  const submitted = chosen.length >= 2;

  const toggle = (scenario: string) =>
    setPicked((list) =>
      list.includes(scenario)
        ? list.filter((s) => s !== scenario)
        : list.length < MAX_SCENARIOS
          ? [...list, scenario]
          : list,
    );
  const run = () => {
    const next = new URLSearchParams({ profile, sims: String(sims), seed: String(seed) });
    picked.forEach((s) => next.append("scenario", s));
    setParams(next);
  };

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Compare scenarios</h1>
          <div className="subtitle">
            Two to four scenarios on the same simulated markets and lifespans. The first one picked is the baseline.
          </div>
        </div>
      </div>
      <section className="card stack">
        <div className="row">
          <label className="field">
            Profile
            <select
              value={profile}
              onChange={(e) => {
                setPicked([]);
                setParams(new URLSearchParams({ profile: e.target.value }));
              }}
            >
              {profiles.data?.map((p) => (
                <option key={p.name}>{p.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Paths
            <input
              type="number"
              className="number"
              min={100}
              max={100000}
              step={500}
              value={sims}
              onChange={(e) => setSims(Number(e.target.value))}
            />
          </label>
          <label className="field">
            Seed
            <input
              type="number"
              className="number"
              style={{ width: 80 }}
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
            />
          </label>
        </div>
        <div className="row" role="group" aria-label="Scenarios">
          {detail.data?.scenarios.map((scenario) => (
            <label key={scenario} className="inline" style={{ marginRight: 12 }}>
              <input type="checkbox" checked={picked.includes(scenario)} onChange={() => toggle(scenario)} />
              {scenario}
              {picked[0] === scenario && <span className="small muted">(baseline)</span>}
            </label>
          ))}
        </div>
        <div className="row">
          <button className="primary" disabled={picked.length < 2} onClick={run}>
            Compare {picked.length >= 2 ? picked.length : ""} scenarios
          </button>
          {picked.length < 2 && <span className="small muted">Pick at least two.</span>}
        </div>
      </section>
      {submitted && (
        <Comparison
          profile={params.get("profile") ?? profile}
          scenarios={chosen}
          sims={Number(params.get("sims") ?? sims)}
          seed={Number(params.get("seed") ?? seed)}
        />
      )}
    </div>
  );
}
