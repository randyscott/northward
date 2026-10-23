import { locate, parseLocation } from "./yamlLocate";

const TEXT = `schema_version: 1
# accounts
accounts:
  - id: brokerage
    owner: joint
    balance: 100
  - id: ira
    owner: alex
levers:
  ss_claim_ages:
    alex: 67
`;

test("parses dotted keys and bracketed items", () => {
  expect(parseLocation("accounts[ira].owner")).toEqual(["accounts", "ira", "owner"]);
  expect(parseLocation("levers.ss_claim_ages.alex")).toEqual(["levers", "ss_claim_ages", "alex"]);
  expect(parseLocation("")).toEqual([]);
});

test("finds a field of a list item named by its id", () => {
  expect(locate(TEXT, "accounts[ira].owner")).toMatchObject({ startLine: 8, startColumn: 5, endLine: 8 });
});

test("finds nested keys", () => {
  expect(locate(TEXT, "levers.ss_claim_ages.alex")).toMatchObject({ startLine: 11, startColumn: 5 });
});

test("falls back to the deepest part that exists", () => {
  expect(locate(TEXT, "accounts[brokerage].cost_basis").startLine).toBe(4); // missing field: its item
  expect(locate(TEXT, "accounts[3]").startLine).toBe(3); // no such item: the list's key
  expect(locate(TEXT, "")).toMatchObject({ startLine: 1, startColumn: 1 });
});

test("list items can be addressed by index", () => {
  expect(locate(TEXT, "accounts[1].owner").startLine).toBe(8);
});
