// Views of one simulated path (a Monte Carlo path or the deterministic run): charts from its telemetry buckets,
// the year-by-year table, and the transaction ledger.
import { useMemo, useState } from "react";

import { cell, money } from "../lib/format";
import { type Series, StackedColumns } from "./charts";

export type Basis = "real" | "nominal";

type Buckets = Record<string, (number | null)[]>;

/** A bucket in the chosen basis: nominal as simulated, or real (today's dollars) by dividing by the price level. */
export function inBasis(buckets: Buckets, name: string, basis: Basis): (number | null)[] {
  const values = buckets[name] ?? [];
  if (basis === "nominal") return values;
  const prices = buckets.price_level ?? [];
  return values.map((v, i) => (v === null || !prices[i] ? null : v / prices[i]!));
}

/** Income that isn't wages, Social Security, pensions, or RMDs (investment income, other streams, inherited IRAs). */
function otherIncome(buckets: Buckets, basis: Basis): (number | null)[] {
  const parts = ["wages", "social_security", "pensions", "rmds"].map((name) => inBasis(buckets, name, basis));
  return inBasis(buckets, "income", basis).map((total, i) =>
    total === null ? null : Math.max(0, total - parts.reduce((sum, part) => sum + (part[i] ?? 0), 0)),
  );
}

function seriesOf(buckets: Buckets, basis: Basis, names: [string, string][]): Series[] {
  return names.map(([name, label]) => ({ name: label, values: inBasis(buckets, name, basis) }));
}

const BALANCES: [string, string][] = [
  ["taxable", "Taxable (cash & brokerage)"],
  ["deferred", "Tax-deferred"],
  ["roth", "Roth"],
  ["hsa", "HSA"],
  ["education", "529"],
];
const TAX_TYPES: [string, string][] = [
  ["federal_tax", "Federal income"],
  ["state_tax", "State income"],
  ["fica", "Payroll (FICA)"],
];
const INCOME_SOURCES: [string, string][] = [
  ["wages", "Wages"],
  ["social_security", "Social Security"],
  ["pensions", "Pensions"],
  ["rmds", "RMDs"],
];

export function PathCharts({
  years,
  buckets,
  basis,
  busy,
}: {
  years: number[];
  buckets: Buckets;
  basis: Basis;
  busy?: boolean;
}) {
  const unit = basis === "real" ? "today's dollars" : "nominal dollars";
  const balances = useMemo(() => seriesOf(buckets, basis, BALANCES), [buckets, basis]);
  const taxes = useMemo(() => seriesOf(buckets, basis, TAX_TYPES), [buckets, basis]);
  const income = useMemo(
    () => [...seriesOf(buckets, basis, INCOME_SOURCES), { name: "Other", values: otherIncome(buckets, basis) }],
    [buckets, basis],
  );
  return (
    <div className="stack">
      <StackedColumns
        title="Balances by account type"
        hint={`Year-end, ${unit}`}
        years={years}
        series={balances}
        busy={busy}
      />
      <div className="grid-2">
        <StackedColumns
          title="Taxes by type"
          hint={`Per year, ${unit}`}
          years={years}
          series={taxes}
          busy={busy}
          height={280}
        />
        <StackedColumns
          title="Income by source"
          hint={`Per year, ${unit}`}
          years={years}
          series={income}
          busy={busy}
          height={280}
        />
      </div>
    </div>
  );
}

const SUMMARY = [
  "reserve_drawn",
  "reserve_topped_up",
  "net_worth",
  "net_worth_today",
  "total_assets",
  "total_liabilities",
  "spending",
  "debt_payments",
  "total_taxes",
  "shortfall",
  "swept",
];
const INCOME = [
  "gross_wages",
  "social_security",
  "child_benefits",
  "pension_income",
  "rmds",
  "inherited_distributions",
  "roth_conversions",
  "other_income",
  "investment_income",
  "event_inflows",
  "plan_529_qualified",
  "withdrawals_taxable",
  "withdrawals_deferred",
  "withdrawals_roth",
  "withdrawals_hsa",
  "realized_gains",
];
const TAXES = [
  "filing_status",
  "agi",
  "taxable_social_security",
  "capital_gains",
  "standard_deduction",
  "senior_deduction",
  "taxable_income",
  "ordinary_tax",
  "capital_gains_tax",
  "nonrefundable_credits",
  "refundable_credits",
  "income_tax",
  "net_investment_income_tax",
  "social_security_tax",
  "medicare_tax",
  "additional_taxes",
  "state_income",
  "state_tax",
  "marginal_rate",
  "effective_rate",
  "total_taxes",
];

const GROUPS: Record<string, (column: string) => boolean> = {
  Summary: (c) => SUMMARY.includes(c),
  Income: (c) => INCOME.includes(c),
  Taxes: (c) => TAXES.includes(c),
  Balances: (c) => c.startsWith("balance_") || c.startsWith("loan_"),
  Spending: (c) => c.startsWith("spending_") || c === "spending",
  All: () => true,
};

const label = (column: string) => column.replace(/_/g, " ");

export function YearTable({ rows }: { rows: Record<string, unknown>[] }) {
  const [group, setGroup] = useState("Summary");
  const all = Object.keys(rows[0] ?? {});
  const fixed = all.filter((c) => c === "year" || c.startsWith("age_"));
  const columns = [...fixed, ...all.filter((c) => !fixed.includes(c) && GROUPS[group]!(c))];
  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h3>Year by year</h3>
          <div className="hint">Nominal dollars, except “net worth today”</div>
        </div>
        <div className="segmented" role="group" aria-label="Columns">
          {Object.keys(GROUPS).map((g) => (
            <button key={g} type="button" className={g === group ? "selected" : ""} onClick={() => setGroup(g)}>
              {g}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap tall">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} className={c === "year" || c === "filing_status" ? "" : "num"}>
                  {label(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} className={c === "year" || c === "filing_status" ? "" : "num"}>
                    {cell(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface LedgerRow {
  year: number;
  source: string;
  dest: string;
  amount: number;
  description: string;
  tax_category: string;
  member?: string | null;
}

const LEDGER_LIMIT = 500;

export function LedgerTable({ rows }: { rows: Record<string, unknown>[] }) {
  const ledger = rows as unknown as LedgerRow[];
  const years = useMemo(() => [...new Set(ledger.map((r) => r.year))], [ledger]);
  const categories = useMemo(() => [...new Set(ledger.map((r) => r.tax_category))].sort(), [ledger]);
  const [year, setYear] = useState<string>(String(years[0] ?? ""));
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const needle = search.trim().toLowerCase();
  const shown = ledger.filter(
    (r) =>
      (!year || String(r.year) === year) &&
      (!category || r.tax_category === category) &&
      (!needle || `${r.source} ${r.dest} ${r.description}`.toLowerCase().includes(needle)),
  );
  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h3>Ledger</h3>
          <div className="hint">Every movement of money, in nominal dollars</div>
        </div>
        <div className="row">
          <select aria-label="Ledger year" value={year} onChange={(e) => setYear(e.target.value)}>
            <option value="">All years</option>
            {years.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
          <select aria-label="Ledger category" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All tax categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {label(c)}
              </option>
            ))}
          </select>
          <input
            aria-label="Search the ledger"
            placeholder="Search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <div className="table-wrap tall">
        <table>
          <thead>
            <tr>
              <th>Year</th>
              <th>From</th>
              <th>To</th>
              <th className="num">Amount</th>
              <th>Description</th>
              <th>Tax category</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, LEDGER_LIMIT).map((r, i) => (
              <tr key={i}>
                <td>{r.year}</td>
                <td className="mono">{r.source}</td>
                <td className="mono">{r.dest}</td>
                <td className="num">{money(r.amount)}</td>
                <td>{r.description}</td>
                <td className="secondary">{label(r.tax_category)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="small muted" style={{ marginTop: 6 }}>
        {shown.length > LEDGER_LIMIT
          ? `Showing ${LEDGER_LIMIT} of ${shown.length} entries; narrow the filters to see the rest.`
          : `${shown.length} entries`}
      </div>
    </section>
  );
}
