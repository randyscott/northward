# HTTP API

`northward serve` (or `make serve`) runs the API on the database at http://127.0.0.1:8000, with interactive docs at
`/docs`. The web UI uses this API, and you can script against it too.

The API has **no authentication**, so it listens on localhost only. `--host` makes it listen elsewhere, with a
warning; don't do that on a network you don't trust.

`northward openapi [FILE]` writes the OpenAPI schema. It includes the configuration document models (`AccountsDoc`,
`ScenarioDoc`, ...), so generated client types describe each document's `data`.

## Endpoints

All paths start with `/api`. Profiles and scenarios are addressed by name, and documents by their `data/` layout
address (`accounts`, `scenarios/base`).

| Endpoint | Purpose |
|---|---|
| `GET /health` | Engine version and database schema revision. |
| `GET/POST /profiles`, `GET/PATCH/DELETE /profiles/{profile}`, `POST .../restore` | List, create (from documents or `copy_from`), rename, delete, restore, and purge (`?purge=true`) profiles. |
| `GET /profiles/{profile}/documents`, `PUT` (batch) | Every document a profile can have, including optional ones it doesn't have yet. Save several at once, validated together. |
| `GET/PUT /profiles/{profile}/documents/{address}` | Read or save one document, as `yaml_text` or structured `data`. |
| `GET /documents/{id}[/revisions[/{rev}]]`, `.../diff`, `POST .../revisions/{rev}/restore` | Revision history, an old revision, diffs, and restoring a revision. |
| `GET/POST /profiles/{profile}/scenarios`, `GET/PATCH/DELETE .../{scenario}`, `POST .../restore` | Scenarios: create from content or `clone_from`, rename, delete, restore, purge. |
| `GET /rule-sets[/{name}[/documents/{kind}]]` | The shared rules (read-only; `data/rules/` is their master copy). |
| `GET /schemas/{kind}`, `POST /validate` | A document kind's JSON Schema. Check one document, or a set of changes as saving them would, without saving. |
| `POST /simulate/deterministic` | Run and record a deterministic simulation; returns the year table and the ledger. |
| `POST /simulate/montecarlo` | Queue a Monte Carlo run (202), or get an identical stored one (200, `cached: true`). |
| `GET /runs[/{id}]`, `POST /runs/{id}/cancel` | Run history, status, and progress; cancel a queued or running run. |
| `GET /runs/{id}/results` | Statistics and percentile bands (`buckets=`, `bands=false`), with one-off goal overrides (`liquidity_floor=`, ...). |
| `GET /runs/{id}/years` | A deterministic run's year table, recomputed from its pinned inputs. |
| `GET /runs/{id}/paths/{i}` | Re-run one path of a run on its pinned inputs, with the ledger. |
| `POST /compare` | Compare scenarios on the same draws. Queues missing runs (202); repeat the request until it returns 200. |

## Saving structured data

A `PUT` with `data` is merged into the document's current YAML text, so comments, key order, and formatting survive.
Only changed values are rewritten, and list items with an `id` keep their comments when reordered.

Pass `base_revision` (the revision you started editing from) to get a 409 instead of overwriting a newer save.

## Errors

Each error response has a `detail` message.

| Status | Meaning |
|---|---|
| 400 | A bad value. |
| 404 | A missing item. |
| 409 | A conflict: a name already in use, purging an item that isn't deleted, or a stale `base_revision`. |
| 422 | A configuration problem, with `issues` (`origin`, `location`, `message`, as `northward validate` prints them). Nothing is saved. Malformed requests also get a 422, with FastAPI's usual `detail` list. |

## Monte Carlo jobs

Monte Carlo runs execute one at a time in the background, each using every CPU. Their state is in the database:

- Stopping the server puts the active run back in the queue, and the next start resumes queued runs.
- A run whose process died is marked failed.
- Identical requests share a run.
- Progress is visible only to the server running the job, not to runs started from the CLI.
