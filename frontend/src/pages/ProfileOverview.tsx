import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type ScenarioOut, unwrap } from "../api/client";
import { useProfile, useRuns } from "../api/hooks";
import { Dialog, ErrorNotice, Loading, NameHint, StatusBadge } from "../components/common";
import { dateTime } from "../lib/format";
import { titleOf } from "../lib/documents";

type Action = { kind: "rename-profile" } | { kind: "clone" | "rename"; scenario: ScenarioOut } | null;

export function ProfileOverview() {
  const { profile = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showDeleted, setShowDeleted] = useState(false);
  const detail = useProfile(profile, showDeleted);
  const runs = useRuns({ profile, limit: 8 });
  const [action, setAction] = useState<Action>(null);
  const [name, setName] = useState("");

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["profile", profile] });
    void queryClient.invalidateQueries({ queryKey: ["profiles"] });
  };
  const open = (next: Action, initial: string) => {
    setAction(next);
    setName(initial);
  };

  const submit = useMutation({
    mutationFn: async () => {
      if (!action) return;
      if (action.kind === "rename-profile") {
        await unwrap(api.PATCH("/api/profiles/{profile}", { params: { path: { profile } }, body: { name } }));
        return `/profiles/${name}`;
      }
      if (action.kind === "clone") {
        await unwrap(
          api.POST("/api/profiles/{profile}/scenarios", {
            params: { path: { profile } },
            body: { name, clone_from: action.scenario.name },
          }),
        );
        return `/profiles/${profile}/scenarios/${name}`;
      }
      await unwrap(
        api.PATCH("/api/profiles/{profile}/scenarios/{scenario}", {
          params: { path: { profile, scenario: action.scenario.name } },
          body: { name },
        }),
      );
      return undefined;
    },
    onSuccess: (to) => {
      setAction(null);
      refresh();
      if (to) navigate(to);
    },
  });

  const scenarioCall = useMutation({
    mutationFn: ({ scenario, op }: { scenario: string; op: "delete" | "restore" }) =>
      op === "delete"
        ? unwrap(
            api.DELETE("/api/profiles/{profile}/scenarios/{scenario}", { params: { path: { profile, scenario } } }),
          )
        : unwrap(
            api.POST("/api/profiles/{profile}/scenarios/{scenario}/restore", {
              params: { path: { profile, scenario } },
            }),
          ),
    onSuccess: refresh,
  });
  const deleteProfile = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/profiles/{profile}", { params: { path: { profile } } })),
    onSuccess: () => {
      refresh();
      navigate("/profiles");
    },
  });

  if (detail.isPending) return <Loading />;
  if (detail.error) return <ErrorNotice error={detail.error} />;
  const data = detail.data!;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="crumbs">Profile</div>
          <h1>{data.name}</h1>
          <div className="subtitle">Updated {dateTime(data.updated_at)}</div>
        </div>
        <div className="row">
          <Link className="button" to={`/profiles/${profile}/balances`}>
            Update balances
          </Link>
          <button onClick={() => open({ kind: "rename-profile" }, profile)}>Rename</button>
          <button
            className="danger"
            onClick={() =>
              window.confirm(`Delete profile ${profile}? You can restore it from All profiles.`) &&
              deleteProfile.mutate()
            }
          >
            Delete
          </button>
        </div>
      </div>
      <ErrorNotice error={scenarioCall.error ?? deleteProfile.error} />

      <div className="grid-2">
        <section className="card">
          <div className="card-header">
            <h2>Documents</h2>
            <span className="hint">Edited as YAML; every save is a new revision</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Holds</th>
                <th className="num">Revision</th>
              </tr>
            </thead>
            <tbody>
              {data.documents.map((doc) => (
                <tr key={doc.address}>
                  <td>
                    <Link to={`/profiles/${profile}/documents/${doc.address}`}>{titleOf(doc.address)}</Link>
                    {doc.required && <span className="muted small"> · required</span>}
                  </td>
                  <td className="secondary" style={{ whiteSpace: "normal" }}>
                    {doc.description}
                  </td>
                  <td className="num">
                    {doc.latest ? (
                      doc.latest.revision
                    ) : (
                      <Link className="small" to={`/profiles/${profile}/documents/${doc.address}`}>
                        Create
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <div className="stack">
          <section className="card">
            <div className="card-header">
              <h2>Scenarios</h2>
              <label className="inline small secondary">
                <input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
                Show deleted
              </label>
            </div>
            <table>
              <tbody>
                {data.scenario_details.map((scenario) => (
                  <tr key={scenario.name}>
                    <td style={{ whiteSpace: "normal" }}>
                      {scenario.deleted_at ? (
                        <span className="muted">{scenario.name} (deleted)</span>
                      ) : (
                        <Link to={`/profiles/${profile}/scenarios/${scenario.name}`}>{scenario.name}</Link>
                      )}
                      {scenario.parent && <span className="muted small"> · from {scenario.parent}</span>}
                      <div className="small secondary">{scenario.description}</div>
                    </td>
                    <td style={{ width: 1 }}>
                      <div className="row" style={{ flexWrap: "nowrap" }}>
                        {scenario.deleted_at ? (
                          <button onClick={() => scenarioCall.mutate({ scenario: scenario.name, op: "restore" })}>
                            Restore
                          </button>
                        ) : (
                          <>
                            <button onClick={() => open({ kind: "clone", scenario }, `${scenario.name}_copy`)}>
                              Clone
                            </button>
                            <button onClick={() => open({ kind: "rename", scenario }, scenario.name)}>Rename</button>
                            <button
                              className="danger"
                              onClick={() =>
                                window.confirm(`Delete scenario ${scenario.name}?`) &&
                                scenarioCall.mutate({ scenario: scenario.name, op: "delete" })
                              }
                            >
                              Delete
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.scenario_details.length === 0 && <div className="muted">No scenarios yet.</div>}
          </section>

          <section className="card">
            <div className="card-header">
              <h2>Recent runs</h2>
              <Link className="small" to={`/runs?profile=${profile}`}>
                All runs
              </Link>
            </div>
            {runs.data?.length ? (
              <table>
                <tbody>
                  {runs.data.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link to={`/runs/${run.id}`}>#{run.id}</Link> <span className="secondary">{run.scenario}</span>
                      </td>
                      <td className="secondary small">
                        {run.kind === "monte_carlo" ? `${run.n_sims?.toLocaleString()} paths` : "deterministic"}
                      </td>
                      <td>
                        <StatusBadge status={run.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="muted">No runs yet. Open a scenario to run it.</div>
            )}
          </section>
        </div>
      </div>

      {action && (
        <Dialog
          title={
            action.kind === "rename-profile"
              ? "Rename profile"
              : action.kind === "clone"
                ? `Clone ${action.scenario.name}`
                : `Rename ${action.scenario.name}`
          }
          submitLabel={action.kind === "clone" ? "Clone" : "Rename"}
          onSubmit={() => submit.mutate()}
          onClose={() => setAction(null)}
          busy={submit.isPending}
        >
          <label className="field">
            {action.kind === "clone" ? "New scenario name" : "New name"}
            <input value={name} onChange={(e) => setName(e.target.value.trim())} required />
            <NameHint value={name} />
          </label>
          <ErrorNotice error={submit.error} title="That didn't work" />
        </Dialog>
      )}
    </div>
  );
}
