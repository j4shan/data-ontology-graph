# Project Working State: Data Ontology Graph

This document tracks the current implementation and open decisions relative to the [project PRD](../product/backend/project-prd.md). It records working state, not product requirements.

Last reconciled with the repository: **2026-10-03**.

## 1. Current repository baseline and product gaps

The repository implements the governed YAML-directory-to-current-artifact path, safe artifact
replacement, the sessionless local read service, user-owned daemon lifecycle commands, and
functional request bounds. The next planned work is the two agent skills in PRD 5.1.6 and 5.1.8.

| Area | Current baseline | Gap against the PRD |
| --- | --- | --- |
| Knowledge model | Intermediary schema version 3 and snapshot version 5.0 persist the global logical identity registry; dataset descriptors; schema-identified accessors with provider-specific JSON properties; a required grain that is either a compound grain object or the explicit value `unknown`; relevant columns; entity definitions with definition-scoped `entity_universe` (`complete`, `partial`, or `unknown`); compound edge endpoint references; directional multiplicity; and match existence. The canonical model contains no SQL-key, replica, or relationship-inference fields. | Statistics integration is intentionally deferred. A second source environment has not demonstrated that the model is source-independent in practice. |
| Unknown knowledge | Typed claims (`grain`, `entity_universe`, `multiplicity`, `match_existence`) state unknown through their own `unknown` value. Descriptive text is free text and may hold placeholders such as `unknown` or `N/A`. The build report and read responses list unknown claims as `unknown_fields`. | None for the initial release. |
| Definition source | A source-controlled JSON Schema, valid and invalid examples, and a blocking Pydantic/YAML validator govern the complete intermediary. The [financial unit-test fixture](../../tests/fixtures/financial/catalog.yaml) covers eight datasets, 55 physical columns, eight identities, and eight relationships. [YAML Preparation Conventions](../product_spec/yaml-preparation.md) record node-ID, column-inventory, accessor, and decision-log conventions for upstream authoring. | Agent skill A (PRD 5.1.6), which helps a human expert transform SQLite and other definitions into finalized project-schema YAML, is unimplemented. A second storage environment has not been modeled. |
| Builder input boundary | `build_snapshot_from_yaml` accepts a finalized `yaml/` directory governed by a sibling `directory-manifest.yaml` ([manifest schema](../../resources/schema/intermediary-directory.schema.json)). The manifest lists one identities file, one or more node files, and one edges file relative to `yaml/`; each file must hold schema version `"3"` and only its owned collection. The builder rejects missing manifests, unlisted, missing, unsupported, or escaping files, ownership and schema-version conflicts, and duplicate definitions, then assembles one deterministic definition and maps only the rule-valid result into the graph model. Single-file input remains supported. | No initial-release builder-input gap remains. |
| Relationship construction | The builder resolves explicit endpoints to registered entity definitions and creates exactly the authored edges. The local read service exposes relationship detail, directed hops, bounded BFS subgraphs, and bounded ranked paths. | Larger-corpus behavior remains optional Tier 1 validation. |
| Agent access | One sessionless service loads the current artifact, builds a MARISA exact-and-prefix search index plus graph lookup and adjacency indexes, and serves typed request/response methods through JSON-RPC 2.0 over a protected Unix-domain socket. A description whose whole value is a placeholder, such as `null`, `N/A`, or `TBD`, contributes no search terms. Search, BFS, and path responses expose configurable functional bounds. The Python `launchd` command manages the user-owned daemon. | Agent skill B (PRD 5.1.8), a local MCP server or plugin that wraps these tools with AKG-assembly guidance, is unimplemented. |
| Publication | `CurrentArtifactStore` builds and reload-validates a complete candidate, safely replaces one current-artifact directory at a caller-supplied path outside this repository, restores the prior artifact if promotion fails, and removes its transient backup after success. Cross-file envelopes must agree. | No initial-release publication gap remains. The application does not manage prior releases or manifests. |
| Downstream accuracy evaluation | The read tools return evidence fragments that a reasoning agent may use when assembling an AKG or SQL-query plan. | Out of scope. The sibling [Critic](../../../critic/) project owns the AKG submission schema, gold AKGs, scoring, test data sources, reference catalogs, and published artifacts. |
| Ingestion quality | Validation blocks graph construction on YAML syntax, schema, registry, canonical dataset-column ordering, endpoint resolution, identity alignment, grain resolution, duplicate definitions, duplicate edges, unsupported directory files, and cross-file conflicts, with rule and location findings. The committed JSON Schema is checked against the validator model. | Semantic validation belongs to agent skill A. |

The [product specifications](../product_spec/) describe the target contracts. The [project description](../project_description/project-description.md) records the retired legacy inference model for historical context only.

The baseline above was checked against the [dataset model](../../src/data_ontology_graph/model/dataset.py), [claims model](../../src/data_ontology_graph/model/claims.py), [snapshot model](../../src/data_ontology_graph/model/snapshot.py), [build report](../../src/data_ontology_graph/builder/report.py), [graph read service](../../src/data_ontology_graph/service/read.py), [lexical index](../../src/data_ontology_graph/service/search.py), and [JSON-RPC socket server](../../src/data_ontology_graph/rpc/server.py).

## 2. Open product decisions

**Settled initial-release direction**

1. Each builder invocation consumes one finalized source-independent YAML directory from a configurable operating-system path and maps it into the internal graph representation. Project-schema YAML is its only accepted input format. Producing that YAML from tenant DDLs or other source formats is a separate preparation stage outside the initial release.
2. A global logical identity registry locates a business identity's dataset-column set across nodes and systems. Relationships are established through registered identity matching, not logical column-name matching.
3. A node can hold an `entity_definition` with an unrestricted `entity_expression`. The expression is an agent-facing label; the builder preserves it without parsing or executing it.
4. `expression_context` belongs to entity metadata. The canonical edge does not duplicate connected definition metadata.
5. A node entity definition is identified by `(node_id, identity_id, canonical dataset_columns)`; a separate `entity_definition_id` is unnecessary. More than one redundant expression may share that key.
6. An edge references two node entity definitions and carries relationship properties. An assembled AKG includes the connected node metadata in context proximity.
7. YAML node and edge definitions and their machine-readable schema are source-controlled. Schema validation is a blocking ingestion gate before graph construction.
8. Metadata may be provisioned by translating original DDL, resolving original DDL plus human or agent feedback, or direct human or agent authoring. Every mode produces one complete YAML artifact.
9. Overrides and overlays are not part of the target builder. Corrections are absorbed into the external preparation step before schema-gated ingestion.
10. One OS-managed background graph service serves production and development through JSON-RPC 2.0 request/response calls over a Unix-domain socket restricted to the local user. Every request carries an `id`; notifications are not supported. The service loads the current published artifact and keeps its search and navigation indexes resident.
11. Graph-service requests are sessionless. The service does not retain conversation, task, candidate-selection, partial-AKG, or traversal state between requests; disposable caches cannot affect response semantics.
12. Initial graph search uses a static `marisa-trie` `RecordTrie` of mechanically normalized terms and posting references. It supports exact and prefix-descendant lookup, followed by straightforward filtering, deduplication, stable ordering, and result limiting. Dedicated relevance-ranking, semantic-similarity, and generalized full-text search are outside the graph service.
13. Search exposes candidates to reduce irrelevant context; the reasoning agent chooses AKG content. An orchestrating agent may use separate enterprise entity, terminology, semantic, or full-text search tools before graph search, but every supplied graph reference must resolve in the pinned snapshot.
14. The initial local tool scope is search, identity and dataset lookup, relationship detail, directed hops, breadth-first subgraph expansion, and path retrieval. Responses are evidence fragments and do not generate or validate SQL.
15. The publisher maintains one current generated graph artifact at a caller-supplied path outside this repository. Successful publication replaces it as a complete unit; failed publication leaves it unchanged. The application does not retain prior releases, and initial-release publisher verification is limited to unit tests.
16. A dataset node uses dataset terminology and contains one descriptor plus a generic accessor envelope. The accessor `schema_id` dispatches provider-specific validation of its JSON properties. An accessor is a recipe for an external reader and never carries credentials.
17. `entity_universe` (`complete`, `partial`, or `unknown`) is required on each entity definition because a dataset may contain multiple identities with different population coverage.
18. A dataset node has exactly one required `grain`: a grain object whose components collectively describe one record boundary, or the explicit value `unknown`.
19. Unknown is a typed claim value only. Descriptive text is free text, is not validated for meaning, and carries no unknown state of its own. The model records knowledge, not how or why it was obtained.
20. This repository stores source code, the YAML schema, and unit-test fixtures. Test data sources, reviewed reference catalogs, published artifacts, and evaluation results live in Critic.

**Open initial-release decisions**

1. `JoinAnnotation` records (`description`, `tags`) remain an optional snapshot sidecar, but the YAML intermediary cannot author them and the PRD does not specify them. Specify an authoring path, or remove them. They no longer affect path ranking.

**Future-release decisions**

7. Which data statistics are necessary for query reasoning, and what variance is tolerable for each type?
8. Which source CRUD events should be subscribed to, and how should they feed the batch update process without mutating published offline copies?
9. When would an optional online knowledge store add value beyond local offline access?
10. What parsers, question-and-answer workflow, and workbook format should agent skill A provide so a human expert can resolve ambiguous metadata or record it as unknown? May the skill read data rows for evidence (aggregate profiling versus value samples), given that [YAML Preparation Conventions](../product_spec/yaml-preparation.md) 3.1 says the project does not read data?
11. Should agent skill B ship as a local MCP server or a plugin, and what AKG output form should it target before Critic publishes its submission schema (Critic C0.1)?
12. Which response-size, tracing, and task-level measurements would be useful if lower-priority retrieval instrumentation is implemented?

## 3. Financial catalog study

The BIRD Mini-Dev `financial` catalog was the study subject for the gaps below: eight datasets and 55 physical columns. Critic has removed that catalog from the assessment corpus because it is too small for ontology assessment. This repository still keeps the [financial unit-test fixture](../../tests/fixtures/financial/catalog.yaml) for builder tests. The observations below were taken from the SQLite database and description files when those sources were available.

| Observation | Example and implication |
| --- | --- |
| Description quality varies | Eighteen of 55 `column_name` labels and seven `column_description` values are blank. `account.csv` has an extra unnamed CSV field containing the `frequency` code meanings. Preparation needs field validation and preservation of raw notes, not a silent best-effort parse. |
| Value semantics matter | `loan.csv` explains `status` codes; `trans.csv` explains transaction types, operations, and payment symbols. Dates, currencies, and units also appear in free text. `loan.payments` is labeled "monthly payments" but has a value note saying "unit: month," which needs review before normalization. |
| Documentation contradicts data | `account.date` is documented as `YYMMDD`, but the SQLite data holds ISO dates such as `1995-03-24`. The `account_to` value note ("each bank has unique two-letter code") belongs to `bank_to`. Only 2 of 6,446 distinct `order.account_to` values match `account.account_id`, so the column likely identifies an external account rather than `account_identity`. These are the ambiguities skill A must surface to a human expert. |
| Declared constraints are not enforced | SQLite reports `PRAGMA foreign_keys = 0`, so a declared foreign key plus `NOT NULL` does not prove `always` match existence. The fixture records match existence from the referencing side as `unknown`. |
| Relationship paths carry different context | The authored YAML declares eight explicit relationships, including client–account connections through `disp` and both client–district and account–district relationships. An agent can reach `district` directly from `client` or through `disp` and `account`; the routes remain distinguishable in an AKG. |
| Coverage is mostly unassessed | Fifteen of 16 entity definitions have `entity_universe: unknown`; only the district definition is `complete`. The build report lists 23 unknown claims: 15 universe claims and 8 match-existence claims. |
| Statistics are absent | The description files document column meanings and some value codes but no row counts, distinct counts, null rates, distributions, or relationship fan-out measures. These would require a separate source and representation. |

## 4. Data modeling adoption audit

This audit compares the current node and edge design with the independent [Data Modeling Spec](../product/data/data-modeling-spec.md).

| Relevant concept | Current node or edge design | Initial-release gap |
| --- | --- | --- |
| Dataset description and access | Every node has a descriptor with a qualified dataset name and a generic accessor whose schema ID dispatches provider-specific JSON validation. `accessor.sqlite.v1` records `host`, absolute `database_path`, `schema`, and `object`. | Additional accessor schemas can be added without changing `DatasetNode`. |
| Dataset grain | Every node has a required grain: a grain object whose components collectively describe one record boundary, or the explicit value `unknown`. The value `unknown` persists in the snapshot and is reported in `unknown_fields`. | None. |
| Entity population coverage | `entity_universe` is scoped to each entity definition and may be `complete`, `partial`, or `unknown`. | Coverage remains authored knowledge; the builder does not infer it. |
| Logical identity and node entity definition | The runtime has a global logical identity registry and node entity definitions keyed by `(node_id, identity_id, dataset_columns)`, with multiple opaque expressions and adjacent metadata. Exact, alias, and prefix search plus identity lookup expose every registered definition. | Retrieval behavior still needs evaluation beyond the financial reference scale. |
| Relationship endpoint identity | Endpoints use compound entity-definition references. Canonical edge identity derives from the unordered endpoint pair, and read responses resolve references to connected definition and dataset context without changing the persisted edge. | None. |
| Edge multiplicity and existence | Edges persist directional `1:1`, `1:many`, `many:1`, `many:many`, or `unknown` multiplicity and `always`, `optional`, or `unknown` match existence. Hops and paths report unknown claims relative to the traversal direction. | Larger-corpus traversal behavior remains to be evaluated. |
| Agent-visible properties | Search, identity and dataset lookup, relationship detail, directed hops, breadth-first subgraphs, and ranked paths expose descriptors, accessors, grain, identity definitions, dataset-column sets, expressions, metadata, universe status, relationship properties, and `unknown_fields`. | Byte accounting remains lower-priority instrumentation. |

The current [intermediary model](../../src/data_ontology_graph/model/intermediary.py), [dataset model](../../src/data_ontology_graph/model/dataset.py), [relationship model](../../src/data_ontology_graph/model/relationship.py), and [explicit builder](../../src/data_ontology_graph/builder/__init__.py) support this audit. The target boundary does not require all Kimball techniques listed in the legacy [project description](../project_description/project-description.md).

## 5. Delivery priorities by tier

These priorities translate the [project PRD](../product/backend/project-prd.md), the data-modeling boundary, and the financial study into delivery order. Tier 0 establishes accurate entity and relationship knowledge, a local offline read surface, controlled batch publication, and functional request bounds. Tier 1 records local validation coverage that is not itself a PRD commitment. Tier 2 contains reserved roadmap capabilities; the PRD names agent skills A and B as the next planned work within it. Collection quality takes precedence over collection speed and refresh frequency in every tier.

### Tier 0 — accurate financial knowledge and local offline use

| ID | Proposed feature | Financial evidence and value | Observable outcome |
| --- | --- | --- | --- |
| T0.1 | Author a financial YAML catalog from the SQLite schema, database-description CSVs, and reviewed domain knowledge. Preserve labels, descriptions, data formats, raw value notes, logical identities, dataset-column sets, entity expressions, and relationship properties. Automated source-to-YAML migration remains out of scope. | All 55 description rows align with SQLite columns, while `account.csv` contains an extra field and `loan.payments` has ambiguous unit text. The catalog provides a concrete target without making the builder source-aware. | A validated financial YAML definition covers the eight datasets and all 55 physical columns. The unit-test fixture lives here; the reviewed reference catalog lives in Critic. |
| T0.2 | Represent addressable datasets independently of storage-specific table concepts through a descriptor, schema-identified accessor, required grain or explicit unknown, and node-scoped entity definitions. | A node may identify a database object, S3 prefix, or another dataset form. | Financial reference tasks distinguish dataset identity and access properties without expanding the canonical graph into a source catalog. |
| T0.3 | Provide one OS-managed, sessionless local graph service with lexical search, detail, directed-hop, breadth-first subgraph, relationship, and path tools over an offline snapshot. Serve JSON-RPC 2.0 over a local-user Unix-domain socket, use a static MARISA trie for exact and prefix candidate discovery, and keep the read surface separate from collection and publication. | The local service keeps one snapshot plus its indexes resident; the `launchd` lifecycle command installs and reloads it against the current-artifact path. | A local agent can discover candidates and inspect or navigate the financial graph through the singleton socket interface while offline; calls cannot mutate the copy or create server-side reasoning sessions. |
| T0.4 | Establish a batch publication workflow that rule-validates the finalized YAML, builds a complete snapshot candidate, and safely replaces the one current artifact at a caller-supplied path. Semantic validation remains upstream of the builder and publisher. | Consumers such as Critic need a reproducible current artifact without application-managed release history. | A successful build replaces the complete current artifact; a failed build leaves it unchanged; unit tests cover the publisher contract. |
| T0.6 | Persist and serve one generic accessor envelope for each dataset. Preserve provider-specific access properties as validated JSON chosen by `schema_id`; connectors remain outside this feature. | Different accessors require different property combinations without widening the universal node model. | Dataset detail exposes the accessor schema ID and comprehensible provider properties without opening a data connection. |
| T0.7 | Expose edge multiplicity and per-endpoint always/optional/unknown existence with explicit unknowns. | Join preservation and relationship cardinality are directional properties and are authored explicitly rather than inferred from source keys. | Financial relationships can be inspected in both directions with supported 1:many and existence properties; unsupported claims remain unknown. |
| T0.8 | Implement the source-controlled YAML node and edge model and global logical identity registry around node-scoped `entity_definition` records. Resolve explicit edge endpoints to registered definitions and gate ingestion with the source-controlled schema. | A business identity can appear through `[c1, c2, c3]`, the label `[c1, xxhash64(c2, c3)]`, and `[d1, d2]`. Column labels alone cannot express this equivalence. | Schema-invalid YAML is rejected before ingestion. The builder creates only explicitly defined YAML edges whose endpoints resolve to registered node entity definitions. |
| T0.9 | Enforce configurable functional bounds on search and graph navigation. | Search, BFS, and paths need result, depth, and hop limits. | Each operation's returned results respect its configured item, depth, and hop bounds. |

### Tier 1 — local validation backlog

| ID | Proposed feature | Financial evidence and value | Observable outcome |
| --- | --- | --- | --- |
| T1.1 | Exercise another source format or vendor through the same YAML intermediary, runtime model, and local tool contract. | Financial currently exercises one SQLite-origin catalog. | Local validation confirms that another catalog builds and is served without source-specific builder behavior. This is validation coverage, not a separate product requirement. |
| T1.2 | Shift local tests to a large metadata pool and observe discovery and traversal behavior. | Financial's eight datasets cannot expose high-volume path or result-limit defects. | The larger local fixture exercises configured functional bounds and identifies implementation defects. It is not a PRD release benchmark. |

### Tier 2 — future roadmap

| ID | Proposed feature | Financial evidence and value | Observable outcome |
| --- | --- | --- | --- |
| T2.1 | Subscribe to CRUD events on all connected data sources as change signals for a batch update of the knowledge source of truth. Keep validation and offline-copy publication as separate release steps. | Financial demonstrates a schema and description pair that can change independently. | Source events can queue a batch refresh, while a published offline copy remains unchanged until a separately validated version is deployed. |
| T2.2 | Optionally add an online knowledge store as another serving mode. Preserve the local offline tool contract and immutable-copy workflow. | The initial local-agent use case has no network boundary. | An online mode, if adopted, serves the same entity and relationship meaning without becoming a dependency of offline agents. |
| T2.3 | Integrate data statistics into persistence and tools, then define validation tolerance by statistic type. | The financial descriptions contain semantic notes but no measured statistics. | Tools can return measured statistics, and their data quality can be validated independently of downstream GenAI accuracy. |
| T2.4 | Agent skill A (PRD 5.1.6): parse SQLite and other external definitions, detect ambiguous decisions, and run a question-and-answer loop through a readable, fillable workbook so a human expert fills gaps or records them as unknown. Keep the skill separate from graph construction. | The financial study shows contradictions, cryptic names, and unenforced constraints that only a domain expert can resolve. Manual authoring does not scale to thousands of entities. | An expert-guided run produces a finalized YAML directory plus a decision log outside it; the directory passes the builder's rule-based validation. Critic C0.9 scores the result against its reference catalog. |
| T2.5 | Add optional retrieval instrumentation for response bytes, tool-call traces, task-level context totals, result volume, and traversal work. | Functional limits can be enforced without monitoring or benchmarking infrastructure. | Optional measurements describe service behavior without changing response semantics or becoming an initial-release gate. |
| T2.6 | Agent skill B (PRD 5.1.8): package the sessionless graph tools as a local MCP server or plugin with instructions that guide an agent through search, lookup, and navigation to output a task-specific AKG. | The graph service is reachable only through JSON-RPC over a Unix socket; agents lack AKG-assembly guidance. | An agent completes a financial task through the packaged tools and emits an AKG in Critic's submission schema without server-side reasoning state. |

Usage-frequency collection and human approval remain reserved goals outside these priorities. Tier 2 event subscription does not imply real-time mutation of offline copies.

## 6. Deferred and accepted limitations

Keep the following boundaries available for later design work:

1. Accessor subtype schemas are registered in source code. Adding a new accessor kind requires adding its schema ID and property validator before the builder accepts it.
2. More than one `entity_expression` may be attached to the same `(node_id, identity_id, dataset_columns)` key. The initial release does not verify that those labels agree on identity semantics; incompatible expressions must be represented under distinguishable definitions or corrected during authoring.
3. The builder preserves unrestricted entity-expression text without parsing, executing, translating, or proving it. The query agent interprets the label using entity metadata and accessor context.
4. Descriptive text cannot be machine-identified as unknown. The search index skips only descriptions whose whole normalized value matches its placeholder list; other wording with the same meaning is indexed.

## 7. Code-ready TODOs

The initial-release Tier 0 implementation is complete. Tier 1 records local validation gaps rather
than product requirements; Tier 2 remains reserved roadmap work, led by agent skills A and B.
Performance work and AKG benchmarking are excluded.

### Completed

| ID | Result |
| --- | --- |
| W0.3 | Source-controlled schema, canonical validation, validation findings, examples, and blocking ingestion gate implemented. |
| W0.4 | Financial YAML implemented with eight datasets, 55 described columns, eight identities, and eight relationships. |
| W0.5 | The snapshot persists the registry, dataset descriptors, schema-identified accessor properties, grain, entity definitions with universe status, endpoint references, and directional relationship properties; round-trip coverage is in place. |
| W0.6 | The builder maps one validated complete YAML artifact into the internal graph model and creates only explicit edges; SQL catalog ingestion, inference, overlays, key decomposition, and replica resolution have been removed. |
| W0.7 | A singleton sessionless service provides MARISA exact-and-prefix search, target-model lookup, directed hops, BFS subgraphs, and ranked paths through JSON-RPC 2.0 request/response calls over a protected Unix-domain socket. The HTTP surface was retired; a development client and `launchd` generator use the same interface. |
| W0.8 | Finalized YAML directories are assembled deterministically; unsupported files, conflicting schema versions, duplicate identities or nodes, and invalid combined definitions block construction with findings. |
| W0.10 | The publication contract is recorded in [Current Graph Artifact Publication](../product_spec/artifact-publication.md): one current artifact at a caller-supplied path, rule-based validation, safe whole-artifact replacement, no application-managed release history, and unit-test-only verification. |
| W0.11 | The current-artifact publisher builds and validates a candidate before safe whole-directory replacement, restores the previous current artifact after promotion failure, rejects mixed cross-file envelopes, and retains no prior release. |
| W0.12 | The Python `data-ontology-graph-launchd` command generates configuration and constructs install, start, reload, status, and uninstall `launchctl` operations against one artifact path. |
| W0.13 | Search, BFS, and path contracts enforce configurable response-semantic bounds. BFS limits returned nodes and edges and reports truncation; path calls enforce hop and result limits. |
| W0.14 | The canonical dataset model uses descriptor and accessor objects, keeps provider-specific access properties behind schema-dispatched JSON validation, scopes universe status to entity definitions, and omits SQL catalog primitives. |
| W0.15 | Intermediary schema 3 and snapshot 5.0: `entity_universe` is `complete`, `partial`, or `unknown`; grain is required as an object or explicit `unknown`; the build report and read responses list unknown claims as `unknown_fields`. Field provenance and ambiguity records were removed; descriptive text is free text. |
| W0.16 | The search index skips descriptions whose whole normalized value is a placeholder such as `null`, `N/A`, `unknown`, `undefined`, `missing`, or `TBD`. Names, synonyms, and tags are never filtered. |
| W0.17 | `accessor.sqlite.v1` records `host`, absolute `database_path`, `schema`, and `object`; the intermediary schema defines node-ID composition, and [YAML Preparation Skill Product Requirements](../product_spec/yaml-preparation.md) define full column inventory and decision-log placement. |
| W0.18 | Test data sources, the reviewed reference catalog, and legacy overlays moved to Critic. The financial unit-test fixture lives under `tests/fixtures/financial/`, and published artifacts live outside the repository. |
| W0.20 | `JoinAnnotation` no longer carries `weight` or `notes`. Paths rank by hop count, then canonical edge IDs. |
| W0.21 | PRD 3.3.13 now matches the Data Modeling Spec and code: exactly one `grain`, either a grain object or explicit `unknown`, with omission invalid and `unknown` persisted. |
| W0.22 | Directory input requires a sibling `directory-manifest.yaml` that owns the collection-file inventory: one identities file, one or more node files, and one edges file, each holding only its collection. The manifest has a checked-in JSON Schema, and tests cover path, ownership, inventory, and schema-version rejections. |
| W0.23 | [YAML Preparation Skill Product Requirements](../product_spec/yaml-preparation.md) define skill A's goals, packaging, evidence classes, field-preparation matrix, survey and decision-log lifecycle, bundled tools, workflow, and acceptance criteria. |

### Remaining

| ID | Tier | Category | TODO | Depends on | Observable completion |
| --- | --- | --- | --- | --- | --- |
| W0.19 | 0 | Documentation | Resolve open initial-release decision 1 (`JoinAnnotation` authoring). | — | The PRD, specs, and code agree on whether annotations exist and how they are authored. |
| W1.1 | 1 | Local coverage validation | Exercise a second catalog from another storage or access environment through the same YAML contract. | W0.11 | Unit tests confirm both catalogs build, reload, and are served without source-specific builder or read-service behavior. This is validation coverage, not a PRD deliverable. |
| W1.2 | 1 | Large-pool validation | Shift local tests to a large metadata pool and exercise search and traversal limits. | W0.13 | Local tests expose high-volume result and path behavior without creating a PRD benchmark or release score. |
| W1.3 | 1 | Retrieval refinement | Change search or navigation only where large-pool local validation demonstrates a concrete functional failure. | W1.2 | Each refinement is tied to a reproducible failing case and preserves the tool contract. |
| W2.1 | 2 | Preparation (skill A) | Build the SQLite-to-YAML agent skill: extraction and optional profiling scripts, ambiguity detection, a fillable question-and-answer workbook in a temporary workspace, answer parsing and follow-up rounds, YAML emission, and a decision log outside the YAML directory. | Future decision 10 | An expert-guided `financial` run produces YAML that passes builder validation, and Critic C0.9 can score it. |
| W2.8 | 2 | AKG guidance (skill B) | Package the graph tools as a local MCP server or plugin with AKG-assembly instructions. | Future decision 11; Critic C0.1 | An agent completes a financial task through the packaged tools and emits an AKG in Critic's submission schema. |
| W2.2 | 2 | Refresh | Subscribe to source CRUD events as signals for later batch rebuilding. | Initial-release publication stabilized | Events queue source-of-truth refresh work without mutating published offline copies. |
| W2.3 | 2 | Statistics | Add data statistics to persistence and tools, with tolerance-aware validation of the statistics themselves. | Statistics contract defined | Statistical variance is validated independently of downstream GenAI accuracy. |
| W2.4 | 2 | Serving | Evaluate and, if justified, add an online store using the same logical contract. | Initial local access stabilized | Online serving does not become a dependency of offline agents. |
| W2.5 | 2 | Usage measurement | Collect read frequency for logical identities and relationships. | Initial local access stabilized | Usage metrics can be analyzed without being confused with source data statistics. |
| W2.6 | 2 | Authorization | Let human subject-matter experts approve agent-collected knowledge assets. | Skill A available | Approval state can participate in later publication policy. |
| W2.7 | 2 | Retrieval instrumentation | Optionally add response-byte counts, tool-call traces, task-level context totals, result-volume measurements, and traversal-work measurements. | Functional bounds stabilized | Instrumentation supports monitoring or service-level benchmarking without changing graph response semantics or benchmarking downstream GenAI accuracy. |
