// Chart cards. Every chart has an HTML legend (two or more series) and a table view of the same numbers, since a
// tooltip must never be the only way to read a value (and three light-mode series colors are under 3:1 contrast).
import type { Data } from "plotly.js";
import { type ReactNode, useMemo, useState } from "react";

import type { Band } from "../api/client";
import { cell } from "../lib/format";
import { Plot, type Theme, useTheme } from "./Plot";

export interface Series {
  name: string;
  values: (number | null)[];
}

interface LegendKey {
  label: string;
  color: string;
  shape: "swatch" | "line" | "wash";
}

export function Legend({ keys }: { keys: LegendKey[] }) {
  return (
    <div className="legend">
      {keys.map((key) => (
        <span className="key" key={key.label}>
          <span
            className={key.shape === "line" ? "line-key" : "swatch"}
            style={{ background: key.color, opacity: key.shape === "wash" ? 0.35 : 1 }}
            aria-hidden
          />
          {key.label}
        </span>
      ))}
    </div>
  );
}

export function ChartCard({
  title,
  hint,
  legend,
  columns,
  rows,
  busy,
  children,
}: {
  title: string;
  hint?: ReactNode;
  legend?: LegendKey[];
  columns: string[];
  rows: (string | number | null)[][];
  busy?: boolean;
  children: ReactNode;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <section className={`card ${busy ? "refreshing" : ""}`} aria-label={title}>
      <div className="card-header">
        <div>
          <h3>{title}</h3>
          {hint && <div className="hint">{hint}</div>}
        </div>
        <div className="segmented" role="group" aria-label={`${title} view`}>
          {(["chart", "table"] as const).map((v) => (
            <button key={v} type="button" className={view === v ? "selected" : ""} onClick={() => setView(v)}>
              {v === "chart" ? "Chart" : "Table"}
            </button>
          ))}
        </div>
      </div>
      {legend && legend.length > 1 && view === "chart" && <Legend keys={legend} />}
      {view === "chart" ? (
        children
      ) : (
        <div className="table-wrap tall">
          <table>
            <thead>
              <tr>
                {columns.map((c, i) => (
                  <th key={c} className={i ? "num" : ""}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>
                  {row.map((value, i) => (
                    <td key={i} className={i ? "num" : ""}>
                      {i === 0 ? String(value) : typeof value === "number" ? cell(value) : (value ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function wash(color: string, alpha: number): string {
  if (!color.startsWith("#") || color.length !== 7) return color;
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const PERCENTILE_NAMES = { p90: "90th percentile", p75: "75th", p50: "Median", p25: "25th", p10: "10th percentile" };

function coneTraces(years: number[], band: Band, theme: Theme): Data[] {
  const color = theme.series[0]!;
  const edge = (key: keyof Band, fill: "none" | "tonexty", alpha: number): Data => ({
    x: years,
    y: band[key],
    name: PERCENTILE_NAMES[key],
    type: "scatter",
    mode: "lines",
    line: { width: 0, color },
    fill,
    fillcolor: wash(color, alpha),
    hovertemplate: "%{y:$,.0f}",
  });
  return [
    edge("p10", "none", 0),
    edge("p90", "tonexty", 0.1),
    edge("p25", "none", 0),
    edge("p75", "tonexty", 0.16),
    {
      x: years,
      y: band.p50,
      name: PERCENTILE_NAMES.p50,
      type: "scatter",
      mode: "lines",
      line: { width: 2, color, shape: "linear" },
      hovertemplate: "%{y:$,.0f}",
    },
  ];
}

/** Percentile cone: 10th–90th and 25th–75th washes around the median line. */
export function ConeChart({
  title,
  hint,
  years,
  band,
  busy,
}: {
  title: string;
  hint?: ReactNode;
  years: number[];
  band: Band;
  busy?: boolean;
}) {
  const theme = useTheme();
  const data = useMemo(() => coneTraces(years, band, theme), [years, band, theme]);
  const color = theme.series[0]!;
  return (
    <ChartCard
      title={title}
      hint={hint}
      busy={busy}
      legend={[
        { label: "Median", color, shape: "line" },
        { label: "25th–75th percentile", color: wash(color, 0.5), shape: "swatch" },
        { label: "10th–90th percentile", color: wash(color, 0.25), shape: "swatch" },
      ]}
      columns={["Year", "10th", "25th", "Median", "75th", "90th"]}
      rows={years.map((year, i) => [
        year,
        band.p10[i] ?? null,
        band.p25[i] ?? null,
        band.p50[i] ?? null,
        band.p75[i] ?? null,
        band.p90[i] ?? null,
      ])}
    >
      <Plot data={data} label={title} />
    </ChartCard>
  );
}

/** Stacked columns of a few series over the years, colored by fixed slot order. */
export function StackedColumns({
  title,
  hint,
  years,
  series,
  busy,
  height,
}: {
  title: string;
  hint?: ReactNode;
  years: number[];
  series: Series[];
  busy?: boolean;
  height?: number;
}) {
  const theme = useTheme();
  const shown = series.filter((s) => s.values.some((v) => v !== null && Math.abs(v) > 0.5));
  const data = useMemo<Data[]>(
    () =>
      series.map((s, i) => ({
        x: years,
        y: s.values,
        name: s.name,
        type: "bar",
        marker: { color: theme.series[i % theme.series.length], line: { color: theme.surface, width: 1 } },
        hovertemplate: "%{y:$,.0f}",
        visible: shown.includes(s) ? true : false,
      })),
    [years, series, shown, theme],
  );
  return (
    <ChartCard
      title={title}
      hint={hint}
      busy={busy}
      legend={series
        .map((s, i) => ({ label: s.name, color: theme.series[i % theme.series.length]!, shape: "swatch" as const }))
        .filter((_, i) => shown.includes(series[i]!))}
      columns={["Year", ...shown.map((s) => s.name), "Total"]}
      rows={years.map((year, i) => {
        const values = shown.map((s) => s.values[i] ?? null);
        return [year, ...values, values.reduce<number>((sum, v) => sum + (v ?? 0), 0)];
      })}
    >
      <Plot data={data} layout={{ barmode: "stack" }} label={title} height={height} />
    </ChartCard>
  );
}

/** A few lines on one axis (e.g. each scenario's median), colored by fixed slot order. */
export function LineChart({
  title,
  hint,
  years,
  series,
  busy,
}: {
  title: string;
  hint?: ReactNode;
  years: number[];
  series: Series[];
  busy?: boolean;
}) {
  const theme = useTheme();
  const data = useMemo<Data[]>(
    () =>
      series.map((s, i) => ({
        x: years,
        y: s.values,
        name: s.name,
        type: "scatter",
        mode: "lines",
        line: { width: 2, color: theme.series[i % theme.series.length] },
        hovertemplate: "%{y:$,.0f}",
      })),
    [years, series, theme],
  );
  return (
    <ChartCard
      title={title}
      hint={hint}
      busy={busy}
      legend={series.map((s, i) => ({ label: s.name, color: theme.series[i % theme.series.length]!, shape: "line" }))}
      columns={["Year", ...series.map((s) => s.name)]}
      rows={years.map((year, i) => [year, ...series.map((s) => s.values[i] ?? null)])}
    >
      <Plot data={data} label={title} />
    </ChartCard>
  );
}
