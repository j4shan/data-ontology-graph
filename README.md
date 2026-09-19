# Data Ontology Graph

A persistent knowledge graph of a SQL data warehouse: datasets, entity
identity, and join relationships. A user can update the tracked model by
changing in-repo evidence and rebuilding a new snapshot. An HTTP ontology API
reads that snapshot; it does not mutate graph knowledge.

## Requirements

1. Model a SQL data warehouse and track entities and entity relationships in a
   graph.
2. Accept user requests that update the tracked data model.
3. Provide a data-ontology API that assists composing SQL queries.

Product requirements live in [`project_metadata/product_spec/`](project_metadata/product_spec/).
The domain-model contract is [`project-description.md`](project-description.md).

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
lockfile. `--extra dev` also installs the optional `dev` extra from
[`pyproject.toml`](pyproject.toml) (`pytest` and `httpx`). Without `--extra
dev`, tests will not run because those packages are not default dependencies.

Without activating the venv:

```bash
uv sync --extra dev --python 3.12
uv run pytest -q
uv run uvicorn data_ontology_graph.api.app:app --reload
```

## Demo

The demo is a read-only HTTP API with OpenAPI. There is no interactive UI.
Tests write a snapshot, then exercise the API with pytest against the BIRD
Mini-Dev SQLite databases in
`resources/data/dev_databases/`. These databases and their schema-description
CSV files come from the [BIRD Mini-Dev benchmark](https://github.com/bird-bench/mini_dev),
not from this project. Download the SQLite databases from the [official BIRD
Mini-Dev dataset](https://huggingface.co/datasets/birdsql/bird_mini_dev) and
place each catalog at `resources/data/dev_databases/<database>/`, with its
`<database>.sqlite` file and `database_description/` directory inside. The
downloaded database tree is ignored by Git and is not included in this
repository; local tests that use it require a separate download.

```bash
pytest
```

```bash
uvicorn data_ontology_graph.api.app:app --reload
```

OpenAPI is at `/openapi.json`.
