# Agent instructions

## Repository boundary

This repository stores the graph core, the DDL collector in `src/ddl_collector/`, preparation
skills and the `query-graph-api` AKG skill in `skills/`, the YAML and AKG schemas, and unit-test
fixtures. Test data sources, reviewed reference catalogs and AKGs, generated catalogs, published
graph artifacts, AKG evaluation criteria, and results live in the sibling
`../data-ontology-agent-critic` project, which evaluates this project as an actor. Publish collector output only under Critic
`resources/data/generated_catalogs/<catalog>/`.

- Do not add vendored databases, generated artifacts, or evaluation results here.
- Unit-test fixtures live under `tests/fixtures/<catalog>/`, one catalog per directory, and every
  `node_id` and `edge_id` in a fixture belongs to that catalog only.
