# System design: functional

## Structure

| ID | Clause |
| --- | --- |
| 1.1 | The graph builder is the only component that creates relationships. No other component inserts, edits, or deletes one. |
| 1.2 | The publisher builds and validates a complete candidate and owns replacement of the one current graph artifact at a caller-supplied path. |
| 1.3 | One OS-managed background graph service loads the current artifact and serves every local request. It keeps the snapshot, the static lexical trie, object maps, graph adjacency, and disposable caches in memory as service infrastructure, never as reasoning-session state. |
| 1.4 | The `data-ontology-graph-launchd` command manages the service as an on-demand, user-owned `launchd` job whose property list lives in the service home, outside the directories `launchd` loads at login. `launchd` manages the process while the job is loaded; neither it nor the application manages a release history. |
| 1.5 | The DDL collector in `src/ddl_collector/` and the source-family skills under `skills/` prepare project-schema YAML upstream of the builder. They depend on the graph core's model and builder APIs; the graph core never depends on them. |
| 1.6 | Collector output enters construction only as a finalized YAML intermediary through the builder's validation gate. The builder accepts no collector evidence or decisions as alternate input. |
| 1.7 | Source families collect structured evidence through one common protocol, and drafting is independent of the source family. |
| 1.8 | Each preparation skill directory under `skills/` covers exactly one data-source family, such as SQLite. A skill may reuse shared contracts or utilities but never combines preparation logic for several families. |
| 1.9 | Every preparation skill has a `SKILL.md` that links to the target `intermediary.schema.json` and requires the agent to consult it before preparing or validating YAML. |
| 1.10 | Each preparation skill bundles a source-appropriate DDL parser that keeps source locations and unsupported constructs for agent review. |
| 1.11 | Each preparation skill bundles a fillable survey template that supports repeated review rounds without losing prior answers or decision IDs. |
| 1.12 | Each preparation skill bundles parameterized read-only profiling queries for row counts, null counts, distinctness and uniqueness, candidate-key checks, relationship coverage, and unmatched records. |
| 1.13 | Each preparation skill bundles commands to inspect the deployed source and run its queries without embedding credentials or assuming the DDL resource is the deployed database. |
| 1.14 | Preparation provides a validator that checks every draft and finalized artifact against the target schema and reports YAML locations and violated rules. |
| 1.15 | The `query-graph-api` skill in `skills/query-graph-api/` guides an agent to build AKGs and is not a preparation skill. It reaches graph knowledge only through the public JSON-RPC interface, using a bundled standard-library client (`scripts/graph_call.py`), AKG file editor (`scripts/akg.py`), and service controller (`scripts/service.py`), which starts, stops, and checks the on-demand service. |

## Interfaces

### Local tool interface

| ID | Clause |
| --- | --- |
| 2.1.1 | The service exposes one JSON-RPC 2.0 request/response interface over a Unix-domain socket. Every call carries a request `id` and receives exactly one result or error. Notifications are not supported, and HTTP/OpenAPI is not part of the interface. |
| 2.1.2 | The methods are snapshot information, lexical search, identity and dataset lookup, relationship detail, directed hops, breadth-first subgraph expansion, ranked paths, and connecting subgraphs. `graph.snapshot_info` reports the served artifact's version and schema fingerprint. |
| 2.1.3 | Responses are uncompressed text that the agent reads as sent. Response size is reduced by response structure, not transport compression. |
| 2.1.4 | Each operation returns a lightweight default and lets the caller request non-default metadata. |
| 2.1.5 | Every dataset, entity definition, and relationship in a response carries `unknown_fields`, the typed claims whose value is `unknown`. Hops and path steps name them relative to the traversal (`direction.*`, `reverse_direction.*`); canonical relationship detail names them `a_to_b.*` and `b_to_a.*`. |

### Search

| ID | Clause |
| --- | --- |
| 2.2.1 | `graph.search` takes an optional `kind`, a non-empty list of `identity`, `dataset`, `entity_definition`, and `column`. Omitting it searches all four. |
| 2.2.2 | Candidates may match a stable ID, business name, synonym, tag, description, qualified dataset name, accessor property, dataset-column set, column metadata, or entity metadata. |
| 2.2.3 | The response has one group per requested kind, in the order `column`, `dataset`, `entity_definition`, `identity`. Each group holds `subject_rows` read through `subject_row_header` and `match_rows` read through `match_row_header`, joined by `key`. |
| 2.2.4 | Subject rows are `column`: `key`, `node_id`, `column_name`; `dataset`: `key`, `display_name`, `unknown_fields`; `entity_definition`: `key`, `entity_expression`, `node_id`, `identity_id`, `dataset_columns`, `unknown_fields`; `identity`: `key`, `name`. Match rows are `key`, `match_type`, `match_field`, `matched_term`, `matched_value`. |
| 2.2.5 | A subject has one match row per matching field value. `match_field` names the property holding `matched_value`, the original text, and `matched_term` is the normalized text that matched. Stored terms are the whole normalized value and each of its words. |
| 2.2.6 | `exact` means a stored term equals the normalized query, and `prefix` means a stored term starts with it. For a multi-word query against a word-match value, `phrase` means consecutive words of the value start with the query words in order, and `all_words` means each query word starts some word of the value. All query words must occur in the same value. |
| 2.2.7 | A value matching several ways reports only its best type, in the order `exact`, `prefix`, `phrase`, `all_words`. Values other than the word-match values match a multi-word query only when they start with the phrase. |
| 2.2.8 | Subjects are ordered by best match type, then normalized label, then key; a subject's match rows by match type, then field. The result limit applies to each group separately. A group's `truncated` is true when the limit omits eligible subjects, and the response's `truncated` is true when any group's is. |

### Navigation

| ID | Clause |
| --- | --- |
| 2.3.1 | `graph.get_hops` returns one `hops` row per relationship step from the requested node, in ascending `edge_id` order, with claims oriented to that step. An optional `limit`, default 100 and maximum 1000, caps the hops, and `truncated` reports whether more exist. |
| 2.3.2 | `graph.get_identity` returns the identity's `entity_definitions` ordered by `node_id`, then `dataset_columns`, with their datasets in `datasets`, under the same limit and `truncated` rule. An optional `entity_universe` filter applies before the limit. |
| 2.3.3 | `graph.expand_subgraph` takes dataset seeds, a maximum depth, and result-item bounds. It returns `datasets` in (distance, `node_id`) order with each `distance` from a seed, their `columns` and `entity_definitions`, and the selected edges in `relationships`, all within the bounds. |
| 2.3.4 | `graph.find_paths` takes two datasets, a maximum hop count, a result-item limit, and optional `allowed_multiplicities`. It returns `path_count` and `hops` rows whose first column `path` is the path's rank from 0. Each step carries both directional claims oriented to the step. |
| 2.3.5 | Ranked-path search proceeds in rank order and stops once the limit is filled and one further path shows that the result is `truncated`. |
| 2.3.6 | `graph.get_relationship` takes an `edge_id` and an optional `from_node_id`, which must name one of the edge's endpoints. It always returns canonical `endpoint_a`, `endpoint_b`, `a_to_b`, and `b_to_a`. With `from_node_id`, `direction` holds claims moving away from that node and `reverse_direction` claims moving toward it; without it, both are null. The relative fields are a view and never change the stored edge. |
| 2.3.7 | Relationship detail exposes its `identity_id`, endpoint node IDs and dataset-column sets, and relationship identity, with both endpoint datasets and entity definitions listed alongside. |
| 2.3.8 | `graph.find_connecting_subgraph` takes the selected datasets in `node_ids`. It returns `status` (`completed` or `disconnected`), the tree's datasets in tree order with their `columns` and `entity_definitions`, and the tree's edges in `relationships`. A disconnected response returns the endpoint datasets and no relationships. |

### Graph-object responses

| ID | Clause |
| --- | --- |
| 2.4.1 | `graph.get_identity`, `graph.get_relationship`, `graph.get_hops`, `graph.find_paths`, `graph.expand_subgraph`, and `graph.find_connecting_subgraph` list each graph object once, keyed by its identifier, and express hops, paths, and subgraph membership as references to those keys. |
| 2.4.2 | The `hops` collection has `edge_id`, `from_node_id`, `to_node_id`, `direction.multiplicity`, `direction.match_existence`, `reverse_direction.multiplicity`, `reverse_direction.match_existence`, and `unknown_fields`; `graph.find_paths` adds `path` first. |
| 2.4.3 | The `relationships` collection, in `edge_id` order, has `edge_id`, `identity_id`, `endpoint_a.node_id`, `endpoint_a.dataset_columns`, `endpoint_b.node_id`, `endpoint_b.dataset_columns`, `a_to_b.multiplicity`, `a_to_b.match_existence`, `b_to_a.multiplicity`, `b_to_a.match_existence`, `unknown_fields`, and `annotation`. |
| 2.4.4 | The `datasets` collection, in `node_id` order or a subgraph's node order, has `node_id`, `descriptor.qualified_name`, `descriptor.display_name`, `descriptor.description`, `descriptor.synonyms`, `descriptor.tags`, `accessor.schema_id`, and `accessor.properties`. Subgraph responses add `grain` and `unknown_fields`, and `graph.expand_subgraph` adds `distance` after `node_id`. |
| 2.4.5 | The `entity_definitions` collection has `node_id`, `identity_id`, `dataset_columns`, `entity_universe`, `entity_expression`, `entity_metadata`, `description`, `effective_description`, `description_source`, and `unknown_fields`. `effective_description` is the definition's own `description` (`description_source` `entity`), else the description of its single column when every `entity_expression` is that bare or bracket-, quote-, or backtick-wrapped column (`column`), else null; it serves `product/graph-model.md#1.10`. The `columns` collection of subgraph datasets has `node_id`, `name`, `description`, `value_description`, and `synonyms`. |
| 2.4.6 | A relationship endpoint's entity definition is the `entity_definitions` row with the endpoint's `node_id` and `dataset_columns` and the relationship's `identity_id`. Hops, paths, and relationship detail list only referenced definitions; subgraph responses list every definition of their datasets. |
| 2.4.7 | A step records its traversal with `from_node_id` and `to_node_id`, and its claims and `unknown_fields` are oriented to that traversal, so a caller never inverts canonical claims. Different steps may traverse the same relationship in opposite directions. |
| 2.4.8 | Each of these methods accepts `response_format`. `"table"`, the default, renders each collection as `{"header": [...], "rows": [[...]]}`, where a dotted column name is a path into the record. `"records"` renders the same content as a list of nested JSON objects. Any other value is rejected as invalid params. |

### Build, publication, and preparation commands

| ID | Clause |
| --- | --- |
| 2.5.1 | `build_snapshot_from_yaml(path)` takes an assembled YAML file or a finalized `yaml/` directory and returns the snapshot, the build report, and validation findings. |
| 2.5.2 | `data-ontology-graph-publish` takes a finalized YAML directory and replaces the current artifact, by default in the service home. `data-ontology-graph-server` serves a snapshot directory on a socket path, by default the service home's, and `data-ontology-graph-client` calls the same interface used in production. |
| 2.5.3 | `data-ontology-graph-launchd` provides `setup`, which writes the job's property list into the service home without starting it, and `start`, `stop`, `reload`, and `status`. `start` and `reload` wait until the service answers `graph.snapshot_info`. |
| 2.5.4 | `ddl-collector` provides the stages `extract`, `survey`, `apply`, `validate`, and `publish` over one scratch session. |
| 2.5.5 | The service home is one private, per-user directory, `~/.data-ontology-graph` or `$DOG_HOME`, created with owner-only permissions. It holds the job's property list (`service.plist`), the current artifact (`current-graph/`), the socket while the service runs (`graph.sock`), and the logs (`logs/`). Every command and bundled script resolves the socket as an explicit `--socket`, then `$DOG_SOCKET`, then the service home's. |

### AKG contract

| ID | Clause |
| --- | --- |
| 2.6.1 | The public AKG contract is the JSON Schema `resources/schema/akg.schema.json` with the format reference bundled in the `query-graph-api` skill. One JSON document holds one objective: `status` (`draft` or `final`), `question`, an optional `objective` and graph snapshot, `datasets` keyed by `node_id`, `relationships` keyed by canonical edge ID, and optional `comparisons` and `gaps` keyed by agent-chosen IDs. Datasets carry the trimmed graph fields `name`, `source`, and optionally `grain`, `columns`, `description`, `entity_definitions`, `synonyms`, `tags`, and `stats`; relationships carry their canonical endpoints and both direction claims. Agent reasoning lives only under each element's `usage`, in `comparisons`, and in `gaps`. Unknown keys are allowed anywhere. The schema is self-contained and is generated from a lenient model. |
| 2.6.2 | `scripts/akg.py` edits an AKG file. It copies graph fields from service responses at a chosen detail level, never writes accessor properties, entity expressions, entity metadata, or unknown-field lists, and never changes a graph field already present: adding is idempotent and only fills in missing graph fields. Adding a relationship also adds its missing endpoint datasets. Removal refuses while other elements refer to the target unless cascaded. Agent fields change only through merge-patches to `usage`, `gaps`, and `comparisons`. Every write is atomic and resets `status` to `draft`. Statistics enter as `stats` once the graph serves them. |
| 2.6.3 | `data-ontology-graph-akg check FILE` reports findings by location, rule, and severity (`error`, `warning`, or `info`) and never refuses to load a parseable document; with `--socket PATH` or `--yaml PATH`, it also resolves every dataset and relationship against the graph service or the YAML intermediary and reports each mismatch by element and field. `finalize` requires no error, treats dangling references as errors, requires that resolution, and then sets `status` to `final`. `export --format markdown` writes a deterministic, read-only copy for human review. |

## Data

### Intermediary

| ID | Clause |
| --- | --- |
| 3.1.1 | The intermediary uses schema version `"3"`. Source-controlled JSON Schemas under `resources/schema/` govern the directory manifest (`intermediary-directory.schema.json`) and the assembled intermediary (`intermediary.schema.json`). |
| 3.1.2 | A finalized directory has a fixed `directory-manifest.yaml` beside its `yaml/` directory. The manifest names, relative to `yaml/`, exactly one logical-identity file, one or more node files, and exactly one edge file. |
| 3.1.3 | Each collection file declares schema version `"3"` and contains exactly its manifest-owned collection. Node files partition the assembled node list; identities and edges are not partitioned. |
| 3.1.4 | Manifest paths are relative, stay within the YAML directory after resolution, and name existing `.yaml` or `.yml` files. Absolute paths, parent traversal, symlink escapes, duplicate paths, missing files, and unlisted files are rejected. |
| 3.1.5 | A finalized YAML directory contains only manifest-listed collection files. The manifest and the durable decision log sit beside it, not inside it. |
| 3.1.6 | `dataset_columns` is a non-empty, duplicate-free list in ascending exact-name order, and every member exists in the node's column inventory. |
| 3.1.7 | A grain component that names an `identity_id` resolves to an entity definition with the same column set on that node. |
| 3.1.8 | The node-ID composition rule lives in the intermediary schema. SQLite node IDs are `sqlite:<catalog>.<table>`, and SQLite qualified names are `<catalog>.<schema>.<table>`. |

### Accessors

| ID | Clause |
| --- | --- |
| 3.2.1 | During deserialization, a known accessor `schema_id` selects its subtype validator. The validated properties stay available as the original JSON object. |
| 3.2.2 | Accessor subtype schemas are registered in source code. A new accessor kind needs its schema ID and property validator before the builder accepts it. |
| 3.2.3 | `accessor.sqlite.v1` records `host`, an absolute `database_path`, `schema`, and `object`; `main` is the schema of a directly opened database file. |

### Relationships

| ID | Clause |
| --- | --- |
| 3.3.1 | A stable edge identity derives from the canonical unordered pair of endpoint references. `endpoint_a` precedes `endpoint_b` in ascending lexical order of `node_id`, `identity_id`, and `dataset_columns`; reversing an authored pair swaps its `a_to_b` and `b_to_a` claims. The snapshot persists and reloads that canonical order. |
| 3.3.2 | An edge stores its endpoint references and relationship properties only. Entity expressions, expression context, accessor information, and other node metadata stay on the connected nodes. |

### Snapshot

| ID | Clause |
| --- | --- |
| 3.4.1 | A snapshot carries its data-contract `version` (`5.0`), a `schema_fingerprint` of the node, identity, relationship, and annotation schemas, a UTC `built_at`, and its logical identities, nodes, edges, and annotations. |
| 3.4.2 | A snapshot rejects duplicate node, logical-identity, or edge IDs and references to unknown nodes, identities, entity definitions, or edges. |
| 3.4.3 | All files of one persisted snapshot agree on version, build time, and schema fingerprint. |
| 3.4.4 | The artifact's schema version identifies its data contract, not an application-managed release. |

### Search index

| ID | Clause |
| --- | --- |
| 3.5.1 | The search index is a static `marisa-trie` `RecordTrie` of mechanically normalized terms. Posting records reference authoritative snapshot objects rather than duplicating them; several terms, including synonyms, may reference one object, and one term may reference several objects. |

### Preparation records

| ID | Clause |
| --- | --- |
| 3.6.1 | During preparation, the survey, decision log, draft YAML, parsed DDL output, and collected statistics live in a temporary session workspace: `session.yaml`, `evidence.json`, `decisions.yaml`, `survey.md`, `draft/`, and `report.json`. |
| 3.6.2 | A draft holds `directory-manifest.yaml` beside `yaml/`, which holds `identities.yaml`, one `nodes-<table>.yaml` per table, and `relationships.yaml`. |
| 3.6.3 | A published generated catalog in Critic holds `directory-manifest.yaml`, `yaml/` with the finalized collection files, `decisions.md` with the durable decision log, and `provenance.yaml` beside `yaml/`. Provenance records source hashes, generation details, review rounds, counts, and unknown claims. |

## Flows

| ID | Clause |
| --- | --- |
| 4.1 | For directory input, the build validates the sibling manifest, path containment, file inventory, collection ownership, and schema-version agreement; assembles the three collections; and validates the result against the intermediary schema. Single-file input is validated directly as an assembled intermediary. |
| 4.2 | After the schema gate, construction validates node and logical-identity references, canonical column sets, entity-definition uniqueness, endpoint resolution, shared endpoint identity, multiplicity, match existence, the descriptor, the accessor subtype, the grain or explicit unknown grain, the column inventory, and definition-scoped `entity_universe`. It then indexes logical identities and entity definitions, derives stable edge identities, and writes the snapshot. |
| 4.3 | Publication builds and reload-validates a complete candidate, replaces the current-artifact directory as one unit, restores the prior artifact if promotion fails, and removes its transient backup after success. |
| 4.4 | After a publication, the maintainer reloads the in-memory service against the stable artifact path. |
| 4.5 | The lifecycle command resolves the artifact path, verifies the artifact exists and loads, writes the `launchd` property list into the service home at `setup`, and at `start`, `stop`, and `reload` invokes only the `launchctl` operation the job's loaded state requires, then calls `graph.snapshot_info` to verify the running service. It never searches for a newest artifact, compares versions or timestamps, follows a `latest` pointer, or validates a release manifest. |
| 4.6 | The intended agent interaction is progressive: discover candidate entities, inspect selected entities, and retrieve relationship evidence through lookup or navigation. |
| 4.7 | Connecting-subgraph search uses a polynomial-time undirected Steiner-tree approximation based on Mehlhorn's multi-source approach. Connectivity treats relationships as traversable in either direction, while responses keep both directional claims. |
| 4.8 | Preparation runs in stages: initialize a temporary workspace and inspect the target schema; parse static resources with source locations; inspect the deployed source with bundled read-only queries; draft the manifest and collection YAML; inquire through the survey; iterate on optional answers, defaults, and validation; and finalize. |
| 4.9 | `extract` checks every catalog file against the hashes in Critic's `resources/data/SOURCES.md` before reading it. `publish` rechecks source hashes and atomically writes the generated catalog under Critic `resources/data/generated_catalogs/<catalog>/`. |
