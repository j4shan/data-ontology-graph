# Project configuration

## Build

| ID | Clause |
| --- | --- |
| 1.1 | The graph core (`data_ontology_graph`) builds from `src/` into one Python distribution. |

## Test

| ID | Clause |
| --- | --- |
| 2.1 | Verification is limited to unit tests run with `pytest`. Integration, deployment, historical-release, rollback, performance, and AKG-benchmark tests are not release gates. |
| 2.2 | Unit-test fixtures live under `tests/fixtures/<catalog>/`, one catalog per directory, and every `node_id` and `edge_id` in a fixture belongs to that catalog only. |
| 2.3 | Graph tests use the synthetic single-file `lending` catalog, which describes no real data source. |
| 2.4 | Unit tests check that each committed JSON Schema agrees with its validator model. |
| 2.5 | Publisher tests cover successful replacement, rejection of invalid input, preservation of the current artifact after failure, prevention of mixed-build output, daemon configuration against the stable artifact path, and construction of the expected `launchctl` operations. |
| 2.6 | Graph-product acceptance checks that search, lookup, and navigation return the evidence of known definitions without inventing knowledge; that schema-invalid YAML is rejected before ingestion; and that result, traversal, and input-dataset bounds hold while concurrent requests stay responsive. |

## Packaging

| ID | Clause |
| --- | --- |
| 3.2 | Graph artifacts are published only outside this repository. A consumer that needs history versions the artifacts it publishes. |

## Development

| ID | Clause |
| --- | --- |
| 4.1 | This repository stores the graph core, the `query-graph-api` AKG skill in `skills/`, the YAML and AKG schemas, and unit-test fixtures. Test data sources, reference catalogs and AKGs, generated catalogs, published graph artifacts, evaluation criteria, and results live outside it. |
| 4.2 | Vendored databases, generated artifacts, and evaluation results are never added to this repository. |
| 4.3 | Contributors create the virtual environment with `uv` on Python 3.12 and install from `uv.lock` with `uv sync --extra dev`. |
| 4.5 | Execution plans live in `project_metadata/plans/` and are never versioned or cited as a source of requirements. |
| 4.6 | Agent tooling state and per-developer editor configuration, including `.agents/` and `.cursor/`, are never versioned. |
| 4.7 | A schema change and the definitions that depend on it are reviewed and committed together. |

## Toolchain

| ID | Clause |
| --- | --- |
| 5.1 | The project uses Python 3.12 or later, managed with `uv`. |
| 5.2 | Pydantic models validate the YAML intermediary and snapshot, and JSON Schema documents publish their contracts. |
| 5.3 | Lexical search uses `marisa-trie`. |
| 5.4 | The service lifecycle uses macOS `launchd`, driven by a Python command rather than shell scripts. |
