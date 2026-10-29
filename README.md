# Data Ontology Graph

A persistent knowledge graph of datasets, logical entities, entity
definitions, and relationships. Source-controlled YAML builds one read-only
current artifact. One local singleton service reads that artifact and exposes
sessionless JSON-RPC tools over a Unix-domain socket.

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
It describes no real data source.
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
names, decompose composite primary keys, or apply overlays.

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
relationship detail, a dataset's directed edges, breadth-first subgraph expansion, ranked shortest paths,
and an approximate connecting subgraph for two to sixteen datasets. It does
not generate or validate SQL. For development, `data-ontology-graph-server` runs the service in
the foreground with the same defaults.
`graph.snapshot_info` reports the graph API `api_version` and the snapshot `version`, which
identifies the published data by its UTC build time. Republish the current artifact from the
YAML intermediary with `data-ontology-graph-publish` after a software upgrade.

## AKG contract and the query-graph-api skill

An abstract knowledge graph (AKG) selects graph datasets and directed edges for one analytical objective. It has no format version; its schema follows the graph API version. It stores datasets as response-shaped records in a list. Each selected directed edge remains an API array inside the start dataset's `edge_groups`; its position names appear in the document's `edge_fields`. Agent reasoning lives in dataset `usage`, entity-definition `usage` keyed by `edge_id`, comparisons, and gaps. Disconnected components are valid when the objective asks for separate facts or the graph lacks a connection.

The [query-graph-api skill](skills/query-graph-api/SKILL.md) documents best practices and bundles the [complete graph API reference](skills/query-graph-api/references/graph-api.md), [format guide](skills/query-graph-api/references/akg-format.md), and a [schema copy](skills/query-graph-api/references/akg.schema.json) identical to the public [AKG schema](resources/schema/akg.schema.json). Its `query.py` proxy prints each service result or error and keeps two files for one question: a JSON question file with logical entity names and a Markdown traversal file. For the context path `question.json`, these are `question.json` and `question.traversals.md`. The traversal file records requests and responses for directed-edge, subgraph, path, and connecting-subgraph calls, including service errors. The agent uses these files and the format guide to write the AKG at the caller's output path, or at `$GRAPH_WORK/akg.json`, with `status` set to `draft`.

From the repository root, run the service and make the first proxy call with `--question`. Later calls use the same context file; `--entity` records a logical entity name:

```bash
python3 skills/query-graph-api/scripts/service.py start
GRAPH_WORK=$(mktemp -d)
GRAPH_CONTEXT="$GRAPH_WORK/question.json"
python3 skills/query-graph-api/scripts/query.py snapshot_info --context "$GRAPH_CONTEXT" --question 'How many loans are there per region?'
python3 skills/query-graph-api/scripts/query.py get_edges '{"node_id":"sqlite:lending.loan"}' --context "$GRAPH_CONTEXT" --entity 'Account'
# After the agent writes the AKG to "$GRAPH_WORK/akg.json":
cd "$GRAPH_WORK"
data-ontology-graph-akg check akg.json
data-ontology-graph-akg finalize akg.json
data-ontology-graph-akg export akg.json --format markdown
```

After writing `akg.json`, use this repository's `data-ontology-graph-akg` command for review. `check` reports findings without changing the file; pass `--socket PATH` or `--yaml PATH` to also resolve it against a graph. `finalize` resolves datasets and directed edges against the graph service or a YAML intermediary, requires no errors, and sets `status` to `final`. `export` produces a read-only Markdown copy.
