import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type GoalOverrides, type Percentiles, type RunOut, unwrap } from "../api/client";
import { isActive, keys, usePath, useResults, useRun, useYears } from "../api/hooks";
import { ConeChart } from "../components/charts";
import { ErrorNotice, Loading, ProgressBar, StatusBadge, Tile } from "../components/common";
import { type Basis, LedgerTable, PathCharts, YearTable } from "../components/runViews";
import { compactMoney, dateTime, percent } from "../lib/format";

const PERCENTILES = ["p10", "p25", "p50", "p75", "p90"] as const;
const PERCENTILE_LABEL: Record<keyof Percentiles, string> = {
  p10: "10th percentile",
  p25: "25th percentile",
  p50: "Median",
  p75: "75th percentile",
  p90: "90th percentile",
};

function BasisToggle({ basis, onChange }: { basis: Basis; onChange: (b: Basis) => void }) {
  return (
    <div className="segmented" role="group" aria-label="Dollars">
      {(["real", "nominal"] as const).map((b) => (
        <button key={b} type="button" className={basis === b ? "selected" : ""} onClick={() => onChange(b)}>
          {b === "real" ? "Today's dollars" : "Nominal"}
        </button>
      ))}
    </div>
  );
}

function useDebounced<T>(value: T, ms = 400): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function range(p: Percentiles): string {
  return `${compactMoney(p.p10)} – ${compactMoney(p.p90)} (10th–90th)`;
}

function MonteCarloDashboard({ run }: { run: RunOut }) {
  const [basis, setBasis] = useState<Basis>("real");
  const [allowShortfall, setAllowShortfall] = useState(false);
  const [floor, setFloor] = useState("");
  const [heirs, setHeirs] = useState("");
  const [choice, setChoice] = useState<keyof Percentiles | "custom">("p50");
  const [custom, setCustom] = useState(0);

  const goals = useDebounced<GoalOverrides>({
    ...(allowShortfall ? { allow_shortfall: true } : {}),
    ...(floor.trim() !== "" && !Number.isNaN(Number(floor)) ? { liquidity_floor: Number(floor) } : {}),
    ...(heirs.trim() !== "" && !Number.isNaN(Number(heirs)) ? { heirs_tax_rate: Number(heirs) / 100 } : {}),
  });
  const results = useResults(run.id, goals, true, ["net_worth"]);
  const data = results.data;
  const pathIndex = data ? (choice === "custom" ? custom : data.representative_paths[choice]) : null;
  const path = usePath(run.id, pathIndex);
  const pathYears = useMemo(() => path.data?.years.map((row) => row.year as number) ?? [], [path.data]);

  if (results.isPending) return <Loading what="Computing results" />;
  if (results.error) return <ErrorNotice error={results.error} />;
  if (!data) return null;
  const success = data.success;
  const floorGoal = data.goals.success.liquidity_floor;
  const band = data.bands?.net_worth?.[basis];
  const failures = Object.entries(success.failure_probability);

  return (
    <div className="stack">
      <div className="row card" style={{ padding: "10px 16px" }} aria-label="Filters">
        <BasisToggle basis={basis} onChange={setBasis} />
        <span className="spacer" />
        <span className="small secondary">Success criteria (no rerun needed):</span>
        <label className="inline small">
          <input type="checkbox" checked={allowShortfall} onChange={(e) => setAllowShortfall(e.target.checked)} />
          Allow spending shortfalls
        </label>
        <label
          className="inline small"
          title="Year-end cash plus brokerage, in today's dollars. Retirement accounts and HSAs don't count."
        >
          Cash + brokerage floor
          <input
            className="number"
            style={{ width: 110 }}
            inputMode="decimal"
            placeholder={floorGoal ? String(floorGoal.amount) : "none"}
            value={floor}
            onChange={(e) => setFloor(e.target.value)}
            aria-label="Cash + brokerage floor, today's dollars (0 turns it off)"
          />
        </label>
        <label className="inline small">
          Heirs' tax rate %
          <input
            className="number"
            style={{ width: 64 }}
            inputMode="decimal"
            placeholder={String(Math.round(data.goals.legacy.heirs_tax_rate * 100))}
            value={heirs}
            onChange={(e) => setHeirs(e.target.value)}
            aria-label="Heirs' tax rate, percent"
          />
        </label>
      </div>

      <div
        className={`grid-2 ${results.isFetching ? "refreshing" : ""}`}
        style={{ gridTemplateColumns: "minmax(260px, 1fr) minmax(0, 2fr)" }}
      >
        <section className="card">
          <div className="secondary">Probability of success</div>
          <div className="hero" data-testid="success-probability">
            {percent(success.probability)}
          </div>
          <div className="small secondary" style={{ marginTop: 6 }}>
            of {data.n_sims.toLocaleString()} paths{" "}
            {[
              data.goals.success.no_shortfall ? "never ran short on spending" : null,
              floorGoal ? `kept cash + brokerage above ${compactMoney(floorGoal.amount)}` : null,
            ]
              .filter(Boolean)
              .join(" and ") || "(no criteria: every path succeeds)"}
          </div>
          {failures.length > 0 && (
            <table style={{ marginTop: 12 }}>
              <tbody>
                {failures.map(([criterion, rate]) => (
                  <tr key={criterion}>
                    <td className="secondary" style={{ whiteSpace: "normal" }}>
                      {criterion === "no_shortfall" ? (
                        "Ran short on spending"
                      ) : (
                        <>
                          Cash + brokerage fell below {compactMoney(floorGoal?.amount)}
                          <div className="small muted">Retirement accounts and HSAs don't count toward the floor</div>
                        </>
                      )}
                    </td>
                    <td className="num">{percent(rate)}</td>
                  </tr>
                ))}
                {success.median_first_failure_year && (
                  <tr>
                    <td className="secondary">Median first failing year</td>
                    <td className="num">{success.median_first_failure_year}</td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </section>
        <div className="grid-tiles">
          <Tile
            label="After-tax legacy, median"
            value={compactMoney(data.legacy_after_tax[basis].p50)}
            detail={range(data.legacy_after_tax[basis])}
          />
          <Tile
            label="Final net worth, median"
            value={compactMoney(data.terminal_net_worth[basis].p50)}
            detail={range(data.terminal_net_worth[basis])}
          />
          <Tile
            label="Lifetime taxes, median"
            value={compactMoney(data.lifetime_taxes[basis].p50)}
            detail={range(data.lifetime_taxes[basis])}
          />
          <Tile
            label="Market"
            value={<span style={{ fontSize: 16 }}>{data.preset.replace(/_/g, " ")}</span>}
            detail={`${data.sampler} · mortality ${data.mortality} · seed ${data.seed}`}
          />
        </div>
      </div>

      {band && (
        <ConeChart
          title="Net worth"
          hint={`Year-end, ${basis === "real" ? "today's dollars" : "nominal dollars"}, across all paths`}
          years={data.years}
          band={band}
          busy={results.isFetching}
        />
      )}

      <section className="card row" aria-label="Path">
        <h2>One path in detail</h2>
        <select
          aria-label="Path to show"
          value={choice}
          onChange={(e) => setChoice(e.target.value as keyof Percentiles | "custom")}
        >
          {PERCENTILES.map((p) => (
            <option key={p} value={p}>
              {PERCENTILE_LABEL[p]} path by after-tax legacy (#{data.representative_paths[p]})
            </option>
          ))}
          <option value="custom">A path by number…</option>
        </select>
        {choice === "custom" && (
          <input
            type="number"
            className="number"
            min={0}
            max={data.n_sims - 1}
            value={custom}
            onChange={(e) => setCustom(Math.min(data.n_sims - 1, Math.max(0, Number(e.target.value))))}
            aria-label="Path number"
          />
        )}
        <span className="small muted">Re-run on the run's own inputs, with the full ledger.</span>
      </section>
      <ErrorNotice error={path.error} />
      {path.data && (
        <>
          <PathCharts years={pathYears} buckets={path.data.buckets} basis={basis} busy={path.isFetching} />
          <YearTable rows={path.data.years} />
          <LedgerTable key={path.data.path} rows={path.data.ledger} />
        </>
      )}
    </div>
  );
}

function DeterministicView({ run }: { run: RunOut }) {
  const [basis, setBasis] = useState<Basis>("real");
  const years = useYears(run.id);
  const summary = (run.summary ?? {}) as {
    final_net_worth?: number;
    final_net_worth_real?: number;
    lifetime_taxes?: number;
    shortfall_years?: number[];
    end_year?: number;
  };
  const rows = years.data?.years ?? [];
  const yearList = useMemo(() => rows.map((row) => row.year as number), [rows]);
  if (years.isPending) return <Loading />;
  if (years.error) return <ErrorNotice error={years.error} />;
  const shortfalls = summary.shortfall_years ?? [];
  return (
    <div className="stack">
      <div className="row">
        <BasisToggle basis={basis} onChange={setBasis} />
      </div>
      <div className="grid-tiles">
        <Tile
          label={`Net worth in ${summary.end_year}`}
          value={compactMoney(summary.final_net_worth_real)}
          detail={`today's dollars (${compactMoney(summary.final_net_worth)} nominal)`}
        />
        <Tile label="Lifetime taxes" value={compactMoney(summary.lifetime_taxes)} detail="nominal" />
        <Tile
          label="Years short on spending"
          value={shortfalls.length}
          detail={shortfalls.length ? shortfalls.slice(0, 6).join(", ") : "none"}
        />
      </div>
      {years.data!.warnings.length > 0 && (
        <div className="notice">
          <div className="secondary">Notes from the simulation</div>
          <ul>
            {years.data!.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      <PathCharts years={yearList} buckets={years.data!.buckets} basis={basis} />
      <YearTable rows={rows} />
      <LedgerTable rows={years.data!.ledger} />
    </div>
  );
}

export function RunPage() {
  const id = Number(useParams().runId);
  const run = useRun(id);
  const queryClient = useQueryClient();
  const [showInputs, setShowInputs] = useState(false);
  const cancel = useMutation({
    mutationFn: () => unwrap(api.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keys.run(id) }),
  });

  if (run.isPending) return <Loading />;
  if (run.error) return <ErrorNotice error={run.error} />;
  const data = run.data!;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="crumbs">
            <Link to="/runs">Runs</Link> / #{data.id}
          </div>
          <h1>
            <Link to={`/profiles/${data.profile}/scenarios/${data.scenario}`}>
              {data.profile}/{data.scenario}
            </Link>
          </h1>
          <div className="subtitle row">
            <StatusBadge status={data.status} />
            <span>
              {data.kind === "monte_carlo"
                ? `Monte Carlo · ${data.n_sims?.toLocaleString()} paths · seed ${data.seed}`
                : "Deterministic"}
            </span>
            <span className="muted">
              started {dateTime(data.created_at)}
              {data.elapsed_seconds !== null && ` · ${data.elapsed_seconds.toFixed(1)} s`}
            </span>
            <button className="link small" onClick={() => setShowInputs((v) => !v)}>
              {showInputs ? "Hide inputs" : "Inputs"}
            </button>
          </div>
        </div>
      </div>

      {showInputs && (
        <section className="card small">
          <div className="secondary" style={{ marginBottom: 6 }}>
            Pinned revisions (a rerun uses exactly these) · engine <span className="mono">{data.engine_version}</span>
          </div>
          <div style={{ columns: 3 }}>
            {data.revisions.map(([doc, revision]) => (
              <div key={doc} className="mono">
                {doc} @ {revision}
              </div>
            ))}
          </div>
        </section>
      )}

      {isActive(data) && (
        <section className="card stack">
          <div className="row">
            <span>{data.status === "queued" ? "Waiting for another run to finish…" : "Simulating…"}</span>
            <span className="spacer" />
            <button className="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              Cancel run
            </button>
          </div>
          {data.progress && <ProgressBar done={data.progress.done} total={data.progress.total} />}
          <ErrorNotice error={cancel.error} />
        </section>
      )}
      {data.status === "failed" && <ErrorNotice error={new Error(data.error ?? "failed")} title="This run failed" />}
      {data.status === "complete" &&
        (data.kind === "monte_carlo" ? <MonteCarloDashboard run={data} /> : <DeterministicView run={data} />)}
    </div>
  );
}
