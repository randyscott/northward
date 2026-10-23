// The shared rules, read-only: data/rules is their master copy (edit the files, then `northward db seed`).
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, unwrap } from "../api/client";
import { ErrorNotice, Loading } from "../components/common";
import YamlEditor from "../components/YamlEditor";
import { dateTime } from "../lib/format";

export default function RulesPage() {
  const [name, kind] = (useParams()["*"] ?? "").split("/");
  const navigate = useNavigate();
  const ruleSets = useQuery({ queryKey: ["rule-sets"], queryFn: () => unwrap(api.GET("/api/rule-sets")) });
  const selected = ruleSets.data?.find((r) => r.name === name) ?? ruleSets.data?.find((r) => r.latest);
  const doc = useQuery({
    queryKey: ["rule-doc", selected?.name, kind],
    queryFn: () =>
      unwrap(
        api.GET("/api/rule-sets/{name}/documents/{kind}", { params: { path: { name: selected!.name, kind: kind! } } }),
      ),
    enabled: !!selected && !!kind,
  });

  useEffect(() => {
    if (selected && !kind) navigate(`/rules/${selected.name}/${selected.documents[0]?.kind}`, { replace: true });
  }, [selected, kind, navigate]);

  if (ruleSets.isPending) return <Loading />;
  if (ruleSets.error) return <ErrorNotice error={ruleSets.error} />;
  if (!selected) return <div className="muted">No rule sets. Run `northward db seed`.</div>;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Rules {selected.name}</h1>
          <div className="subtitle">
            Shared by every profile. Read-only here: edit <code>data/rules/</code> and run{" "}
            <code>northward db seed</code>.
          </div>
        </div>
        {ruleSets.data!.length > 1 && (
          <select aria-label="Rule set" value={selected.name} onChange={(e) => navigate(`/rules/${e.target.value}`)}>
            {ruleSets.data!.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
                {r.latest ? " (latest)" : ""}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "240px minmax(0, 1fr)" }}>
        <nav className="card nav-section" aria-label="Rule documents">
          {selected.documents.map((d) => (
            <Link
              key={d.kind}
              className={`nav-link${d.kind === kind ? " active" : ""}`}
              to={`/rules/${selected.name}/${d.kind}`}
            >
              {d.kind.replace(/_/g, " ")}
            </Link>
          ))}
        </nav>
        <div className="stack">
          {doc.data && (
            <div className="small muted">
              Revision {doc.data.latest?.revision} · {dateTime(doc.data.latest?.created_at)} · {doc.data.latest?.note}
            </div>
          )}
          <ErrorNotice error={doc.error} />
          {doc.data ? (
            <YamlEditor
              key={`${selected.name}/${kind}`}
              path={`rules/${selected.name}/${kind}.yaml`}
              value={doc.data.yaml_text}
              readOnly
            />
          ) : (
            <Loading />
          )}
        </div>
      </div>
    </div>
  );
}
