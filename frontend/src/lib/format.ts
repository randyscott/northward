// Number formatting. Compact money for tiles and axes ($1.2M), full for tables ($1,234,567).

const full = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function money(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "–" : full.format(value);
}

export function compactMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${sign}$${trim(abs / 1e9)}B`;
  if (abs >= 1e6) return `${sign}$${trim(abs / 1e6)}M`;
  if (abs >= 1e3) return `${sign}$${trim(abs / 1e3)}K`;
  return `${sign}$${Math.round(abs)}`;
}

function trim(value: number): string {
  return value >= 100
    ? value.toFixed(0)
    : value >= 10
      ? value.toFixed(1).replace(/\.0$/, "")
      : value.toFixed(2).replace(/\.?0+$/, "");
}

export function percent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined || Number.isNaN(value) ? "–" : `${(value * 100).toFixed(digits)}%`;
}

export function signedMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return `${value > 0 ? "+" : ""}${compactMoney(value)}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** A table cell: numbers get thousands separators (money-like columns no decimals), the rest as text. */
export function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") {
    if (Number.isInteger(value) && Math.abs(value) < 3000) return String(value); // years, ages, counts
    return Math.abs(value) < 10 ? value.toFixed(4).replace(/\.?0+$/, "") : Math.round(value).toLocaleString("en-US");
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
