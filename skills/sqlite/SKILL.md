---
name: sqlite
description: Prepare schema-version-3 YAML catalogs from curated SQLite sources with the DDL collector and optional user review.
---

# Prepare a SQLite catalog

Use this skill to help the human user running the collector prepare one SQLite catalog from a local Critic checkout. The user may answer decisions or provide additional business information. The current collector still requires every decision to leave `open` before publication; evidence-backed defaults for unanswered decisions are planned. The `ddl_collector` package supplies extraction, read-only profiling, drafting, validation, and publication; this skill supplies the review procedure. Its SQLite adapter uses only the Python standard library. Run commands from the `data-ontology-graph` repository root after `uv sync --extra dev`.

Before preparing or validating YAML, consult the [intermediary schema](../../resources/schema/intermediary.schema.json) and [directory manifest schema](../../resources/schema/intermediary-directory.schema.json). They govern schema version `"3"`, required fields, collection ownership, and valid claims. Use the [survey format reference](templates/survey.md) when reviewing decisions and the [decision log format reference](templates/decisions.md) when checking the published log. The collector's read-only profiling queries are in [`sqlite_profile.sql`](../../src/ddl_collector/sources/sqlite_profile.sql).

## Inputs and stages

Set `<critic-root>` to the local `data-ontology-agent-critic` checkout and `<catalog>` to a directory under its `resources/data/dev_databases/`. Its files must be registered with SHA-256 hashes in Critic `resources/data/SOURCES.md`. Choose a distinct `scratch/<session_id>` for this attempt. Set `<catalog-root>` to `<critic-root>/resources/data/generated_catalogs`; the command creates or replaces `<catalog-root>/<catalog>/`.

| Stage | Exact command | Inputs and outputs |
| --- | --- | --- |
| 1. Extract | `uv run ddl-collector extract --critic-root <critic-root> --catalog <catalog> --family sqlite --scratch scratch/<session_id>` | Verifies source hashes, reads the SQLite database and BIRD `database_description/*.csv`, profiles read-only, and writes the session, first draft, survey, and report. |
| 2. Survey | `uv run ddl-collector survey --scratch scratch/<session_id>` | Regenerates `survey.md` from open and blocking decisions. Use after a review round if the user needs a fresh copy. |
| 3. Apply | `uv run ddl-collector apply --scratch scratch/<session_id>` | Reads the user's edited `survey.md`, preserves prior answers, rebuilds `draft/`, validates it, and updates `report.json` and the next survey. |
| 4. Validate | `uv run ddl-collector validate --scratch scratch/<session_id>` | Rebuilds and checks the current draft through the graph builder; reads findings, unknown claims, counts, and unresolved decision IDs from `report.json`. |
| 5. Publish | `uv run ddl-collector publish --scratch scratch/<session_id> --catalog-root <critic-root>/resources/data/generated_catalogs` | Rechecks source hashes and writes the finalized catalog, decision log, and provenance under Critic only if publication gates pass. |

`extract` profiles by default. Add `--no-profile` to stage 1 to skip read-only data profiling. Add `--source-root <absolute-posix-path>` or `--host <host>` to stage 1 to change the accessor location; defaults are `/opt/data-ontology/sources` and `localhost`. The default SQLite accessor path is `/opt/data-ontology/sources/<catalog>/<file>`, with schema and object properties beside it. The source root is a configurable default, not a project-wide deployment policy.

The git-ignored session directory contains `session.yaml`, `evidence.json`, `decisions.yaml`, `survey.md`, `draft/`, and `report.json`. The draft has `directory-manifest.yaml` beside `yaml/`, with `identities.yaml`, one `nodes-<table>.yaml` per table, and `relationships.yaml`. It keeps every physical column. Node IDs are `sqlite:<catalog>.<table>` and qualified names are `<catalog>.<schema>.<table>`.

## User review loop

1. The user may review `scratch/<session_id>/survey.md` and answer decisions. Have the user edit only each decision's `answer` block: `status`, `value` overrides of the proposal, and `rationale`. `{}` accepts the proposal. The user assesses business meaning before answering; declared keys and measured data are proposals, never final answers.
2. Review grain decisions first, then relationships. Every table has `grain.<table>`; every declared foreign key has `relationship.<table>.<columns>.<referenced table>`. All begin `open`. A primary key proposes `<table>_identity` with `entity_universe: unknown`; a table without a primary key proposes no columns. Relationship `a_to_b` reads from the referencing dataset. Without profiling, observed multiplicity and match existence stay `unknown`.
3. The user may choose `answered`, `unknown`, `waived`, or `blocking`; leave `open` to defer. An `unknown` or `waived` grain produces an explicit unknown grain. A relationship lacking a confirmed target grain identity produces a draft finding rather than an edge. Resolve that finding with the user's answer before publication.
4. Run `apply`, inspect `report.json`, and repeat `survey` and `apply` for remaining open or blocking decisions. Malformed answers return the problems without changing decisions. Do not edit `decisions.yaml` to bypass user review. `validate` reports builder findings, draft findings, `unknown_fields`, identity/node/edge counts, decision counts by status, and unresolved IDs.
5. Publish only after no decision is open or blocking, no draft finding remains, and the catalog validates. Publication refuses changed or unverifiable sources and leaves the prior catalog in place when a precondition fails. A successful catalog contains `directory-manifest.yaml`, `yaml/`, `decisions.md`, and `provenance.yaml`. Provenance includes verified hashes, generator version and git state, review rounds, counts, and unknown claims.

Source databases and profiling are read-only. Never place credentials in YAML, surveys, logs, commands, or other artifacts. Generated catalogs belong only in Critic `resources/data/generated_catalogs/`; never commit them to this repository. The builder accepts collector output only through its normal YAML validation gate. The command exits with 0 on success, 1 on validation failure or refused publication, and 2 on malformed surveys or invalid input.
