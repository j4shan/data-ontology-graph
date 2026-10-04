# Data Ontology Graph

A persistent knowledge graph of datasets, logical identities, entity
definitions, and relationships. Source-controlled YAML builds one read-only
current artifact. One local singleton service reads that artifact and exposes
sessionless JSON-RPC tools over a Unix-domain socket.

The DDL collector prepares schema-version-3 YAML from curated source catalogs
with a schema owner's review. It ships as the `ddl_collector` Python package
beside the graph core in this distribution and runs through `ddl-collector`.

## Requirements

1. Model logical entities and their relationships across addressable datasets
   without assuming every dataset is a SQL table.
2. Publish one validated current offline artifact from governed YAML.
3. Provide local search, lookup, and graph-navigation evidence for agent-built
   abstract knowledge graphs.

The product requirements are in the [project PRD](project_metadata/product/backend/project-prd.md)
and the [Data Modeling Spec](project_metadata/product/data/data-modeling-spec.md).
Detailed contracts live in [`project_metadata/product_spec/`](project_metadata/product_spec/).
[`project-description.md`](project_metadata/project_description/project-description.md) records the retired legacy inference model for
historical context.

## Setup

Python 3.12+ is required. Use [uv](https://docs.astral.sh/uv/) to create the
project virtual environment and install from `uv.lock`.

```bash
uv python install 3.12
uv venv --python 3.12
source .venv/bin/activate
uv sync --extra dev
```

`uv sync` makes the `.venv` match `uv.lock`: it installs this package and its
runtime dependencies, and it removes anything in the venv that is not in the
lockfile. `--extra dev` also installs `pytest`; without it, tests will not run.

## YAML intermediary

The initial target build path reads a finalized YAML directory through its sibling
`directory-manifest.yaml`, assembles the three collection types deterministically, validates the
result before ingestion, and materializes only the relationships defined there. The governed JSON
Schemas are under [`resources/schema/`](resources/schema/): `intermediary-directory.schema.json`
governs the manifest and `intermediary.schema.json` governs the assembled document. Graph tests
use the synthetic, single-file schema version `"3"` [lending fixture](tests/fixtures/lending/catalog.yaml).
It describes no real data source. DDL collector tests use a separate synthetic SQLite fixture
under [`tests/fixtures/minibank/`](tests/fixtures/minibank/).
Test data sources, reviewed reference catalogs, generated catalogs, published graph artifacts,
and AKG evaluation live in the sibling [Critic](../data-ontology-agent-critic/) project.

```python
from data_ontology_graph.builder import build_snapshot_from_yaml

snapshot, report, findings = build_snapshot_from_yaml(
    "path/to/catalog/yaml"
)
```

A directory catalog has this layout:

```text
catalog/
├── directory-manifest.yaml
└── yaml/
    ├── identities.yaml
    ├── customers.yaml
    ├── orders.yaml
    └── relationships.yaml
```

The manifest uses schema version `"3"` and names every collection file relative to `yaml/`:

```yaml
schema_version: "3"
logical_identities: identities.yaml
nodes:
  - customers.yaml
  - orders.yaml
edges: relationships.yaml
```

Each listed file also declares schema version `"3"` and contains exactly its named collection.
The identity and edge collections each have one owner file. One or more node files partition the
single assembled `nodes` list. Unlisted files, missing files, duplicate paths, paths outside the
YAML directory, mixed collection ownership, and conflicting schema versions block construction.
A finalized YAML directory may contain only `.yaml` and `.yml` files.

Single-file input remains available and is validated directly as an assembled intermediary.

The builder does not read SQLite catalogs, infer relationships, decompose composite primary keys,
or apply overlays. The DDL collector prepares YAML upstream; the builder validates its output
through the same gate used for manually authored YAML. Dependencies flow from `ddl_collector` to
`data_ontology_graph`, never back into the graph core.

## DDL collector

The first source family is SQLite. Its adapter opens the database read-only and gathers table
columns, declared primary and unique keys, foreign keys, and BIRD description CSVs. Read-only
profiling adds counts and relationship coverage by default; `--no-profile` skips it. Source
families collect structured evidence through a common protocol, while drafting is independent of
the source family. SQLite needs no extra dependencies. A future family needing drivers or
toolchains receives its own `ddl-collector-<family>` optional extra.

Run the stages from the repository root with a local Critic checkout:

```bash
uv run ddl-collector extract --critic-root ../data-ontology-agent-critic --catalog catalog_name --scratch scratch/catalog-review
uv run ddl-collector survey --scratch scratch/catalog-review
# The schema owner edits only the answer blocks in scratch/catalog-review/survey.md.
uv run ddl-collector apply --scratch scratch/catalog-review
uv run ddl-collector validate --scratch scratch/catalog-review
uv run ddl-collector publish --scratch scratch/catalog-review --catalog-root ../data-ontology-agent-critic/resources/data/generated_catalogs
```

Replace `catalog_name` with a catalog directory registered in Critic's
`resources/data/SOURCES.md`. The collector accepts any registered catalog directory.

`extract` checks every catalog file against Critic's `resources/data/SOURCES.md` hashes before
reading it. It creates a session with `session.yaml`, `evidence.json`, `decisions.yaml`,
`survey.md`, `draft/`, and `report.json` under the git-ignored `scratch/` directory. The survey
lists unresolved grain decisions before relationship decisions. Declared keys and observed data
are proposals; only the schema owner answers them. Repeated `apply` and `survey` rounds preserve
answers and report unresolved decisions and validation findings.

The draft has a sibling `directory-manifest.yaml` and a `yaml/` directory with `identities.yaml`,
one `nodes-<table>.yaml` per table, and `relationships.yaml`. Every physical column remains in
the draft. SQLite node IDs use `sqlite:<catalog>.<table>` and qualified names use
`<catalog>.<schema>.<table>`. The `accessor.sqlite.v1` properties include `host` (default
`localhost`), `schema`, `object`, and an absolute `database_path` under the configurable
`--source-root` (default `/opt/data-ontology/sources`). `--host` changes the accessor host.

Publication rechecks source hashes and requires resolved decisions, no draft findings, and a
valid catalog. It atomically writes `generated_catalogs/<catalog>/` in Critic with the manifest,
`yaml/`, `decisions.md`, and `provenance.yaml`. The provenance records source hashes, generation
details, review rounds, counts, and unknown claims. Generated catalogs are never committed here.
Agents preparing SQLite catalogs should follow
[the SQLite skill](skills/sqlite/SKILL.md).

Without activating the venv:

```bash
uv sync --extra dev --python 3.12
uv run pytest -q
```

## Local graph service

Build and replace the one current artifact, then start the singleton against its
stable directory:

```console
data-ontology-graph-publish \
  --yaml-dir path/to/finalized-yaml-directory \
  --artifact-dir path/to/current-graph
```

```bash
data-ontology-graph-server \
  --snapshot-dir path/to/current-graph \
  --socket /tmp/data-ontology-graph.sock
```

In another shell, call the same JSON-RPC request/response interface used by
production. Every call carries a request ID; fire-and-forget notifications are
not supported:

```bash
data-ontology-graph-client \
  --socket /tmp/data-ontology-graph.sock \
  graph.search \
  --params '{"query":"customer"}'
```

The service supports snapshot information, lexical search, identity and
dataset lookup, relationship detail, directed hops, breadth-first subgraph
expansion, and path retrieval. It does not generate or validate SQL.

### launchd singleton

Install a user-agent property list with the resolved Python and current-artifact
paths, then let `launchd` start the daemon:

```bash
data-ontology-graph-launchd install \
  --snapshot-dir path/to/current-graph \
  --socket /tmp/data-ontology-graph.sock \
  --log-dir "$HOME/Library/Logs/data-ontology-graph" \
  --output "$HOME/Library/LaunchAgents/com.data-ontology-graph.service.plist"
```

The service starts at login and restarts after unexpected failure. After publishing a new current
artifact, restart the in-memory daemon with:

```console
data-ontology-graph-launchd reload --snapshot-dir path/to/current-graph
```

The lifecycle command also supports `start`, `status`, and `uninstall`. It uses the configured
stable artifact path directly and performs no release discovery, version selection, or manifest
validation.
