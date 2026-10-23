// Data hooks over the API. Query keys start with the resource name, so a mutation can invalidate e.g. everything
// about one profile with ["profile", name].
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, type GoalOverrides, type Results, type RunOut, unwrap } from "./client";

const ACTIVE = new Set(["queued", "running"]);

export const keys = {
  profiles: (deleted = false) => ["profiles", deleted] as const,
  profile: (name: string) => ["profile", name] as const,
  document: (profile: string, address: string) => ["profile", profile, "document", address] as const,
  revisions: (documentId: number) => ["revisions", documentId] as const,
  runs: (filters: object = {}) => ["runs", filters] as const,
  run: (id: number) => ["run", id] as const,
};

export function useProfiles(deleted = false) {
  return useQuery({
    queryKey: keys.profiles(deleted),
    queryFn: () => unwrap(api.GET("/api/profiles", { params: { query: { deleted } } })),
  });
}

export function useProfile(name: string | undefined, deleted = false) {
  return useQuery({
    queryKey: [...keys.profile(name ?? ""), deleted],
    queryFn: () =>
      unwrap(api.GET("/api/profiles/{profile}", { params: { path: { profile: name! }, query: { deleted } } })),
    enabled: !!name,
  });
}

export function useDocument(profile: string, address: string) {
  return useQuery({
    queryKey: keys.document(profile, address),
    queryFn: () =>
      unwrap(api.GET("/api/profiles/{profile}/documents/{address}", { params: { path: { profile, address } } })),
    retry: false, // a 404 means "not created yet", which the page handles
  });
}

export function useRevisions(documentId: number | null | undefined) {
  return useQuery({
    queryKey: keys.revisions(documentId ?? 0),
    queryFn: () =>
      unwrap(api.GET("/api/documents/{document_id}/revisions", { params: { path: { document_id: documentId! } } })),
    enabled: !!documentId,
  });
}

export function useRevision(documentId: number | null | undefined, revision: number | null) {
  return useQuery({
    queryKey: ["revision", documentId, revision],
    queryFn: () =>
      unwrap(
        api.GET("/api/documents/{document_id}/revisions/{revision}", {
          params: { path: { document_id: documentId!, revision: revision! } },
        }),
      ),
    enabled: !!documentId && !!revision,
    staleTime: Infinity, // revisions never change
  });
}

export function useRuns(filters: { profile?: string; scenario?: string; kind?: string; limit?: number } = {}) {
  return useQuery({
    queryKey: keys.runs(filters),
    queryFn: () => unwrap(api.GET("/api/runs", { params: { query: filters } })),
    refetchInterval: (query) => (query.state.data?.some((r) => ACTIVE.has(r.status)) ? 1500 : false),
  });
}

export function isActive(run: Pick<RunOut, "status"> | undefined): boolean {
  return !!run && ACTIVE.has(run.status);
}

export function useRun(id: number) {
  return useQuery({
    queryKey: keys.run(id),
    queryFn: () => unwrap(api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } })),
    refetchInterval: (query) => (isActive(query.state.data) ? 1000 : false),
  });
}

export function useResults(id: number, goals: GoalOverrides, enabled = true, buckets?: string[]) {
  return useQuery({
    queryKey: ["results", id, goals, buckets],
    queryFn: async () => {
      const query = { ...goals, buckets } as Record<string, unknown>;
      return (await unwrap(
        api.GET("/api/runs/{run_id}/results", { params: { path: { run_id: id }, query } }),
      )) as unknown as Results;
    },
    enabled,
    placeholderData: keepPreviousData, // goal changes re-render in place instead of flashing
    staleTime: Infinity, // a completed run's results only change with the goal overrides (part of the key)
  });
}

export function usePath(id: number, path: number | null, enabled = true) {
  return useQuery({
    queryKey: ["path", id, path],
    queryFn: () =>
      unwrap(api.GET("/api/runs/{run_id}/paths/{path}", { params: { path: { run_id: id, path: path! } } })),
    enabled: enabled && path !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

export function useYears(id: number, enabled = true) {
  return useQuery({
    queryKey: ["years", id],
    queryFn: () => unwrap(api.GET("/api/runs/{run_id}/years", { params: { path: { run_id: id } } })),
    enabled,
    staleTime: Infinity,
  });
}

/** JSON Schemas of the editable document kinds, for the YAML editor. */
export function useDocumentSchemas(kinds: readonly string[]) {
  return useQuery({
    queryKey: ["schemas", kinds],
    queryFn: async () => {
      const entries = await Promise.all(
        kinds.map(
          async (kind) => [kind, await unwrap(api.GET("/api/schemas/{kind}", { params: { path: { kind } } }))] as const,
        ),
      );
      return Object.fromEntries(entries) as Record<string, object>;
    },
    staleTime: Infinity,
  });
}
