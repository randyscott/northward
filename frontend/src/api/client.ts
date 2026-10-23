// The typed API client. Types come from the backend's OpenAPI schema (`make api-types`), so a backend change that
// breaks the frontend fails `npm run typecheck`.
import createClient from "openapi-fetch";
import type { Readable } from "openapi-typescript-helpers";

import type { components, paths } from "./schema";

// As openapi-fetch delivers them (its `Readable` view of each schema), so these match the responses exactly.
export type Schemas = { [Name in keyof components["schemas"]]: Readable<components["schemas"][Name]> };
export type Issue = Schemas["Issue"];
export type RunOut = Schemas["RunOut"];
export type ProfileOut = Schemas["ProfileOut"];
export type ProfileDetail = Schemas["ProfileDetail"];
export type DocumentOut = Schemas["DocumentOut"];
export type DocumentDetail = Schemas["DocumentDetail"];
export type RevisionOut = Schemas["RevisionOut"];
export type ScenarioOut = Schemas["ScenarioOut"];
export type YearsOut = Schemas["YearsOut"];
export type PathOut = Schemas["PathOut"];
export type CompareOut = Schemas["CompareOut"];
export type Content = Schemas["Content"];

export const api = createClient<paths>({ baseUrl: "" });

/** A failed request: the server's message and, for configuration problems (422), their issues. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly issues: Issue[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorMessage(body: unknown, status: number): { message: string; issues: Issue[] } {
  if (body && typeof body === "object" && "detail" in body) {
    const { detail, issues: raw } = body as { detail: unknown; issues?: unknown };
    const issues = Array.isArray(raw) ? (raw as Issue[]) : [];
    if (typeof detail === "string") return { message: detail, issues };
    if (Array.isArray(detail)) {
      // FastAPI's own request validation: [{loc, msg}, ...]
      const parts = detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg}`);
      return { message: parts.join("; "), issues: [] };
    }
  }
  return { message: `request failed (${status})`, issues: [] };
}

/** The data of an openapi-fetch response, or an ApiError. */
export async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await request;
  if (error !== undefined || !response.ok) {
    const { message, issues } = errorMessage(error, response.status);
    throw new ApiError(message, response.status, issues);
  }
  return data as T;
}

/** Monte Carlo statistics (`GET /api/runs/{id}/results`); the endpoint returns a plain JSON object. */
export type Percentiles = { p10: number; p25: number; p50: number; p75: number; p90: number };
export type Band = Record<keyof Percentiles, (number | null)[]>;
export interface Results {
  profile: string;
  scenario: string;
  seed: number;
  n_sims: number;
  preset: string;
  sampler: string;
  mortality: string;
  years: number[];
  goals: {
    success: {
      no_shortfall: boolean;
      shortfall_tolerance: number;
      liquidity_floor: { amount: number; start: unknown } | null;
    };
    legacy: { heirs_tax_rate: number };
  };
  success: {
    probability: number;
    failure_probability: Record<string, number>;
    first_failure_year: Record<string, number>;
    median_first_failure_year: number | null;
  };
  terminal_net_worth: { nominal: Percentiles; real: Percentiles };
  legacy_after_tax: { nominal: Percentiles; real: Percentiles };
  lifetime_taxes: { nominal: Percentiles; real: Percentiles };
  paths_running: number[];
  representative_paths: Record<keyof Percentiles, number>;
  bands?: Record<string, { nominal: Band; real?: Band }>;
}

export interface GoalOverrides {
  allow_shortfall?: boolean;
  liquidity_floor?: number;
  heirs_tax_rate?: number;
}
