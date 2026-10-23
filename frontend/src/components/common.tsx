import { type FormEvent, type ReactNode, useEffect, useRef } from "react";

import { ApiError, type Issue, type RunOut } from "../api/client";

export function StatusBadge({ status }: { status: RunOut["status"] }) {
  const label = { queued: "Queued", running: "Running", complete: "Complete", failed: "Failed" }[status];
  return (
    <span className={`badge ${status}`}>
      <span className="dot" aria-hidden />
      {label}
    </span>
  );
}

export function ProgressBar({ done, total }: { done: number; total: number }) {
  const fraction = total > 0 ? done / total : 0;
  return (
    <div className="row">
      <div
        className="progress"
        role="progressbar"
        aria-valuenow={done}
        aria-valuemin={0}
        aria-valuemax={total}
        style={{ flex: 1 }}
      >
        <div style={{ width: `${fraction * 100}%` }} />
      </div>
      <span className="small secondary">
        {done.toLocaleString()} / {total.toLocaleString()} paths
      </span>
    </div>
  );
}

export function IssueList({ issues }: { issues: Issue[] }) {
  return (
    <ul>
      {issues.map((issue, i) => (
        <li key={i}>
          <span className="mono">{issue.origin}</span>
          {issue.location && (
            <>
              {" "}
              <span className="mono">{issue.location}</span>
            </>
          )}
          : {issue.message}
        </li>
      ))}
    </ul>
  );
}

/** An error from a query or mutation, with its configuration issues when the server sent them. */
export function ErrorNotice({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  const issues = error instanceof ApiError ? error.issues : [];
  return (
    <div className="notice error" role="alert">
      <div className="title">{title ?? "Something went wrong"}</div>
      <div>{message}</div>
      {issues.length > 0 && <IssueList issues={issues} />}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="muted">{what}…</div>;
}

export function Tile({ label, value, detail }: { label: string; value: ReactNode; detail?: ReactNode }) {
  return (
    <div className="card tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {detail && <div className="detail">{detail}</div>}
    </div>
  );
}

/** A small modal form. Enter submits, Escape (or Cancel) closes. */
export function Dialog({
  title,
  children,
  submitLabel,
  onSubmit,
  onClose,
  busy,
  danger,
}: {
  title: string;
  children: ReactNode;
  submitLabel: string;
  onSubmit: () => void;
  onClose: () => void;
  busy?: boolean;
  danger?: boolean;
}) {
  const ref = useRef<HTMLFormElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("input, select, button.primary")?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="dialog stack" ref={ref} onSubmit={submit} role="dialog" aria-label={title}>
        <h2>{title}</h2>
        {children}
        <div className="actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={danger ? "primary danger" : "primary"} disabled={busy}>
            {busy ? "Working…" : submitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

export function NameHint({ value }: { value: string }) {
  return value && !/^[a-z][a-z0-9_]*$/.test(value) ? (
    <span className="small" style={{ color: "var(--critical-text)" }}>
      Use lowercase letters, digits, and underscores, starting with a letter.
    </span>
  ) : null;
}
