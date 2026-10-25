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
| 2.1.2 | The methods are snapshot information, lexical search, logical entity and dataset lookup, relationship detail, a dataset's edges, breadth-first subgraph expansion, ranked paths, and connecting subgraphs. `graph.snapshot_info` reports the served artifact's version and schema fingerprint. |
| 2.1.3 | Responses are uncompressed text that the agent reads as sent. Response size is reduced by response structure, not transport compression. |
| 2.1.4 | Each operation returns a lightweight default and lets the caller request non-default metadata. Navigation methods do so through detail levels and added fields (2.4.6–2.4.8). |
| 2.1.5 | Every dataset, entity definition, and relationship in a response carries `unknown_fields`, the typed claims whose value is `unknown`. A directed edge names them relative to the dataset it leaves (`multiplicity`, `match_existence`, `reverse_multiplicity`, `reverse_match_existence`); canonical relationship detail names them `a_to_b.*` and `b_to_a.*`. |

### Search

| ID | Clause |
| --- | --- |
| 2.2.1 | `graph.search` takes an optional `kind`, a non-empty list of `identity`, `dataset`, `entity_definition`, and `column`. Omitting it searches all four. |
| 2.2.2 | Candidates may match a stable ID, business name, synonym, tag, description, qualified dataset name, accessor property, dataset-column set, column metadata, or entity metadata. |
| 2.2.3 | The response has one group per requested kind, in the order `column`, `dataset`, `entity_definition`, `identity`. Each group holds `subject_rows` read through `subject_row_header` and `match_rows` read through `match_row_header`, joined by `key`. |
| 2.2.4 | Subject rows are `column`: `key`, `node_id`, `column_name`; `dataset`: `key`, `qualified_name`, `unknown_fields`; `entity_definition`: `key`, `entity_expression`, `node_id`, `identity_id`, `dataset_columns`, `unknown_fields`; `identity`: `key`, `name`. Match rows are `key`, `match_type`, `match_field`, `matched_term`, `matched_value`. |
| 2.2.5 | A subject has one match row per matching field value. `match_field` names the property holding `matched_value`, the original text, and `matched_term` is the normalized text that matched. Stored terms are the whole normalized value and each of its words. |
| 2.2.6 | `exact` means a stored term equals the normalized query, and `prefix` means a stored term starts with it. For a multi-word query against a word-match value, `phrase` means consecutive words of the value start with the query words in order, and `all_words` means each query word starts some word of the value. All query words must occur in the same value. |
| 2.2.7 | A value matching several ways reports only its best type, in the order `exact`, `prefix`, `phrase`, `all_words`. Values other than the word-match values match a multi-word query only when they start with the phrase. |
| 2.2.8 | Subjects are ordered by best match type, then normalized label, then key; a subject's match rows by match type, then field. The result limit applies to each group separately. A group's `truncated` is true when the limit omits eligible subjects, and the response's `truncated` is true when any group's is. |

### Navigation

| ID | Clause |
| --- | --- |
| 2.3.1 | Every navigation method runs on one internal traversal with three parts. Neighbour listing turns each endpoint of a relationship that lies on a dataset into one directed edge leaving that dataset (`product/graph-model.md#3.8`); it is the only place a relationship becomes a directed edge. Bounded expansion walks breadth-first from one or more seeds under a depth, result bounds, and an optional directed-edge filter on logical entity ID and multiplicity. Route search finds ranked routes between two datasets. The connecting-subgraph algorithm uses the same neighbour listing and directed-edge filter. The public methods are configurations of this traversal. |
| 2.3.2 | An expanded dataset lists its directed edges in edge groups, one per logical entity ID in ascending order, each holding the dataset's entity definitions of that logical entity in ascending `dataset_columns` order. An entity definition lists the directed edges leaving it in ascending (`to.node_id`, `to_dataset_columns`) order, up to `limit`, and reports `edge_count`, the number of its directed edges the expansion's filter keeps, and `truncated`. There is no paging. An entity definition that is the only one of its logical entity has no directed edges and no entry. |
| 2.3.3 | `graph.get_edges` takes `node_id`, `limit` (default 200 per entity definition, maximum 1000), optional `identity_id` and `from_dataset_columns`, and `response_format`. It is bounded expansion from that dataset at depth 1, and every target of a listed directed edge appears at distance 1 as a boundary dataset. `identity_id` keeps only the directed edges leaving that logical entity's definitions on the dataset, and `from_dataset_columns`, which requires `identity_id`, keeps only one definition's; a filter that matches no entity definition on the dataset is rejected as invalid params. `truncated` reports whether any entity definition's list was cut. |
| 2.3.4 | `graph.expand_subgraph` takes dataset seeds, `max_depth` (default 1, maximum 10), `max_nodes` (default 1000, maximum 10,000), and `limit` (default 200 per entity definition, maximum 1000). Datasets are reached breadth-first and ordered by (distance, `node_id`). A dataset at a distance below `max_depth` is expanded and lists its edge groups (2.3.2); a dataset at `max_depth` is a boundary dataset and lists none. `max_nodes` caps datasets in that order, `limit` caps each entity definition's list, and directed edges whose target is omitted are not listed. `truncated` reports whether either cap omitted anything. Every dataset in a navigation response reports `edge_count`, the number of directed edges leaving it in the graph, whether or not they are listed, so an agent sees how much lies beyond the response. |
| 2.3.5 | `graph.get_identity` returns the logical entity's `entity_definitions` ordered by `node_id`, then `dataset_columns`, with their datasets in `datasets`, under the same limit and `truncated` rule as `graph.get_edges`. An optional `entity_universe` filter applies before the limit. |
| 2.3.6 | `graph.find_paths` takes two datasets, a maximum route length `max_edges` (default 4), a route limit k (default 6), and optional `allowed_multiplicities`, which removes directed edges whose outgoing multiplicity is not allowed. It returns `path_count` and up to k routes in rank order in `routes`, each an ordered list of directed-edge arrays (2.4.1). A route's stops are (dataset, entity definition) pairs: it may revisit a dataset through a different definition, never reuses a definition, and never takes two directed edges in a row on one key; a change of definition on one dataset shows through a directed edge's start and end columns. |
| 2.3.7 | Ranked-path search finds the k shortest simple routes with Yen's algorithm, with every directed edge costing 1 and ties broken by each route's sequence of `edge_id` and starting definition. It searches a graph that holds each entity definition twice, arrived by a directed edge and ready to leave: a pivot links an arrived copy to the ready copies of its dataset's other definitions at no cost, and each stored relationship links the ready copy of one endpoint to the arrived copy of the other. It searches for k + 1 routes, and `truncated` reports whether the extra one exists. Each shortest search is linear in the stored relationships, so cost grows with k, not with how many routes exist. |
| 2.3.8 | `graph.get_relationship` takes an `edge_id` and optionally the endpoint to read it from, as `from_node_id` and `from_dataset_columns`. `from_dataset_columns` is required when both endpoints lie on `from_node_id`. It always returns canonical `endpoint_a`, `endpoint_b`, `a_to_b`, and `b_to_a`, with the endpoint datasets and entity definitions alongside. With an endpoint, it also returns the directed edge leaving that endpoint as one array in `edge`, at `standard` positions named by `edge_fields`; without one, both are null. The directed edge is a view and never changes the stored relationship. |
| 2.3.9 | `graph.find_connecting_subgraph` takes the selected datasets in `node_ids`. It returns `status` (`completed` or `disconnected`) and the tree's datasets in tree order, each listing, in edge groups (2.3.2), the directed edges of the tree's relationships that leave it. A disconnected response returns the selected datasets with no directed edges. |

### Graph-object responses

| ID | Clause |
| --- | --- |
| 2.4.1 | Every navigation response and `graph.get_relationship` write a directed edge as one array without field names, and one `edge_fields` header per response names its positions. Position `edge` is `"<start node_id>[<columns>] -> <end node_id>[<columns>]"`, the two entity definitions, with columns comma-separated in `dataset_columns` order; a column name containing `,`, `[`, `]`, `"`, or `->` is written as a JSON string, as in `bank.t["a,b"]`. Then come `multiplicity` and `match_existence`; from `standard` detail, `reverse_multiplicity`, `reverse_match_existence`, `from_description`, and `to_description`, the effective descriptions of both endpoints or null; at `full`, `annotation`; and `edge_id` last. Positions follow that order, so a detail level or an added field only inserts positions before `edge_id`. The claims always leave the start, so a directed edge needs no direction field, and an unknown claim reads `unknown` in its position. Inside an edge group, the logical entity ID is the group's `identity_id`. The end dataset's `qualified_name` is in `datasets`. |
| 2.4.2 | An edge group is `{identity_id, entity_definitions}`, and each entry of `entity_definitions` is `{dataset_columns, edge_count, truncated, edges}`. In `"records"` format, each expanded dataset record nests its edge groups under `edge_groups`, so a dataset's adjacency reads in one record, and navigation responses carry no separate relationship list. A relationship whose endpoints are both returned appears as one directed edge in each endpoint's dataset. In both formats, edge groups and directed-edge arrays are the same, and the formats differ only in dataset fields. `graph.find_paths` `routes` is a list in rank order, each route its directed-edge arrays in travel order; the datasets the routes pass through are listed once each in `datasets`, at the requested detail and with `edge_count`, and nest no directed edges because the routes hold them. |
| 2.4.3 | In `"table"` format, each collection renders as `{"header": [...], "rows": [[...]]}`, where a dotted column name is a path into the record. Edge groups form one top-level `edge_groups` list, each group with `node_id` first, in the order of the datasets they belong to; its contents are as in records. Datasets, entity definitions, and columns form their own tables keyed by `node_id`. Any other `response_format` value is rejected as invalid params. |
| 2.4.4 | Responses identify datasets by `node_id` and `qualified_name`. `display_name` is reserved for a presentation mode for people and is not part of navigation, search, `graph.get_identity`, or `graph.get_relationship` responses; `graph.get_dataset` returns the full descriptor, including it. |
| 2.4.5 | `graph.get_relationship` returns the canonical relationship record with `edge_id`, `identity_id`, `endpoint_a.node_id`, `endpoint_a.dataset_columns`, `endpoint_b.node_id`, `endpoint_b.dataset_columns`, `a_to_b.multiplicity`, `a_to_b.match_existence`, `b_to_a.multiplicity`, `b_to_a.match_existence`, `unknown_fields`, and `annotation`. |
| 2.4.6 | Navigation methods accept `detail`: `essential`, `standard` (the default), or `full`. `essential`, for initial exploration, gives datasets `node_id`, `qualified_name`, `accessor.schema_id`, `distance`, and `edge_count`, and directed edges `edge`, `multiplicity`, `match_existence`, and `edge_id`. `standard` adds dataset `grain`, `descriptor.description`, and `unknown_fields`, and the `standard` directed-edge positions of 2.4.1. `full`, for validation, adds `descriptor.synonyms`, `descriptor.tags`, `accessor.properties`, the dataset's `columns` and `entity_definitions`, and each directed edge's `annotation`. |
| 2.4.7 | Navigation methods accept `fields`, a map from `dataset`, `edge`, or `entity_definition` to field names added to the chosen level. An unknown object or field name is rejected as invalid params. Basic fields are always present and cannot be removed: a dataset's `node_id` and `qualified_name`, and a directed edge's `edge` and `edge_id`. Every navigation response echoes the `detail` and `fields` it applied, and `edge_fields`. The `query-graph-api` skill publishes the field catalog and which level suits which task. |
| 2.4.8 | Detail levels never change result bounds. Each method has one default per bound: `graph.get_edges` `limit` 200 per entity definition; `graph.expand_subgraph` `max_nodes` 1000 and `limit` 200 per entity definition; `graph.find_paths` route limit 6 and `max_edges` 4. An explicit bound overrides the default within the method's maximum. |
| 2.4.9 | The `entity_definitions` collection, at `full` detail or when requested, has `node_id`, `identity_id`, `dataset_columns`, `entity_universe`, `unique`, `total`, `conforms`, `entity_expression`, `entity_metadata`, `description`, `effective_description`, `description_source`, and `unknown_fields`. `effective_description` is the definition's own `description` (`description_source` `entity`), else the description of its single column when every `entity_expression` is that bare or bracket-, quote-, or backtick-wrapped column (`column`), else null; it serves `product/graph-model.md#1.9`. A definition with an empty `entity_expression` identifies its logical entity by the combination of its `dataset_columns` (`product/graph-model.md#1.6`). The `columns` collection has `node_id`, `name`, `description`, `value_description`, and `synonyms`. |

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
| 2.6.1 | The public AKG contract is the JSON Schema `resources/schema/akg.schema.json` with the format reference bundled in the `query-graph-api` skill. One JSON document holds one objective: `format_version` (2), `status` (`draft` or `final`), `question`, an optional `objective` and graph snapshot, `datasets` keyed by `node_id`, and optional `comparisons` and `gaps` keyed by agent-chosen IDs. Datasets carry the trimmed graph fields `name`, `source`, and optionally `grain`, `columns`, `description`, `entity_definitions`, `synonyms`, `tags`, and `stats`. The AKG records adjacency as navigation responses do (`product/graph-api-skill.md#3.8`): a selected join is one directed edge in `edges` of the dataset traversal starts from, identified by `edge_id` and `from_dataset_columns`, with `identity_id`, `to_node_id`, `to_dataset_columns`, the outgoing and reverse claims, and the effective descriptions of both entity definitions, the `standard` directed-edge fields of 2.4.1 as named fields. Gaps name directed edges as (`node_id`, `edge_id`). Connected components derive from the directed edges. Agent reasoning lives only under each dataset's and directed edge's `usage` (`keep`, `aggregate_before_join`, and `note` on an edge), in `comparisons`, and in `gaps`. Unknown keys are allowed anywhere. The schema is self-contained and is generated from a lenient model. |
| 2.6.2 | `scripts/akg.py` edits an AKG file. It copies graph fields from service responses at a chosen detail level, never writes accessor properties, entity expressions, entity metadata, or unknown-field lists, and never changes a graph field already present: adding is idempotent and only fills in missing graph fields. `add-edge NODE_ID EDGE_ID` fetches the directed edge through `graph.get_relationship` with `from_node_id`, and `from_dataset_columns` when both endpoints lie on that dataset, and also adds its missing end datasets. `migrate` converts a document holding the earlier `relationships` map: each relationship becomes the directed edge leaving its `usage.from` endpoint, else `endpoint_a`, with its claims kept as written and missing fields fetched; other commands refuse such a document. Removal refuses while other elements refer to the target unless cascaded. Agent fields change only through merge-patches to `usage`, `gaps`, and `comparisons`. Every write is atomic and resets `status` to `draft`. Statistics enter as `stats` once the graph serves them. |
| 2.6.3 | `data-ontology-graph-akg check FILE` reports findings by location, rule, and severity (`error`, `warning`, or `info`) and never refuses to load a parseable document; with `--socket PATH` or `--yaml PATH`, it also resolves every dataset and directed edge against the graph service or the YAML intermediary, a directed edge as its relationship read from the dataset that holds it, and reports each mismatch by element and field. A document that still holds a `relationships` map is one error that names `migrate`. `finalize` requires no error, treats dangling references as errors, requires that resolution, and then sets `status` to `final`. `export --format markdown` writes a deterministic, read-only copy for human review. |

## Data

### Intermediary

| ID | Clause |
| --- | --- |
| 3.1.1 | The intermediary uses schema version `"4"`. Source-controlled JSON Schemas under `resources/schema/` govern the directory manifest (`intermediary-directory.schema.json`) and the assembled intermediary (`intermediary.schema.json`). |
| 3.1.2 | A finalized directory has a fixed `directory-manifest.yaml` beside its `yaml/` directory. The manifest names, relative to `yaml/`, exactly one logical-entity file and one or more node files. Relationships are derived, so no file authors them. |
| 3.1.3 | Each collection file declares schema version `"4"` and contains exactly its manifest-owned collection. Node files partition the assembled node list; logical entities are not partitioned. |
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
| 3.4.1 | A snapshot carries its data-contract `version` (`6.0`), a `schema_fingerprint` of the node, logical entity, relationship, and annotation schemas, a UTC `built_at`, and its logical entities (`logical_identities`), nodes, edges, and annotations. |
| 3.4.2 | A snapshot rejects duplicate node, logical-entity, or edge IDs and references to unknown nodes, logical entities, entity definitions, or edges. |
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
| 4.2 | After the schema gate, construction validates node and logical-entity references, canonical column sets, entity-definition uniqueness, the required `unique`, `total`, and `conforms` properties, the descriptor, the accessor subtype, the grain or explicit unknown grain, the column inventory, and definition-scoped `entity_universe`. It then derives one relationship for every two entity definitions of the same logical entity, with multiplicity and match existence computed from their properties (`product/graph-model.md#3.2`, `#3.3`), stores one record per relationship under its stable edge identity, and writes the snapshot. The build report lists unknown derived claims beside the unknown definition properties they follow from. |
| 4.3 | Publication builds and reload-validates a complete candidate, replaces the current-artifact directory as one unit, restores the prior artifact if promotion fails, and removes its transient backup after success. |
| 4.4 | After a publication, the maintainer reloads the in-memory service against the stable artifact path. |
| 4.5 | The lifecycle command resolves the artifact path, verifies the artifact exists and loads, writes the `launchd` property list into the service home at `setup`, and at `start`, `stop`, and `reload` invokes only the `launchctl` operation the job's loaded state requires, then calls `graph.snapshot_info` to verify the running service. It never searches for a newest artifact, compares versions or timestamps, follows a `latest` pointer, or validates a release manifest. |
| 4.6 | The intended agent interaction is progressive: discover candidate entities, inspect selected entities, and retrieve relationship evidence through lookup or navigation. |
| 4.7 | Connecting-subgraph search uses a polynomial-time undirected Steiner-tree approximation based on Mehlhorn's multi-source approach. Connectivity treats relationships as traversable in either direction, while responses keep both directional claims. |
| 4.8 | Preparation runs in stages: initialize a temporary workspace and inspect the target schema; parse static resources with source locations; inspect the deployed source with bundled read-only queries; draft the manifest and collection YAML; inquire through the survey; iterate on optional answers, defaults, and validation; and finalize. |
| 4.9 | `extract` checks every catalog file against the hashes in Critic's `resources/data/SOURCES.md` before reading it. `publish` rechecks source hashes and atomically writes the generated catalog under Critic `resources/data/generated_catalogs/<catalog>/`. |
