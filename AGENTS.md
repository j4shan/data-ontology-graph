# Agent instructions

## Repository boundary

This repository stores source code, the YAML schema, and unit-test fixtures. Test data sources,
reviewed reference catalogs, published graph artifacts, AKG evaluation criteria, and results live
in the sibling `../critic` project, which evaluates this project as an actor.

- Do not add vendored databases, generated artifacts, or evaluation results here.
- Unit-test fixtures live under `tests/fixtures/<catalog>/`, one catalog per directory, and every
  `node_id` and `edge_id` in a fixture belongs to that catalog only.
