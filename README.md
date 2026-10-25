# Data Ontology Graph

A persistent knowledge graph of datasets, logical entities, entity
definitions, and relationships. Source-controlled YAML builds one read-only
current artifact. One local singleton service reads that artifact and exposes
sessionless JSON-RPC tools over a Unix-domain socket.

The DDL collector prepares schema-version-3 YAML from curated source catalogs.
The user running it may review and answer decisions. The collector ships as the
`ddl_collector` Python package beside the graph core in this distribution and
runs through `ddl-collector`.

## Requirements

1. Model logical entities and their relationships across addressable datasets
   without assuming every dataset is a SQL table.
2. Publish one validated current offline artifact from governed YAML.
3. Provide local search, lookup, and graph-navigation evidence for agent-built
   abstract knowledge graphs.

Project decisions live under [`project_metadata/`](project_metadata/):
[product functions](project_metadata/product/functional.md) and
[qualities](project_metadata/product/non_functional.md),
[system design](project_metadata/system_design/functional.md) and its
[non-functional design](project_metadata/system_design/non_functional.md), and
[project configuration](project_metadata/project_configuration.md).

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
`directory-manifest.yaml`, assembles the logical entity and node collections deterministically,
validates the result before ingestion, and derives one relationship for every two entity
definitions of the same logical entity. Multiplicity and match existence come from each
definition's `unique`, `total`, `conforms`, and `entity_universe` properties. The governed JSON
Schemas are under [`resources/schema/`](resources/schema/): `intermediary-directory.schema.json`
governs the manifest and `intermediary.schema.json` governs the assembled document. Graph tests
use the synthetic, single-file schema version `"4"` [lending fixture](tests/fixtures/lending/catalog.yaml).
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
    └── orders.yaml
```

The manifest uses schema version `"4"` and names every collection file relative to `yaml/`:

```yaml
schema_version: "4"
logical_identities: identities.yaml
nodes:
  - customers.yaml
  - orders.yaml
```

Each listed file also declares schema version `"4"` and contains exactly its named collection.
The logical entity collection has one owner file. One or more node files partition the
single assembled `nodes` list. Unlisted files, missing files, duplicate paths, paths outside the
YAML directory, mixed collection ownership, and conflicting schema versions block construction.
A finalized YAML directory may contain only `.yaml` and `.yml` files.

Single-file input remains available and is validated directly as an assembled intermediary.

The builder does not read SQLite catalogs, infer relationships from database keys or column
names, decompose composite primary keys, or apply overlays. The DDL collector prepares YAML upstream; the builder validates its output
through the same gate used for manually authored YAML. Dependencies flow from `ddl_collector` to
`data_ontology_graph`, never back into the graph core.

## DDL collector

The collector is deprecated. It still writes schema version `"3"` with authored
relationships, which the graph builder no longer accepts.

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
# The user may edit the answer blocks in scratch/catalog-review/survey.md.
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
are proposals; the user may answer them. The current collector publishes only after every
decision is answered, unknown, or waived; defaulting unanswered decisions is planned. Repeated
`apply` and `survey` rounds preserve answers and report unresolved decisions and validation
findings.

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

The service and its files live in one private, per-user service home, `~/.data-ontology-graph`
(or `$DOG_HOME`):

| Path | Content |
| --- | --- |
| `current-graph/` | The published artifact |
| `service.plist` | The on-demand `launchd` job that runs the service |
| `graph.sock` | The service socket, present only while the service runs |
| `logs/` | Service output and error logs |

Publish the current artifact into the home, then set up the job once:

```console
data-ontology-graph-publish --yaml-dir path/to/finalized-yaml-directory
data-ontology-graph-launchd setup
```

The service runs only on demand. Nothing starts it at login, because the job's property list sits
in the service home rather than in `~/Library/LaunchAgents`. Start and stop it as needed; while it
is started, `launchd` restarts it after an unexpected failure, and logging out stops it:

```console
data-ontology-graph-launchd start     # waits until the service answers
data-ontology-graph-launchd status
data-ontology-graph-launchd reload    # after publishing a new artifact
data-ontology-graph-launchd stop
```

Every command finds the socket by itself: an explicit `--socket`, then `$DOG_SOCKET`, then the
service home's. Call the same JSON-RPC request/response interface used by production. Every call
carries a request ID; fire-and-forget notifications are not supported:

```bash
data-ontology-graph-client graph.search --params '{"query":"customer"}'
```

The service supports snapshot information, lexical search, logical entity and dataset lookup,
relationship detail, a dataset's directed edges, breadth-first subgraph expansion, and k-shortest route retrieval. It does
not generate or validate SQL. For development, `data-ontology-graph-server` runs the service in
the foreground with the same defaults.

## AKG contract and the query-graph-api skill

An abstract knowledge graph (AKG) is the subset of graph datasets and relationships that an agent
selects for one objective. One JSON file holds the whole objective: datasets keyed by `node_id`,
each holding the directed edges the agent traverses from it, trimmed graph fields such as name,
source, grain, and the columns that matter, and the agent's reasoning under each dataset's and
directed edge's `usage`, plus gaps and comparisons. Connected components are derived from the
directed edges; disconnected components are
a valid answer when the objective asks for unrelated facts or the graph lacks a connection, which
the AKG records as a data gap.

[`resources/schema/akg.schema.json`](resources/schema/akg.schema.json) is the public contract. The
[`query-graph-api` skill](skills/query-graph-api/SKILL.md) builds an AKG file incrementally in file
mode: it discovers through `scripts/graph_call.py` and writes the file only through
`scripts/akg.py`, which copies graph objects from the service and never changes a graph field
already present. `scripts/service.py start|stop|status` starts and stops the on-demand service
for the agent. The scripts are standard-library only and find the service by themselves.

```bash
python3 skills/query-graph-api/scripts/service.py start
python3 skills/query-graph-api/scripts/akg.py init akg.json --question "..."
python3 skills/query-graph-api/scripts/akg.py add-edge akg.json NODE_ID EDGE_ID
data-ontology-graph-akg check akg.json                          # findings by severity
data-ontology-graph-akg finalize akg.json                       # or --yaml PATH
data-ontology-graph-akg export akg.json --format markdown       # read-only copy for review
```

`check` never refuses to load a parseable file; `finalize` requires no error, resolves every
dataset and directed edge against the service or the YAML intermediary, and marks the file
`final`.
