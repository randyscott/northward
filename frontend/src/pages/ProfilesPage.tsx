import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, unwrap } from "../api/client";
import { useProfiles } from "../api/hooks";
import { Dialog, ErrorNotice, Loading, NameHint } from "../components/common";
import { dateTime } from "../lib/format";
import { blankProfile } from "../lib/templates";

function CreateProfile({ onClose, existing }: { onClose: () => void; existing: string[] }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [from, setFrom] = useState("");
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/profiles", {
          body: from
            ? { name, copy_from: from }
            : {
                name,
                note: "created in the app",
                documents: Object.fromEntries(
                  Object.entries(blankProfile()).map(([address, text]) => [address, { yaml_text: text }]),
                ),
              },
        }),
      ),
    onSuccess: (profile) => {
      void queryClient.invalidateQueries({ queryKey: ["profiles"] });
      navigate(`/profiles/${profile.name}`);
    },
  });
  return (
    <Dialog
      title="New profile"
      submitLabel="Create"
      onSubmit={() => create.mutate()}
      onClose={onClose}
      busy={create.isPending}
    >
      <label className="field">
        Name
        <input value={name} onChange={(e) => setName(e.target.value.trim())} placeholder="e.g. household" required />
        <NameHint value={name} />
      </label>
      <label className="field">
        Start from
        <select value={from} onChange={(e) => setFrom(e.target.value)}>
          <option value="">A blank profile (one member, one account, a base scenario)</option>
          {existing.map((profile) => (
            <option key={profile} value={profile}>
              A copy of {profile}
            </option>
          ))}
        </select>
      </label>
      <ErrorNotice error={create.error} title="Couldn't create the profile" />
    </Dialog>
  );
}

export function ProfilesPage() {
  const [showDeleted, setShowDeleted] = useState(false);
  const [creating, setCreating] = useState(false);
  const profiles = useProfiles(showDeleted);
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["profiles"] });
  const restore = useMutation({
    mutationFn: (profile: string) =>
      unwrap(api.POST("/api/profiles/{profile}/restore", { params: { path: { profile } } })),
    onSuccess: refresh,
  });
  const purge = useMutation({
    mutationFn: (profile: string) =>
      unwrap(api.DELETE("/api/profiles/{profile}", { params: { path: { profile }, query: { purge: true } } })),
    onSuccess: refresh,
  });

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Profiles</h1>
          <div className="subtitle">A household and everything about it: documents, scenarios, and their runs.</div>
        </div>
        <button className="primary" onClick={() => setCreating(true)}>
          New profile
        </button>
      </div>
      <ErrorNotice error={profiles.error ?? restore.error ?? purge.error} />
      <div className="card">
        <div className="card-header">
          <h2>All profiles</h2>
          <label className="inline small secondary">
            <input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
            Show deleted
          </label>
        </div>
        {profiles.isPending ? (
          <Loading />
        ) : profiles.data?.length === 0 ? (
          <div className="muted">No profiles yet. Create one, or run `northward db seed`.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Profile</th>
                <th>Scenarios</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {profiles.data?.map((profile) => (
                <tr key={profile.name}>
                  <td>
                    {profile.deleted_at ? (
                      <span className="muted">{profile.name} (deleted)</span>
                    ) : (
                      <Link to={`/profiles/${profile.name}`}>{profile.name}</Link>
                    )}
                  </td>
                  <td className="secondary">{profile.scenarios.join(", ") || "–"}</td>
                  <td className="secondary">{dateTime(profile.updated_at)}</td>
                  <td>
                    {profile.deleted_at && (
                      <div className="row">
                        <button onClick={() => restore.mutate(profile.name)}>Restore</button>
                        <button
                          className="danger"
                          onClick={() =>
                            window.confirm(`Permanently remove ${profile.name}, its history, and its runs?`) &&
                            purge.mutate(profile.name)
                          }
                        >
                          Purge
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {creating && (
        <CreateProfile
          onClose={() => setCreating(false)}
          existing={profiles.data?.filter((p) => !p.deleted_at).map((p) => p.name) ?? []}
        />
      )}
    </div>
  );
}
