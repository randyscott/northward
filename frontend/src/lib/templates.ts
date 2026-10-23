// Starting documents for a blank profile: the smallest valid household, with one member, account, and scenario.

export function blankProfile(year = new Date().getFullYear()): Record<string, string> {
  return {
    household: `schema_version: 1

household:
  filing_status: single           # married_filing_jointly, single, head_of_household, ...
  state: WI                       # state of residence (rules/state_tax.yaml)

members:
  - id: me
    name: "Me"
    sex: female
    birth_year: ${year - 45}
    birth_month: 1
    target_retirement_age: 65
    social_security:
      pia_at_fra: 2500            # monthly benefit at full retirement age, today's dollars
`,
    accounts: `schema_version: 1

accounts:
  - id: savings
    owner: me
    type: savings
    balance: 50000
`,
    spending: `schema_version: 1

spending:
  base:
    amount: 60000                 # per year, today's dollars
`,
    "scenarios/base": `schema_version: 1
description: "Baseline"

horizon:
  start_year: ${year}
  end_age: 95
`,
  };
}
