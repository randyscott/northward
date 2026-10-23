"""Text reports and files for Monte Carlo runs and comparisons."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from northward.montecarlo import telemetry
from northward.montecarlo.stats import PERCENTILES
from northward.montecarlo.telemetry import MonteCarloResult

_COLUMNS = [f"p{p}" for p in PERCENTILES]


def _money(value: float) -> str:
    return f"{value:>13,.0f}"


def _percent(value: float) -> str:
    """One decimal, but never rounding a rare outcome away (one failure in 10,000 is ">99.9%", not "100.0%")."""
    if 0 < value < 0.0005:
        return "<0.1%"
    if 0.9995 <= value < 1:
        return ">99.9%"
    return f"{value * 100:.1f}%"


def _table_row(label: str, values: dict[str, float]) -> str:
    return f"{label:<28}" + "".join(_money(values[c]) for c in _COLUMNS)


def _criteria_text(summary: dict[str, Any]) -> str:
    success = summary["success"]["failure_probability"]
    criteria = summary["goals"]["success"]
    parts = []
    if "no_shortfall" in success:
        parts.append(f"short on spending in {_percent(success['no_shortfall'])} of paths")
    if "liquidity_floor" in success:
        floor = criteria["liquidity_floor"]["amount"]
        parts.append(
            f"cash + brokerage below {floor:,.0f} (today $; retirement accounts and HSAs don't count) in "
            f"{_percent(success['liquidity_floor'])}"
        )
    return "; ".join(parts) if parts else "no criteria enabled"


def format_summary(summary: dict[str, Any]) -> str:
    s = summary
    lines = [
        f"Monte Carlo: profile {s['profile']!r}, scenario {s['scenario']!r}: {s['n_sims']:,} paths, seed {s['seed']}, "
        f"preset {s['preset']} ({s['sampler']}), mortality {s['mortality']}",
        f"Probability of success: {_percent(s['success']['probability'])} ({_criteria_text(s)})",
    ]
    failures = s["success"]["first_failure_year"]
    if failures:
        lines.append(
            f"First failure: earliest {min(map(int, failures))}, median {s['success']['median_first_failure_year']}"
        )
    lines += ["", f"{'':<28}" + "".join(f"{c:>13}" for c in _COLUMNS)]
    lines.append(_table_row("Terminal net worth (today $)", s["terminal_net_worth"]["real"]))
    lines.append(_table_row("Legacy after tax (today $)", s["legacy_after_tax"]["real"]))
    lines.append(_table_row("Lifetime taxes (today $)", s["lifetime_taxes"]["real"]))
    if s["mortality"] == "sampled":
        lines.append(f"{'Final year':<28}" + "".join(f"{s['final_year'][c]:>13.0f}" for c in _COLUMNS))
    if "bands" in s:
        band = s["bands"]["net_worth"]["real"]
        lines += [
            "",
            "Net worth by year (today $):",
            f"{'Year':>6}{'Paths':>7}" + "".join(f"{c:>13}" for c in _COLUMNS),
        ]
        last = len(s["years"]) - 1
        for i, year in enumerate(s["years"]):
            if i % 5 and i != last:
                continue
            lines.append(f"{year:>6}{s['paths_running'][i]:>7}" + "".join(_money(band[c][i]) for c in _COLUMNS))
    paths = ", ".join(f"{p} #{i}" for p, i in s["representative_paths"].items())
    lines += ["", f"Paths by after-tax legacy: {paths}  (drill down: northward run --path N --seed {s['seed']})"]
    return "\n".join(lines)


def band_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for bucket, bases in summary["bands"].items():
        for basis, columns in bases.items():
            for i, year in enumerate(summary["years"]):
                rows.append({"year": year, "bucket": bucket, "basis": basis, **{c: columns[c][i] for c in _COLUMNS}})
    return rows


def write_outputs(mc: MonteCarloResult, summary: dict[str, Any], out_dir: Path) -> list[Path]:
    """telemetry.npz (raw arrays), summary.json (statistics without bands), and bands.csv."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [telemetry.save(mc, out_dir / "telemetry.npz")]
    path = out_dir / "summary.json"
    path.write_text(json.dumps({k: v for k, v in summary.items() if k != "bands"}, indent=1))
    written.append(path)
    if "bands" in summary:
        path = out_dir / "bands.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["year", "bucket", "basis", *_COLUMNS])
            writer.writeheader()
            writer.writerows(band_rows(summary))
        written.append(path)
    return written


def format_comparison(comparison: dict[str, Any]) -> str:
    rows = comparison["scenarios"]
    width = max(12, *(len(r["scenario"]) for r in rows)) + 2
    lines = [
        f"Scenario comparison: {comparison['n_sims']:,} paths each, seed {comparison['seed']} (the same draws for every "
        f"scenario); differences are path by path against {rows[0]['scenario']!r}.",
        "",
        f"{'Scenario':<{width}}{'Success':>9}{'Legacy p10':>14}{'Legacy p50':>14}{'Legacy p90':>14}{'Taxes p50':>14}"
        f"{'Δ legacy p50':>15}{'P(legacy ↑)':>13}{'Δ taxes p50':>14}",
    ]
    for r in rows:
        legacy, vs = r["legacy_after_tax_real"], r["vs_first"]
        lines.append(
            f"{r['scenario']:<{width}}{_percent(r['success_probability']):>9}"
            f"{legacy['p10']:>14,.0f}{legacy['p50']:>14,.0f}{legacy['p90']:>14,.0f}"
            f"{r['lifetime_taxes_real']['p50']:>14,.0f}"
            f"{vs['legacy_after_tax_real_difference']['p50']:>15,.0f}{_percent(vs['legacy_higher_probability']):>13}"
            f"{vs['lifetime_taxes_real_difference']['p50']:>14,.0f}"
        )
    lines += [
        "",
        "Legacy is net worth at the end, less the heirs' tax on pre-tax accounts; all amounts in today's dollars.",
    ]
    for r in rows[1:]:
        vs = r["vs_first"]
        lines.append(
            f"{r['scenario']}: succeeds where {rows[0]['scenario']} fails in {_percent(vs['succeeds_where_first_fails'])} "
            f"of paths, fails where it succeeds in {_percent(vs['fails_where_first_succeeds'])}."
        )
    return "\n".join(lines)
