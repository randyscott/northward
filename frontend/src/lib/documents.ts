// The kinds of documents a profile holds, as the API names them, and the editor's model paths.

export const PROFILE_KINDS = [
  "household",
  "accounts",
  "income",
  "liabilities",
  "spending",
  "events",
  "health_costs",
  "goals",
] as const;

export const EDITABLE_KINDS = [...PROFILE_KINDS, "scenario"] as const;

/** The document kind of an address: `accounts` -> accounts, `scenarios/base` -> scenario. */
export function kindOf(address: string): string {
  return address.startsWith("scenarios/") ? "scenario" : address;
}

/** The origin the server uses for a document in issues, e.g. profiles/default/scenarios/base.yaml. */
export function originOf(profile: string, address: string): string {
  return `profiles/${profile}/${address}.yaml`;
}

export function titleOf(address: string): string {
  if (address.startsWith("scenarios/")) return `Scenario: ${address.slice("scenarios/".length)}`;
  return address.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export const NAME_PATTERN = /^[a-z][a-z0-9_]*$/;
export const NAME_HINT = "lowercase letters, digits, and underscores, starting with a letter";
