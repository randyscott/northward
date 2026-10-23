// The balance grid: every account's balance (and cost basis, where the account has one) in one table, saved as a
// single revision of accounts.yaml. The save sends structured data, so the file's comments and layout survive.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, unwrap } from "../api/client";
import { keys, useDocument } from "../api/hooks";
import { ErrorNotice, Loading } from "../components/common";
import { money, signedMoney } from "../lib/format";

interface AccountEntry {
  id: string;
  owner: string;
  type: string;
  balance: number;
  cost_basis?: number;
  [field: string]: unknown;
}

type Field = "balance" | "cost_basis";
type Edits = Record<string, Partial<Record<Field, string>>>;

/** A typed amount: digits with optional $ and commas. NaN when it isn't one. */
export function parseAmount(text: string): number {
  const cleaned = text.replace(/[$,\s]/g, "");
  return cleaned === "" || !/^\d+(\.\d+)?$/.test(cleaned) ? NaN : Number(cleaned);
}

/** The accounts document's data with `edits` applied (unchanged fields keep their stored values). */
export function applyEdits(data: { accounts: AccountEntry[] }, edits: Edits): { accounts: AccountEntry[] } {
  return {
    ...data,
    accounts: data.accounts.map((account) => {
      const edit = edits[account.id];
      if (!edit) return account;
      const next = { ...account };
      for (const field of ["balance", "cost_basis"] as const) {
        const typed = edit[field];
        if (typed !== undefined && !Number.isNaN(parseAmount(typed))) next[field] = parseAmount(typed);
      }
      return next;
    }),
  };
}

export function BalancesPage() {
  const { profile = "" } = useParams();
  const queryClient = useQueryClient();
  const doc = useDocument(profile, "accounts");
  const [edits, setEdits] = useState<Edits>({});
  const [note, setNote] = useState("");
  const data = doc.data?.data as { accounts: AccountEntry[] } | undefined;
  const accounts = data?.accounts ?? [];

  const invalid = Object.values(edits).some((edit) =>
    Object.values(edit).some((v) => v !== undefined && Number.isNaN(parseAmount(v))),
  );
  const next = useMemo(() => (data ? applyEdits(data, edits) : undefined), [data, edits]);
  const changed = next
    ? next.accounts.filter((a, i) => a.balance !== accounts[i]!.balance || a.cost_basis !== accounts[i]!.cost_basis)
    : [];
  const total = accounts.reduce((sum, a) => sum + a.balance, 0);
  const newTotal = next ? next.accounts.reduce((sum, a) => sum + a.balance, 0) : total;

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/api/profiles/{profile}/documents/{address}", {
          params: { path: { profile, address: "accounts" } },
          body: {
            data: next as unknown as Record<string, unknown>,
            note: note || "Updated balances",
            base_revision: doc.data?.latest?.revision ?? null,
          },
        }),
      ),
    onSuccess: () => {
      setEdits({});
      setNote("");
      void queryClient.invalidateQueries({ queryKey: keys.profile(profile) });
    },
  });

  const edit = (id: string, field: Field, value: string) =>
    setEdits((current) => ({ ...current, [id]: { ...current[id], [field]: value } }));

  if (doc.isPending) return <Loading />;
  if (doc.error) return <ErrorNotice error={doc.error} />;

  const shown = (account: AccountEntry, field: Field) =>
    edits[account.id]?.[field] ?? (account[field] === undefined ? "" : Number(account[field]).toLocaleString("en-US"));
  const isChanged = (account: AccountEntry, field: Field) => {
    const typed = edits[account.id]?.[field];
    return typed !== undefined && parseAmount(typed) !== account[field];
  };
  const conflict = save.error instanceof ApiError && save.error.status === 409;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="crumbs">
            <Link to={`/profiles/${profile}`}>{profile}</Link> / balances
          </div>
          <h1>Update balances</h1>
          <div className="subtitle">
            Enter current balances, e.g. from statements. Saving makes one new revision of{" "}
            <Link to={`/profiles/${profile}/documents/accounts`}>accounts</Link>; everything else in it stays as it is.
          </div>
        </div>
      </div>

      <section className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Type</th>
                <th>Owner</th>
                <th className="num">Balance</th>
                <th className="num">Cost basis</th>
                <th className="num">Change</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account, i) => {
                const after = next?.accounts[i];
                const delta = after ? after.balance - account.balance : 0;
                return (
                  <tr key={account.id}>
                    <td className="mono">{account.id}</td>
                    <td className="secondary">{account.type.replace(/_/g, " ")}</td>
                    <td className="secondary">{account.owner}</td>
                    <td className="num">
                      <input
                        className={`number${isChanged(account, "balance") ? " changed" : ""}`}
                        aria-label={`${account.id} balance`}
                        inputMode="decimal"
                        value={shown(account, "balance")}
                        onChange={(e) => edit(account.id, "balance", e.target.value)}
                        aria-invalid={Number.isNaN(parseAmount(shown(account, "balance")))}
                      />
                    </td>
                    <td className="num">
                      {"cost_basis" in account ? (
                        <input
                          className={`number${isChanged(account, "cost_basis") ? " changed" : ""}`}
                          aria-label={`${account.id} cost basis`}
                          inputMode="decimal"
                          value={shown(account, "cost_basis")}
                          onChange={(e) => edit(account.id, "cost_basis", e.target.value)}
                          title={account.type === "plan_529" ? "Contributions to date" : "Total cost basis"}
                        />
                      ) : (
                        <span className="muted">–</span>
                      )}
                    </td>
                    <td className="num secondary">{delta ? signedMoney(delta) : ""}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3}>Total</td>
                <td className="num">{money(newTotal)}</td>
                <td />
                <td className="num">{newTotal !== total ? signedMoney(newTotal - total) : ""}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <div className="row">
        <input
          aria-label="Revision note"
          placeholder="Note (default: Updated balances)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={{ width: 320 }}
        />
        <button
          className="primary"
          disabled={!changed.length || invalid || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : `Save ${changed.length || ""} change${changed.length === 1 ? "" : "s"}`}
        </button>
        <button disabled={!Object.keys(edits).length} onClick={() => setEdits({})}>
          Discard
        </button>
        {invalid && (
          <span className="small" style={{ color: "var(--critical-text)" }}>
            Amounts must be non-negative numbers.
          </span>
        )}
        {save.isSuccess && !changed.length && (
          <span className="small" style={{ color: "var(--good-text)" }}>
            Saved as revision {save.data.saved[0]?.revision ?? doc.data?.latest?.revision}.
          </span>
        )}
      </div>
      {conflict ? (
        <div className="notice error" role="alert">
          <div className="title">The accounts changed since this page loaded</div>
          <div className="row" style={{ marginTop: 8 }}>
            <button
              onClick={() => {
                save.reset();
                void queryClient.invalidateQueries({ queryKey: keys.document(profile, "accounts") });
              }}
            >
              Reload them (your edits stay in the grid)
            </button>
          </div>
        </div>
      ) : (
        <ErrorNotice error={save.error} title="Not saved" />
      )}
    </div>
  );
}
