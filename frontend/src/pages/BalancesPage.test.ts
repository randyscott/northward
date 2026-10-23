import { applyEdits, parseAmount } from "./BalancesPage";

test("amounts accept $ and commas, and nothing else", () => {
  expect(parseAmount("$1,234.50")).toBe(1234.5);
  expect(parseAmount("175000")).toBe(175000);
  expect(parseAmount("")).toBeNaN();
  expect(parseAmount("-5")).toBeNaN();
  expect(parseAmount("12k")).toBeNaN();
});

test("edits replace only the typed fields, and ignore invalid ones", () => {
  const data = {
    accounts: [
      { id: "a", owner: "me", type: "brokerage", balance: 100, cost_basis: 80, asset_strategy: { kind: "x" } },
      { id: "b", owner: "me", type: "savings", balance: 50 },
    ],
  };
  const next = applyEdits(data, { a: { balance: "120", cost_basis: "oops" } });
  expect(next.accounts[0]).toEqual({ ...data.accounts[0], balance: 120 });
  expect(next.accounts[1]).toBe(data.accounts[1]);
});
