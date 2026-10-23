import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, type DocumentDetail, type Issue, unwrap } from "../api/client";
import { keys, useDocument, useDocumentSchemas, useRevision, useRevisions } from "../api/hooks";
import { ErrorNotice, IssueList, Loading } from "../components/common";
import DiffViewer from "../components/DiffViewer";
import { setSchemas } from "../components/monaco";
import YamlEditor, { type Marker } from "../components/YamlEditor";
import { EDITABLE_KINDS, originOf, titleOf } from "../lib/documents";
import { dateTime } from "../lib/format";
import { locate } from "../lib/yamlLocate";

const NEW_DOCUMENT = "schema_version: 1\n";

function Editor({ profile, address, doc }: { profile: string; address: string; doc: DocumentDetail | null }) {
  const queryClient = useQueryClient();
  const saved = doc?.yaml_text ?? NEW_DOCUMENT;
  const [text, setText] = useState(saved);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const dirty = text !== saved;

  useEffect(() => setText(saved), [saved]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/api/profiles/{profile}/documents/{address}", {
          params: { path: { profile, address } },
          body: { yaml_text: text, note: note || null, base_revision: doc?.latest?.revision ?? null },
        }),
      ),
    onSuccess: (result) => {
      setNote("");
      setMessage(result.saved.length ? `Saved revision ${result.saved[0]!.revision}.` : "No changes to save.");
      void queryClient.invalidateQueries({ queryKey: keys.profile(profile) });
    },
    onError: () => setMessage(null),
  });

  const origin = originOf(profile, address);
  const issues: Issue[] = save.error instanceof ApiError ? save.error.issues : [];
  const here = issues.filter((issue) => issue.origin === origin);
  const elsewhere = issues.filter((issue) => issue.origin !== origin);
  const markers = useMemo<Marker[]>(
    () =>
      here.map((issue) => ({
        ...locate(text, issue.location),
        message: `${issue.location ? `${issue.location}: ` : ""}${issue.message}`,
      })),
    [save.error], // markers belong to the text that was saved; they stay until the next save
  );
  const conflict = save.error instanceof ApiError && save.error.status === 409;

  const reload = () => {
    save.reset();
    void queryClient.invalidateQueries({ queryKey: keys.document(profile, address) });
  };

  return (
    <div className="stack">
      <div className="row">
        <input
          aria-label="Revision note"
          placeholder="Note for this revision (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={{ flex: 1, maxWidth: 480 }}
        />
        <button className="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button disabled={!dirty} onClick={() => setText(saved)}>
          Discard changes
        </button>
        {dirty && (
          <span className="small secondary row">
            <span className="dirty-dot" aria-hidden /> Unsaved changes · Ctrl+S saves
          </span>
        )}
        {!dirty && message && (
          <span className="small" style={{ color: "var(--good-text)" }}>
            {message}
          </span>
        )}
      </div>

      {conflict && (
        <div className="notice error" role="alert">
          <div className="title">This document changed since you opened it</div>
          <div>{save.error!.message}</div>
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={reload}>Load the newer revision (discards your edits)</button>
          </div>
        </div>
      )}
      {save.error && !conflict && (
        <div className="notice error" role="alert">
          <div className="title">Not saved</div>
          <div>{save.error.message}</div>
          {here.length > 0 && (
            <div className="small secondary">Problems in this document are underlined in the editor.</div>
          )}
          {here.length > 0 && <IssueList issues={here} />}
          {elsewhere.length > 0 && (
            <>
              <div className="small secondary" style={{ marginTop: 6 }}>
                The change would break other documents:
              </div>
              <IssueList issues={elsewhere} />
            </>
          )}
        </div>
      )}

      <YamlEditor
        path={origin}
        value={text}
        onChange={setText}
        markers={markers}
        onSave={() => dirty && save.mutate()}
      />
    </div>
  );
}

function History({ profile, doc }: { profile: string; doc: DocumentDetail }) {
  const queryClient = useQueryClient();
  const revisions = useRevisions(doc.id);
  const latest = doc.latest?.revision ?? 1;
  const [selected, setSelected] = useState(latest);
  const [base, setBase] = useState(Math.max(1, latest - 1));
  const newer = useRevision(doc.id, selected);
  const older = useRevision(doc.id, base);
  const restore = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/documents/{document_id}/revisions/{revision}/restore", {
          params: { path: { document_id: doc.id!, revision: selected } },
          body: { note: null },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.profile(profile) });
      void queryClient.invalidateQueries({ queryKey: keys.revisions(doc.id!) });
    },
  });
  const list = [...(revisions.data ?? [])].reverse();

  return (
    <div className="grid-2" style={{ gridTemplateColumns: "300px minmax(0, 1fr)" }}>
      <section className="card">
        <h3 style={{ marginBottom: 8 }}>Revisions</h3>
        <table>
          <tbody>
            {list.map((revision) => (
              <tr
                key={revision.id}
                onClick={() => {
                  setSelected(revision.revision);
                  setBase(Math.max(1, revision.revision - 1));
                }}
                style={{
                  cursor: "pointer",
                  background: revision.revision === selected ? "var(--accent-wash)" : undefined,
                }}
              >
                <td className="num" style={{ width: 1 }}>
                  {revision.revision}
                </td>
                <td style={{ whiteSpace: "normal" }}>
                  <div>{revision.note || <span className="muted">no note</span>}</div>
                  <div className="small muted">{dateTime(revision.created_at)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="stack">
        <div className="row">
          <span className="secondary">Revision {selected} compared with</span>
          <select aria-label="Compare with revision" value={base} onChange={(e) => setBase(Number(e.target.value))}>
            {list.map((revision) => (
              <option key={revision.id} value={revision.revision}>
                revision {revision.revision}
              </option>
            ))}
          </select>
          <span className="spacer" />
          {selected !== latest && (
            <button onClick={() => restore.mutate()} disabled={restore.isPending}>
              Restore revision {selected}
            </button>
          )}
        </div>
        <ErrorNotice error={restore.error} title="Couldn't restore that revision" />
        {restore.isSuccess && (
          <div className="small" style={{ color: "var(--good-text)" }}>
            {restore.data.saved.length
              ? `Restored as revision ${restore.data.saved[0]!.revision}.`
              : "That revision matches the latest one."}
          </div>
        )}
        {newer.data && older.data ? (
          <DiffViewer original={older.data.yaml_text} modified={newer.data.yaml_text} />
        ) : (
          <Loading />
        )}
        <div className="small muted">
          Left: revision {base}. Right: revision {selected}.
        </div>
      </section>
    </div>
  );
}

export default function DocumentPage() {
  const { profile = "", "*": address = "" } = useParams();
  const [tab, setTab] = useState<"edit" | "history">("edit");
  const doc = useDocument(profile, address);
  const schemas = useDocumentSchemas(EDITABLE_KINDS);

  useEffect(() => {
    if (schemas.data) setSchemas(schemas.data);
  }, [schemas.data]);

  const missing = doc.error instanceof ApiError && doc.error.status === 404;
  const scenario = address.startsWith("scenarios/") ? address.slice("scenarios/".length) : null;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="crumbs">
            <Link to={`/profiles/${profile}`}>{profile}</Link> / {scenario ? "scenarios" : "documents"}
          </div>
          <h1>{titleOf(address)}</h1>
          <div className="subtitle">
            {doc.data
              ? `${doc.data.description} · revision ${doc.data.latest?.revision} · ${dateTime(doc.data.latest?.created_at)}`
              : missing
                ? "This profile doesn't have this document yet. Saving creates it."
                : ""}
          </div>
        </div>
        {scenario && !missing && (
          <Link className="button" to={`/profiles/${profile}/scenarios/${scenario}`}>
            Run this scenario
          </Link>
        )}
      </div>
      {doc.error && !missing && <ErrorNotice error={doc.error} />}
      {doc.data && (
        <div className="tabs" role="tablist">
          {(["edit", "history"] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "selected" : ""}
              onClick={() => setTab(t)}
            >
              {t === "edit" ? "Edit" : `History (${doc.data.latest?.revision ?? 0})`}
            </button>
          ))}
        </div>
      )}
      {doc.isPending ? (
        <Loading />
      ) : tab === "history" && doc.data ? (
        <History profile={profile} doc={doc.data} />
      ) : doc.data || missing ? (
        <Editor key={address} profile={profile} address={address} doc={doc.data ?? null} />
      ) : null}
    </div>
  );
}
