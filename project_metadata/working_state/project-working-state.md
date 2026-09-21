# Project Working State: Data Ontology Graph

This document tracks the current implementation and open decisions relative to the [project PRD](../product/backend/project-prd.md). It records working state, not product requirements.

Last reconciled with the repository: **2026-09-24**.

## 1. Current repository baseline and product gaps

The repository now implements the governed YAML-directory-to-current-artifact path, safe artifact
replacement, the sessionless local read service, user-owned daemon lifecycle commands, and
functional request bounds. Cross-environment validation and future preparation tooling remain.

| Area | Current baseline | Gap against the PRD |
| --- | --- | --- |
| Knowledge model | Snapshot version 4 persists the global logical identity registry; dataset descriptors; schema-identified accessors with provider-specific JSON properties; one optional compound grain; relevant columns; entity definitions with definition-scoped universe status; compound edge endpoint references; directional multiplicity; and match existence. The canonical model contains no SQL-key, replica, or relationship-inference fields. | Statistics integration is intentionally deferred. A second source environment has not demonstrated that the model is source-independent in practice. |
| Definition source | A source-controlled JSON Schema, valid and invalid examples, and a blocking Pydantic/YAML validator govern the complete intermediary. The financial reference YAML covers eight datasets and 55 described physical columns. | Upstream preparation tooling that helps a human or external agent transform DDLs and other definitions into finalized project-schema YAML remains unimplemented. A second storage environment has not been modeled. |
| Builder input boundary | `build_snapshot_from_yaml` accepts a finalized YAML directory, discovers `.yaml` and `.yml` files recursively in deterministic order, assembles one coherent definition, rejects unsupported files and duplicate or conflicting definitions, and maps only the rule-valid result into the graph model. Single-file input remains for compatibility. | No initial-release builder-input gap remains. |
| Relationship construction | `build_snapshot_from_yaml` accepts only rule-valid complete YAML, resolves explicit endpoints to registered entity definitions, and creates exactly the authored edges. SQL catalog ingestion, overlay enrichment, key decomposition, replica resolution, and automatic edge inference have been removed. The local read service exposes relationship detail, directed hops, bounded BFS subgraphs, and bounded ranked paths. | Larger-corpus behavior remains optional Tier 1 validation. |
| Agent access | One sessionless service loads the current artifact, builds a MARISA exact-and-prefix search index plus graph lookup and adjacency indexes, and serves typed request/response methods through JSON-RPC 2.0 over a protected Unix-domain socket. Search, BFS, and path responses expose configurable functional bounds. The Python `launchd` command generates the property list and constructs install, start, reload, status, and uninstall operations for the user-owned daemon. | No initial-release local-access gap remains. |
| Publication | `CurrentArtifactStore` builds and reload-validates a complete candidate, safely replaces one stable current-artifact directory, restores the prior current artifact if promotion fails, and removes its transient backup after success. Cross-file envelopes must agree. | No initial-release publication gap remains. The application does not manage prior releases or manifests. |
| Downstream accuracy evaluation | The read tools return evidence fragments that a reasoning agent may use when assembling an AKG or SQL-query plan. | Defining an AKG evaluation artifact and benchmarking the tools' effect on GenAI or SQL-query accuracy are non-goals of this project and are TBD in a separate project. |
| Ingestion quality | Validation blocks graph construction on YAML syntax, schema, registry, canonical dataset-column ordering, endpoint resolution, identity-alignment, duplicate definitions, duplicate edges, unsupported directory files, and cross-file conflicts, with rule and location findings. The committed JSON Schema is checked against the validator model. | Semantic validation belongs to the future upstream YAML-generator agent skill. |

The [project description](../../project-description.md) records the legacy inference model. The [product specifications](../product_spec/) describe the target contracts; W0.3 through W0.7 implement their YAML, snapshot, search, and local-read foundation.

The baseline above was checked against the [dataset model](../../src/data_ontology_graph/model/dataset.py), [snapshot model](../../src/data_ontology_graph/model/snapshot.py), [graph read service](../../src/data_ontology_graph/service/read.py), [lexical index](../../src/data_ontology_graph/service/search.py), and [JSON-RPC socket server](../../src/data_ontology_graph/rpc/server.py).

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
15. The repository contains one current generated graph artifact at a stable path. Successful publication replaces it as a complete unit; failed publication leaves it unchanged. The application does not retain prior releases, and initial-release publisher verification is limited to unit tests.
16. A dataset node uses dataset terminology and contains one descriptor plus a generic accessor envelope. The accessor `schema_id` dispatches provider-specific validation of its JSON properties.
17. `is_entity_universe` is required on each entity definition because a dataset may contain multiple identities with different population coverage.
18. A dataset node has zero or one grain object; its components collectively describe one record boundary.

**Open initial-release decisions**

None currently recorded.

**Future-release decisions**

7. Which data statistics are necessary for query reasoning, and what variance is tolerable for each type?
8. Which source CRUD events should be subscribed to, and how should they feed the batch update process without mutating published offline copies?
9. When would an optional online knowledge store add value beyond local offline access?
10. What parsers, authoring instructions, and workflow should the proposed preparation-skill bundle provide so external agents can iteratively produce accurate finalized YAML directories at scale?
11. Which response-size, tracing, and task-level measurements would be useful if lower-priority retrieval instrumentation is implemented?

## 3. Financial catalog study

The local BIRD Mini-Dev `financial` catalog provides a focused study subject for the gaps above. Its eight [database-description CSV files](../../resources/data/dev_databases/financial/database_description/) describe 55 physical columns. The builder reads only the prepared [financial YAML](../../resources/data/dev_overlays/financial/catalog.yaml), which preserves the reviewed descriptions and value notes without ingesting SQLite or CSV sources itself.

| Observation | Example and implication |
| --- | --- |
| Description quality varies | Eighteen of 55 `column_name` labels and seven `column_description` values are blank. [account.csv](../../resources/data/dev_databases/financial/database_description/account.csv) has an extra unnamed CSV field containing the `frequency` code meanings. Import needs field validation and preservation of raw notes, not a silent best-effort parse. |
| Value semantics matter | [loan.csv](../../resources/data/dev_databases/financial/database_description/loan.csv) explains `status` codes; [trans.csv](../../resources/data/dev_databases/financial/database_description/trans.csv) explains transaction types, operations, and payment symbols. Dates, currencies, and units also appear in free text. `loan.payments` is labeled “monthly payments” but has a value note saying “unit: month,” which needs review before normalization. |
| Relationship paths carry different context | The authored YAML declares eight explicit relationships, including client–account connections through `disp` and both client–district and account–district relationships. An agent can reach `district` directly from `client` or through `disp` and `account`; the routes remain distinguishable in an AKG. |
| Statistics are absent | The description files document column meanings and some value codes but no row counts, distinct counts, null rates, distributions, or relationship fan-out measures. These would require a separate source and representation. |

## 4. Data modeling adoption audit

This audit reverse engineers the current node and edge design against the independent [Data Modeling Spec](../product/data/data-modeling-spec.md). It records what already exists and what the initial release still needs.

| Relevant concept | Current node or edge design | Initial-release gap |
| --- | --- | --- |
| Dataset description and access | Every node has a descriptor with a qualified dataset name and a generic accessor whose schema ID dispatches provider-specific JSON validation. | Additional accessor schemas can be added without changing `DatasetNode`. |
| Dataset grain | Every node has zero or one grain object whose components collectively describe one record boundary. | Additional catalogs need reviewed grain authoring beyond financial. |
| Entity population coverage | `is_entity_universe` is scoped to each entity definition rather than the containing dataset. | Coverage remains authored knowledge; the builder does not infer it. |
| Logical identity and node entity definition | The runtime has a global logical identity registry and node entity definitions keyed by `(node_id, identity_id, dataset_columns)`, with multiple opaque expressions and adjacent metadata. Exact, alias, and prefix search plus identity lookup expose every registered definition. | Retrieval behavior still needs evaluation beyond the financial reference scale. |
| Relationship endpoint identity | Target endpoints use compound entity-definition references. Canonical edge identity derives from the unordered endpoint pair, and read responses resolve references to connected definition and dataset context without changing the persisted edge. | Functional result limits for expanded endpoint context remain W0.13 work. |
| Edge multiplicity and existence | Target edges persist directional `1:1`, `1:many`, `many:1`, `many:many`, or `unknown` multiplicity and `always`, `optional`, or `unknown` match existence. | Larger-corpus traversal behavior remains to be evaluated. |
| Agent-visible properties | Search, identity and dataset lookup, relationship detail, directed hops, breadth-first subgraphs, and ranked paths expose descriptors, accessors, grain, identity definitions, dataset-column sets, expressions, metadata, universe status, and relationship properties. | Byte accounting remains lower-priority instrumentation. |

The current [intermediary model](../../src/data_ontology_graph/model/intermediary.py), [dataset model](../../src/data_ontology_graph/model/dataset.py), [relationship model](../../src/data_ontology_graph/model/relationship.py), and [explicit builder](../../src/data_ontology_graph/builder/__init__.py) support this audit. The target boundary does not require all Kimball techniques listed in the legacy [project description](../../project-description.md).

## 5. Delivery priorities by tier

These priorities translate the [project PRD](../product/backend/project-prd.md), the data-modeling boundary, and the financial study into delivery order. Tier 0 establishes accurate entity and relationship knowledge, a local offline read surface, controlled batch publication, and functional request bounds. Tier 1 records local validation coverage that is not itself a PRD commitment. Tier 2 contains reserved roadmap capabilities. Collection quality takes precedence over collection speed and refresh frequency in every tier.

### Tier 0 — accurate financial knowledge and local offline use

| ID | Proposed feature | Financial evidence and value | Observable outcome |
| --- | --- | --- | --- |
| T0.1 | Author a reference financial YAML catalog from the SQLite schema, database-description CSVs, and reviewed domain knowledge. Preserve labels, descriptions, data formats, raw value notes, logical identities, dataset-column sets, entity expressions, and relationship properties; flag malformed or conflicting inputs for curation. Automated source-to-YAML migration remains out of scope. | All 55 description rows align with SQLite columns, while [account.csv](../../resources/data/dev_databases/financial/database_description/account.csv) contains an extra field and `loan.payments` has ambiguous unit text. The catalog provides a concrete target without making the builder source-aware. | A validated financial YAML definition covers the eight datasets and all 55 physical columns, and a rebuilt snapshot exposes the reviewed knowledge without reading SQLite or CSV inputs directly. |
| T0.2 | Represent addressable datasets independently of storage-specific table concepts through a descriptor, schema-identified accessor, single optional grain, and node-scoped entity definitions. | A node may identify a database object, S3 prefix, or another dataset form. | Financial reference tasks distinguish dataset identity and access properties without expanding the canonical graph into a source catalog. |
| T0.3 | Provide one OS-managed, sessionless local graph service with lexical search, detail, directed-hop, breadth-first subgraph, relationship, and path tools over an offline snapshot. Serve JSON-RPC 2.0 over a local-user Unix-domain socket, use a static MARISA trie for exact and prefix candidate discovery, and keep the read surface separate from collection and publication. | The implemented local service keeps one snapshot plus its indexes resident; the `launchd` lifecycle command installs and reloads it against the stable current-artifact path. | A local agent can discover candidates and inspect or navigate the financial graph through the singleton socket interface while offline; calls cannot mutate the copy or create server-side reasoning sessions. |
| T0.4 | Establish a batch publication workflow that rule-validates the finalized YAML, builds a complete snapshot candidate, and safely replaces the one current source-controlled artifact. Semantic validation remains upstream of the builder and publisher. | The repository needs a reproducible current artifact without application-managed release history. | A successful build replaces the complete current artifact; a failed build leaves it unchanged; unit tests cover the publisher contract. |
| T0.6 | Persist and serve one generic accessor envelope for each dataset. Preserve provider-specific access properties as validated JSON chosen by `schema_id`; connectors remain outside this feature. | Different accessors require different property combinations without widening the universal node model. | Dataset detail exposes the accessor schema ID and comprehensible provider properties without opening a data connection. |
| T0.7 | Expose edge multiplicity and per-endpoint always/optional/unknown existence with evidence-aware unknowns. | Join preservation and relationship cardinality are directional properties and are authored explicitly rather than inferred from source keys. | Financial relationships can be inspected in both directions with supported 1:many and existence properties; unsupported claims remain unknown. |
| T0.8 | Implement the source-controlled YAML node and edge model and global logical identity registry around node-scoped `entity_definition` records. Each definition is identified by `(node_id, identity_id, canonical dataset_columns)`, may carry multiple unrestricted `entity_expression` labels, and keeps `expression_context` in node entity metadata. Resolve explicit edge endpoints to registered definitions and gate ingestion with the source-controlled schema. | A business identity can appear through `[c1, c2, c3]`, the label `[c1, xxhash64(c2, c3)]`, and `[d1, d2]`. Column labels alone cannot express this equivalence, and automatic composite-PK decomposition generates unsupported candidates. | Schema-invalid YAML is rejected before ingestion. The builder creates only explicitly defined YAML edges whose endpoints resolve to registered node entity definitions. Canonical edges store endpoint references plus relationship properties, while identity search locates every dataset-column set and the AKG obtains expressions and context from connected nodes. |
| T0.9 | Enforce configurable functional bounds on search and graph navigation, including response item count, BFS depth and node/edge result count, and path hop and result count. | Search and paths accept result limits and BFS accepts depth, but BFS lacks node and edge result-count limits. | Each operation's returned results respect its configured item, depth, and hop bounds. |

### Tier 1 — local validation backlog

| ID | Proposed feature | Financial evidence and value | Observable outcome |
| --- | --- | --- | --- |
| T1.1 | Exercise another source format or vendor through the same YAML intermediary, runtime model, and local tool contract. | Financial currently exercises one SQLite-origin catalog. | Local validation confirms that another catalog builds and is served without source-specific builder behavior. This is validation coverage, not a separate product requirement. |
| T1.2 | Shift local tests to a large metadata pool and observe discovery and traversal behavior. | Financial's eight datasets cannot expose high-volume path or result-limit defects. | The larger local fixture exercises configured functional bounds and identifies implementation defects. It is not a PRD release benchmark. |

### Tier 2 — future roadmap

| ID | Proposed feature | Financial evidence and value | Observable outcome |
| --- | --- | --- | --- |
| T2.1 | Subscribe to CRUD events on all connected data sources as change signals for a batch update of the knowledge source of truth. Keep validation and offline-copy publication as separate release steps. | Financial demonstrates a schema and description pair that can change independently; event detection could identify what needs recollection without changing an agent's copy. | Source events can queue a batch refresh, while a published financial offline copy remains unchanged until a separately validated version is deployed. |
| T2.2 | Optionally add an online knowledge store as another serving mode. Preserve the local offline tool contract and immutable-copy workflow. | The initial local-agent use case has no network boundary, and the retired HTTP demo did not establish a need for one. | An online mode, if adopted, serves the same entity and relationship meaning without becoming a dependency of offline agents. |
| T2.3 | Integrate data statistics into persistence and tools, then define validation tolerance by statistic type. | The [financial descriptions](../../resources/data/dev_databases/financial/database_description/) contain semantic notes but no measured statistics. | Tools can return measured statistics, and their data quality can be validated independently of downstream GenAI accuracy. |
| T2.4 | Provide an upstream bundle of agent skills, external-definition parsing tools, semantic-validation guidance, and authoring instructions so dataset owners can generate or iteratively refine complete YAML from source material and feedback at scale. Keep this preparation bundle separate from graph construction. | Manual authoring can establish the initial contract and reference catalog but does not scale to thousands of entities and many owners. | Dataset owners can use an external agent to produce a semantically reviewed finalized YAML directory that passes the builder's rule-based validation and publication gate; the graph builder still accepts only project-schema YAML. |
| T2.5 | Add optional retrieval instrumentation for response bytes, tool-call traces, task-level context totals, result volume, and traversal work. | Functional limits can be enforced without monitoring or benchmarking infrastructure. | Optional measurements describe service behavior without changing response semantics or becoming an initial-release gate. |

Usage-frequency collection and human approval remain reserved goals outside these priorities. Tier 2 event subscription does not imply real-time mutation of offline copies.

## 6. Deferred and accepted limitations

Keep the following boundaries available for later design work:

1. Accessor subtype schemas are registered in source code. Adding a new accessor kind requires adding its schema ID and property validator before the builder accepts it.
2. More than one `entity_expression` may be attached to the same `(node_id, identity_id, dataset_columns)` key. The initial release does not verify that those labels agree on identity semantics; incompatible expressions must be represented under distinguishable definitions or corrected during authoring.
3. The builder preserves unrestricted entity-expression text without parsing, executing, translating, or proving it. The query agent interprets the label using entity metadata and accessor context.

## 7. Code-ready TODOs

The initial-release Tier 0 implementation is complete. Tier 1 records local validation gaps rather
than product requirements; Tier 2 remains reserved roadmap work. Performance work and AKG
benchmarking are excluded.

### Completed

| ID | Result |
| --- | --- |
| W0.3 | Source-controlled schema, canonical validation, validation findings, examples, and blocking ingestion gate implemented. |
| W0.4 | Financial reference YAML implemented with eight datasets, 55 described columns, eight identities, and eight relationships. |
| W0.5 | Snapshot v4 persists the registry, dataset descriptors, schema-identified accessor properties, singular optional grain, entity definitions with universe status, endpoint references, and directional relationship properties; round-trip coverage is in place. |
| W0.6 | The builder maps one validated complete YAML artifact into the internal graph model and creates only explicit edges; SQL catalog ingestion, inference, overlays, key decomposition, and replica resolution have been removed. |
| W0.7 | A singleton sessionless service now provides MARISA exact-and-prefix search, target-model lookup, directed hops, BFS subgraphs, and ranked paths through JSON-RPC 2.0 request/response calls over a protected Unix-domain socket. Every request requires an `id`; notifications are not supported. The HTTP surface and its dependencies were retired; a development client and `launchd` generator use the same interface. |
| W0.8 | Finalized YAML directories are discovered and assembled deterministically; unsupported files, conflicting schema versions, duplicate identities or nodes, and invalid combined definitions block construction with findings. |
| W0.10 | The initial-release publication contract is recorded in [Current Graph Artifact Publication](../product_spec/artifact-publication.md): one current source-controlled artifact, rule-based validation, safe whole-artifact replacement, no application-managed release history, and unit-test-only verification. Semantic validation remains upstream. |
| W0.11 | The current-artifact publisher builds and validates a candidate before safe whole-directory replacement, restores the previous current artifact after promotion failure, rejects mixed cross-file envelopes, and retains no prior release. |
| W0.12 | The existing Python `data-ontology-graph-launchd` command now generates configuration and constructs install, start, reload, status, and uninstall `launchctl` operations against one stable artifact path, without release discovery or manifest validation. |
| W0.13 | Search, BFS, and path contracts enforce configurable response-semantic bounds. BFS now limits returned nodes and edges and reports truncation; path calls enforce hop and result limits. |
| W0.14 | The canonical dataset model now uses descriptor and accessor objects, keeps provider-specific access properties behind schema-dispatched JSON validation, scopes `is_entity_universe` to entity definitions, permits zero or one compound grain, and omits SQL catalog primitives. |

### Remaining

| ID | Tier | Category | TODO | Depends on | Observable completion |
| --- | --- | --- | --- | --- | --- |
| W1.1 | 1 | Local coverage validation | Exercise a second catalog from another storage or access environment through the same YAML contract. | W0.11 | Unit tests confirm both catalogs build, reload, and are served without source-specific builder or read-service behavior. This is validation coverage, not a PRD deliverable. |
| W1.2 | 1 | Large-pool validation | Shift local tests to a large metadata pool and exercise search and traversal limits. | W0.13 | Local tests expose high-volume result and path behavior without creating a PRD benchmark or release score. |
| W1.3 | 1 | Retrieval refinement | Change search or navigation only where large-pool local validation demonstrates a concrete functional failure. | W1.2 | Each refinement is tied to a reproducible failing case and preserves the tool contract. |
| W2.1 | 2 | Preparation | Develop the proposed bundle of agent skills, external-definition parsing tools, semantic-validation guidance, and YAML-authoring instructions for DDL-plus-feedback and direct authoring modes. Keep the bundle upstream of the builder. | Initial-release contract stabilized | An external agent can iteratively produce a semantically reviewed finalized project-schema YAML directory; the builder applies the same rule-based validation and publication gate as for manually authored YAML. |
| W2.2 | 2 | Refresh | Subscribe to source CRUD events as signals for later batch rebuilding. | Initial-release publication stabilized | Events queue source-of-truth refresh work without mutating published offline copies. |
| W2.3 | 2 | Statistics | Add data statistics to persistence and tools, with tolerance-aware validation of the statistics themselves. | Statistics contract defined | Statistical variance is validated independently of downstream GenAI accuracy. |
| W2.4 | 2 | Serving | Evaluate and, if justified, add an online store using the same logical contract. | Initial local access stabilized | Online serving does not become a dependency of offline agents. |
| W2.5 | 2 | Usage measurement | Collect read frequency for logical identities and relationships. | Initial local access stabilized | Usage metrics can be analyzed without being confused with source data statistics. |
| W2.6 | 2 | Authorization | Let human subject-matter experts approve agent-collected knowledge assets. | AI-assisted authoring available | Approval state can participate in later publication policy. |
| W2.7 | 2 | Retrieval instrumentation | Optionally add response-byte counts, tool-call traces, task-level context totals, result-volume measurements, and traversal-work measurements. | Functional bounds stabilized | Instrumentation supports monitoring or service-level benchmarking without changing graph response semantics or benchmarking downstream GenAI accuracy. |
