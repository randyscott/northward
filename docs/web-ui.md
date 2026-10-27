# Web UI

`make ui` builds the browser app, and `make serve` serves it, with the API, at http://127.0.0.1:8000. It needs
Node.js 20.19 or newer to build.

- **Profiles:** create one (blank, or a copy of another), switch between them, rename, delete, and restore. A
  profile's overview lists every document it can have, with a description of each, and its scenarios.
- **Documents** are edited as YAML in an editor that knows each document's schema:
  - It completes field names, shows descriptions on hover, and underlines problems as you type.
  - When saving finds a problem, the editor marks the line it points at, and lists problems the change would cause
    in other documents.
  - Every save is a revision. The **History** tab shows the differences between any two revisions and can restore one.
  - If the document was saved elsewhere (another tab, or the CLI) since you opened it, saving is refused rather than
    overwriting that change.
- **Balances:** a grid of every account's balance (and cost basis), saved as one revision without touching the rest
  of the file. Useful for quarterly updates from statements.
- **Scenarios:** clone, rename, delete, and edit them (including `overrides`), and run them deterministically or with
  Monte Carlo.
- **Results:**
  - the probability of success, with success criteria you can change without rerunning
  - a range (percentile bands) of net worth over time, in today's or nominal dollars
  - one path in detail (the median, or another percentile): balances by account type, taxes by type, income by
    source, the year-by-year table, and the ledger
  - every chart can switch to a table of its numbers
- **Run history** reopens past results without rerunning, and shows progress (with cancel) for active runs.
- **Compare** runs two to four scenarios on the same simulated markets and shows the differences.

Forms for documents other than balances are planned ([roadmap](roadmap.md)). Until then, documents are edited as YAML.
