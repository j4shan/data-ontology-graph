# Data Ontology Graph

A persistent knowledge graph of datasets, logical identities, entity
definitions, and relationships. Source-controlled YAML builds one read-only
current artifact. One local singleton service reads that artifact and exposes
sessionless JSON-RPC tools over a Unix-domain socket.

## Requirements

1. Model logical entities and their relationships across addressable datasets
   without assuming every dataset is a SQL table.
2. Publish one validated current offline artifact from governed YAML.
3. Provide local search, lookup, and graph-navigation evidence for agent-built
   abstract knowledge graphs.

The product requirements are in the [project PRD](project_metadata/product/backend/project-prd.md)
and the [Data Modeling Spec](project_metadata/product/data/data-modeling-spec.md).
Detailed contracts live in [`project_metadata/product_spec/`](project_metadata/product_spec/).
[`project-description.md`](project-description.md) records the retired legacy inference model for
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

The initial target build path reads a finalized YAML directory, assembles its files
deterministically, validates the result before ingestion, and materializes only the relationships
defined there. The governed JSON
Schema and examples are under [`resources/schema/`](resources/schema/); the financial
reference is [`resources/data/dev_overlays/financial/catalog.yaml`](resources/data/dev_overlays/financial/catalog.yaml).

```python
from data_ontology_graph.builder import build_snapshot_from_yaml

snapshot, report, findings = build_snapshot_from_yaml(
    "path/to/finalized-yaml-directory"
)
```

Single-file input remains available. A finalized directory may contain only
`.yaml` and `.yml` files; duplicate or conflicting definitions block construction.

The target path does not read SQLite catalogs, infer relationships, decompose composite
primary keys, or apply overlays. Source translation and authoring happen before this gate.

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
  --artifact-dir data/current-graph
```

```bash
data-ontology-graph-server \
  --snapshot-dir data/current-graph \
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
  --snapshot-dir data/current-graph \
  --socket /tmp/data-ontology-graph.sock \
  --log-dir "$HOME/Library/Logs/data-ontology-graph" \
  --output "$HOME/Library/LaunchAgents/com.data-ontology-graph.service.plist"
```

The service starts at login and restarts after unexpected failure. After publishing a new current
artifact, restart the in-memory daemon with:

```console
data-ontology-graph-launchd reload --snapshot-dir data/current-graph
```

The lifecycle command also supports `start`, `status`, and `uninstall`. It uses the configured
stable artifact path directly and performs no release discovery, version selection, or manifest
validation.
