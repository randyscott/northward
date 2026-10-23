// A thin Plotly wrapper. Plotly loads on first use (it's large). Colors come from the CSS tokens, re-read when the
// color scheme changes, so charts follow light/dark like the rest of the page.
import type { Config, Data, Layout } from "plotly.js";
import { useEffect, useMemo, useRef, useState } from "react";

type PlotlyModule = typeof import("plotly.js-dist-min");
let plotly: Promise<PlotlyModule> | null = null;
const loadPlotly = () => (plotly ??= import("plotly.js-dist-min"));

export interface Theme {
  surface: string;
  text: string;
  secondary: string;
  muted: string;
  grid: string;
  axis: string;
  border: string;
  series: string[];
  font: string;
}

function readTheme(): Theme {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    surface: v("--surface-1") || "#fcfcfb",
    text: v("--text-primary") || "#0b0b0b",
    secondary: v("--text-secondary") || "#52514e",
    muted: v("--text-muted") || "#898781",
    grid: v("--grid") || "#e1e0d9",
    axis: v("--axis") || "#c3c2b7",
    border: v("--border") || "rgba(11,11,11,0.1)",
    series: [1, 2, 3, 4, 5].map((i) => v(`--series-${i}`) || "#2a78d6"),
    font: v("--font") || "system-ui",
  };
}

/** The current chart theme; changes when the OS color scheme does. */
export function useTheme(): Theme {
  const [theme, setTheme] = useState(readTheme);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () => setTheme(readTheme());
    media?.addEventListener?.("change", update);
    return () => media?.removeEventListener?.("change", update);
  }, []);
  return theme;
}

function baseLayout(theme: Theme, layout: Partial<Layout>): Partial<Layout> {
  const axis = {
    gridcolor: theme.grid,
    linecolor: theme.axis,
    zerolinecolor: theme.axis,
    tickfont: { color: theme.muted, size: 11.5 },
    automargin: true,
  };
  return {
    paper_bgcolor: theme.surface,
    plot_bgcolor: theme.surface,
    font: { family: theme.font, color: theme.secondary, size: 12 },
    margin: { l: 8, r: 12, t: 8, b: 8 },
    showlegend: false, // the card renders an HTML legend (text in text tokens)
    hovermode: "x unified",
    hoverlabel: { bgcolor: theme.surface, bordercolor: theme.axis, font: { color: theme.text, family: theme.font } },
    barcornerradius: 4,
    bargap: 0.35,
    ...layout,
    xaxis: {
      ...axis,
      showgrid: false,
      showspikes: true,
      spikemode: "across",
      spikethickness: 1,
      spikecolor: theme.axis,
      spikedash: "solid",
      spikesnap: "data",
      ...layout.xaxis,
    },
    yaxis: { ...axis, tickprefix: "$", tickformat: "~s", ...layout.yaxis },
  } as Partial<Layout>;
}

const CONFIG: Partial<Config> = {
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
};

export function Plot({
  data,
  layout = {},
  height = 320,
  label,
}: {
  data: Data[];
  layout?: Partial<Layout>;
  height?: number;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  const fullLayout = useMemo(() => baseLayout(theme, { height, ...layout }), [theme, layout, height]);

  useEffect(() => {
    let cancelled = false;
    void loadPlotly().then((module) => {
      if (!cancelled && ref.current) void module.default.react(ref.current, data, fullLayout, CONFIG);
    });
    return () => {
      cancelled = true;
    };
  }, [data, fullLayout]);

  useEffect(() => {
    const element = ref.current;
    return () => {
      if (element) void loadPlotly().then((module) => module.default.purge(element));
    };
  }, []);

  return <div ref={ref} className="chart" style={{ minHeight: height }} role="img" aria-label={label} />;
}
