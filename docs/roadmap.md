# Roadmap

Larger pieces of planned work. Smaller improvements and known gaps are tracked as
[GitHub issues](https://github.com/randyscott/northward/issues); [Modeling](modeling.md) lists what the engine
doesn't cover yet.

## Document forms

Forms beside the YAML editor for the same document, with a toggle between them. Both save through the existing API,
so no backend work is needed ([D49](decisions.md#d49-ui-in-two-steps)). In order of how often they're likely to be
used:

1. Scenario levers: retirement and claiming ages, Roth conversions, withdrawal order, mortality.
2. Household and income (salaries and their payroll elections, pensions, other income).
3. Spending categories and events.
4. Accounts beyond the balance grid (account types, asset strategies, 529 details).

Reusable widgets for anchors (a year, a member's or dependent's age, or an event) and for the schema's choices
between alternative shapes. Liabilities, health costs, and goals stay YAML-only unless the forms above prove worth
extending. Validation errors come from the API, as in the editor.

**Done when** the levers, household, income, spending, and events documents can be edited in forms, and every form
round-trips: saving unchanged data adds no revision, and YAML comments survive form edits.

## Multi-user and authentication

Not scheduled. The groundwork is in place ([D17](decisions.md#d17-users)): profiles carry a nullable
`owner_user_id`, and all profile access goes through repositories that can be scoped per user.

- Add a `users` table, start using `profiles.owner_user_id`, and scope every repository query by the current user.
- Authentication: local accounts (argon2 password hashes) with session cookies, or OIDC with an external identity
  provider. Decide when the work starts.
- Authorization: owner-only to start. Sharing a profile, read-only or editable, could follow.
- Rule sets stay global, managed by an admin role.
- Move from SQLite to Postgres if several users will run jobs at once, and move the job queue out of process (for
  example RQ or Celery) if needed.
- Deployment: HTTPS, secrets handling, and backups for a hosted database.

## Smaller improvements

Smaller features and known gaps are
[GitHub issues labeled `enhancement`](https://github.com/randyscott/northward/issues?q=is%3Aissue+is%3Aopen+label%3Aenhancement).
They include computing the Social Security PIA from earnings history, dynamic spending rules, itemized deductions,
the ACA premium tax credit, Roth 5-year rules, and importing balances from brokerage exports.
