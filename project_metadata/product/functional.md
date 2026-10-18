# Product functional requirements

## Actors

| ID | Clause |
| --- | --- |
| 1.1 | The primary user is an AI reasoning agent on the local machine working on a SQL query task in a hybrid data system with both OLTP and OLAP queries. It reads published knowledge through the local tool interface and cannot change that knowledge. |
| 1.2 | The collector user is the one human who runs the preparation tools for a data-source family. They may answer decisions, override proposals, or add business information, but need not answer any decision. No separate confirmer is required. |
| 1.3 | A knowledge maintainer, human or external agent, authors and iteratively refines the YAML source of truth, then requests validation, rebuild, and publication in batches. |

## Capabilities

### Knowledge access

| ID | Clause |
| --- | --- |
| 2.1.1 | An agent can obtain the entities relevant to a query task and include them in a task-specific AKG. |
| 2.1.2 | An agent can obtain relationship links between registered physical representations of a logical identity, with enough relationship knowledge to distinguish plausible links when more than one exists. |
| 2.1.3 | An agent can assemble an AKG from multiple coordinated responses. No tool is required to emit a complete AKG in one response. |
| 2.1.4 | An agent can search logical identities, datasets, entity definitions, and columns with deterministic local lexical search, optionally limited to chosen kinds. Each result reports every matching field value and its match type: `exact` or `prefix`, plus `phrase` and `all_words` for multi-word queries against dataset qualified and display names and logical-identity names. |
| 2.1.5 | Search reduces irrelevant context. It does not decide which candidate is correct or select AKG content; the reasoning agent does. |
| 2.1.6 | A description or value description whose whole normalized value is a placeholder, such as `null`, `N/A`, `unknown`, `undefined`, `missing`, or `TBD`, contributes no search terms and is still returned unchanged in detail. Text that merely contains such a word is indexed normally, and names, synonyms, and tags are never filtered. |
| 2.1.7 | An agent can look up a logical identity with every dataset that realizes it, and a dataset with its descriptor, accessor, relevant columns, grain, and entity definitions with their metadata and universe status. |
| 2.1.8 | An agent can list the directed relationship hops from a dataset, and look up one relationship, optionally oriented from one of its endpoints while keeping the canonical evidence. |
| 2.1.9 | An agent can expand a breadth-first subgraph from one or more named dataset seeds. The returned subgraph is reasoning evidence, not a completed AKG. |
| 2.1.10 | An agent can retrieve ranked paths between two named datasets. Paths rank by hop count, then canonical edge IDs. The service does not pick a single winner; semantic analysis and path selection stay with the caller. |
| 2.1.11 | A ranked-path request may restrict each hop's multiplicity in the traversal direction. Omitting the filter leaves traversal unrestricted, and unknown multiplicity satisfies a restrictive filter only when explicitly allowed. |
| 2.1.12 | Given 2 to 16 distinct caller-selected datasets, with the maximum configurable server-side, an agent can obtain one compact connecting subgraph that includes intermediate datasets where needed. The result is approximate, not a guaranteed minimum or an enumeration of alternatives. Endpoint selection and semantic relevance stay with the caller. |
| 2.1.13 | Every search and navigation request enforces configurable functional bounds that are part of its response semantics: result-item counts, breadth-first depth, path hop count, and for connecting subgraphs the input-dataset count. |
| 2.1.14 | Any external graph reference an agent supplies, such as an ID obtained from a separate enterprise search tool, must resolve in the served snapshot. |

### Knowledge maintenance

| ID | Clause |
| --- | --- |
| 2.2.1 | A maintainer can submit batch changes to complete YAML node and edge definitions, logical identities, entity definitions, relationship properties, the YAML schema, or annotations, and can request validation, rebuild, and publication. |
| 2.2.2 | Every build consumes one complete YAML intermediary from a configurable operating-system path: either one assembled file or one finalized directory whose sibling manifest inventories its collection files. |
| 2.2.3 | Schema and contract validation gates ingestion. A manifest, collection file, or assembled intermediary that violates its source-controlled contract is rejected with findings that name the invalid location and rule, before graph construction begins. |
| 2.2.4 | The builder creates a relationship only from an explicit YAML edge whose endpoints resolve to registered entity definitions of the same logical identity. Column-name equality, foreign-key declarations, and composite-key decomposition never define a relationship. |
| 2.2.5 | Deterministic rule violations, including incompatible references and duplicate definitions, are reported and never auto-resolved. |
| 2.2.6 | A rebuild produces a complete snapshot candidate and a build report of definition validation failures, unresolved dataset or identity references, incompatible entity definitions, total relationships, and every typed claim whose value is `unknown`, each located by stable IDs. |
| 2.2.7 | Publication accepts only a candidate that passes rule-based validation and replaces the one current graph artifact as a complete unit. |
| 2.2.8 | A runtime relationship changes only after its YAML edge definition or a referenced entity definition changes and the graph is rebuilt. |
| 2.2.9 | A maintainer can install, start, reload, check the status of, and uninstall the local graph service against the current artifact's stable path. |

### Knowledge preparation

| ID | Clause |
| --- | --- |
| 2.3.1 | A collector user can turn curated evidence about one supported data-source family, plus optional user input, into complete project-schema YAML. Static definitions are evidence, not an authoritative description of business meaning. |
| 2.3.2 | Preparation never asserts business meaning without static (`S`), profiling (`D`), or user (`H`) evidence. Without it, preparation uses the schema's explicit `unknown` value or omits an optional field. |
| 2.3.3 | Preparation keeps traceability from source evidence, direct data inspection, and optional user input to every decision used to produce the finalized YAML. |
| 2.3.4 | Preparation distinguishes observed evidence from the agent's interpretation or proposal. |
| 2.3.5 | Static constraints may generate candidates and questions, but never by themselves establish business identities, dataset grain, relationships, or population completeness. |
| 2.3.6 | An unanswered decision resolves to the collector's proposal when `S` or `D` evidence supports it, and otherwise to the schema's explicit `unknown` value when available. Shared columns or a declared key alone do not support a claim of business identity. |
| 2.3.7 | An unsupported optional candidate or field is omitted. A required field with neither a supported value nor a valid unknown representation blocks publication. |
| 2.3.8 | Collected statistics are preparation evidence. Preparation adds no raw statistics or undeclared properties to the finalized YAML unless the target schema defines a field for them. |
| 2.3.9 | A node's column inventory includes every physical source column by default. A column is omitted only through a recorded decision, and every YAML column must exist in the deployed dataset. |
| 2.3.10 | An optional field is populated only when evidence supports it; the literal text `unknown` is never a substitute unless the schema permits it. A required field that supports an explicit `unknown` value uses it rather than an unsupported answer. |
| 2.3.11 | Preparation records the deployed dataset's fully qualified name, not the path of a DDL resource or test fixture. |
| 2.3.12 | Preparation does not infer `entity_universe` completeness from uniqueness alone. It sets multiplicity using uniqueness statistics as evidence, not proof, and sets match existence from coverage queries that test for unmatched records. |
| 2.3.13 | Preparation proposes a condition, state, or composite logical identity when two or more datasets record facts against the same identity columns and documentation or column descriptions show that the business compares or reconciles records at that key. |
| 2.3.14 | Shared dimension columns alone never establish an entity or a relationship. A candidate with only shared-column evidence that the user leaves unanswered is not registered, and that outcome is recorded as `defaulted`. |
| 2.3.15 | A registered composite candidate has one logical identity and one entity definition per dataset over the composite column set, with `entity_universe` set to `partial` when supported and `unknown` otherwise. |
| 2.3.16 | Preparation connects entity definitions that record facts against the same registered identity with an ordinary relationship, setting its directional claims from `D` or `H` evidence or to their explicit `unknown` values. |
| 2.3.17 | Preparation produces a readable, fillable Markdown survey that the user may answer without editing YAML. Answering is optional. |
| 2.3.18 | Survey questions are grouped by dataset and decision topic, deduplicated, and ordered so that answers about identities and grain inform later relationship questions. |
| 2.3.19 | Every survey question carries a stable decision ID, the affected YAML path or object, whether the value is required or optional, the question, the available evidence, the proposal or candidate choices when useful, a fillable answer area, an explicit unknown choice, and a rationale or reference area. |
| 2.3.20 | Preparation recognizes ambiguity from conflicting sources, missing business meaning, incompatible statistics, or multiple plausible mappings, and presents a question with an evidence-backed proposal when possible. |
| 2.3.21 | After each optional response round, preparation applies answers and overrides, defaults unanswered decisions, regenerates still-relevant questions, and validates the updated YAML. |
| 2.3.22 | The survey never asks the user to restate facts already established by the target schema or direct source inspection, unless evidence conflicts. |
| 2.3.23 | The decision log records each decision's stable ID, question, resolution, status, affected YAML path or object, evidence references, rationale, and waiver where applicable. A defaulted decision keeps its supporting evidence or explains why the result is unknown or omitted. |
| 2.3.24 | Decision statuses distinguish at least open, answered, defaulted, unknown, waived, and blocking. `defaulted` marks a resolution reached without a user answer. |
| 2.3.25 | Publication of a generated catalog does not wait for user answers. It stops for a required field with no supported value and no valid unknown representation, a decision the user marks blocking, a validation failure, or a draft finding. |
| 2.3.26 | A catalog is final when its manifest, collection files, and assembled intermediary validate, every required field has a valid value, omissions are documented, and no blocking condition remains. |

### AKG resolution

| ID | Clause |
| --- | --- |
| 2.4.1 | An agent can follow the `query-graph-api` skill bundled with this project to build an AKG for one objective incrementally in a local file, adding and removing graph datasets and relationships through bundled tools during a session, and can finalize it after checking every element against the graph service or the YAML intermediary it was built from. |

## Concepts

### Entities and identities

| ID | Clause |
| --- | --- |
| 3.1.1 | A business entity is a concept the business identifies and reasons about with a stable identity. It may be a physical object, party, event, agreement, or a condition or state that matters to the domain at a point in time, such as a planning slot: one item planned at one plant on one calendar day. |
| 3.1.2 | A logical identity names one business identity independently of any physical representation. A global registry gives each a stable `identity_id`, a business name, and an optional description and confirmed synonyms. |
| 3.1.3 | An entity definition is one physical realization of a logical identity in one dataset, identified by `(node_id, identity_id, dataset_columns)` with no separate ID. `dataset_columns` is the complete set of node-local physical columns the definition uses. |
| 3.1.4 | An entity definition may carry one or more unrestricted `entity_expression` labels for the same realization. They are agent-facing text, preserved without parsing, executing, translating, or proving them. |
| 3.1.5 | Entity metadata beside an entity definition holds the context needed to interpret it, including its expression context. |
| 3.1.6 | `entity_universe` belongs to an entity definition and states whether that realization covers the complete entity population (`complete`), part of it (`partial`), or is unassessed (`unknown`). One dataset may hold definitions with different universe status. |
| 3.1.7 | A business entity does not need a dataset holding its complete population. When none does, every definition of that identity may be `partial` or `unknown`. |
| 3.1.8 | An entity definition may use a composite column set whose columns also realize other identities on the same dataset; a column may belong to more than one entity definition. |
| 3.1.9 | A condition, state, or composite logical identity is registered only when the business identifies, compares, reconciles, or tracks records at that key. |

### Datasets

| ID | Clause |
| --- | --- |
| 3.2.1 | A dataset is an addressable data resource, not assumed to be a SQL table or tabular storage. Distinct datasets in different access locations never collapse because their display names match. |
| 3.2.2 | A dataset's descriptor holds its fully qualified deployed name, display name, description, synonyms, and tags in dataset terminology. Source-specific terms such as table, catalog, schema, or prefix belong only to the accessor. |
| 3.2.3 | A dataset's accessor is a credential-free recipe an external tool uses to locate the dataset: a provider `schema_id` and the provider-specific properties it validates. The common model prescribes no vendor-specific properties. |
| 3.2.4 | A dataset has exactly one grain: a grain whose components together describe one record boundary, or the explicit value `unknown`. Different record boundaries are different datasets. |
| 3.2.5 | A dataset records its physical columns for identity, grain, search, and relationship context. The graph does not reproduce primary keys, foreign keys, unique constraints, nullability, SQL types, or other source-catalog primitives. |

### Relationships

| ID | Clause |
| --- | --- |
| 3.3.1 | A relationship connects two different registered entity definitions of the same logical identity. One stored relationship represents both directions; a traversal gives it a direction. |
| 3.3.2 | Multiplicity is a directional claim: `1:1`, `1:many`, `many:1`, `many:many`, or `unknown`. From endpoint A to B, uniqueness on both sides gives `1:1`, nonunique A and unique B gives `many:1`, unique A and nonunique B gives `1:many`, and nonunique on both gives `many:many`; unestablished uniqueness gives `unknown`. |
| 3.3.3 | Match existence is a directional claim for each endpoint: `always` means every record there has a match on the other side, `optional` means zero matches are permitted without asserting that an unmatched record was observed, and `unknown` means neither is established. |
| 3.3.4 | Multiplicity and match existence are independent authored claims. A `many:1` link can still be optional from the many side. |
| 3.3.5 | When two datasets record different facts against the same registered identity, their entity definitions connect through an ordinary relationship. Its multiplicity may be `many:many` when both datasets hold several records per key. |
| 3.3.6 | Entity-universe status is reusable context about one entity definition; directional match existence is the relationship-specific evidence for whether an inner join preserves records from that direction. |
| 3.3.7 | An annotation is descriptive sidecar metadata on one relationship: a description and tags. It never creates, approves, rejects, or alters the relationship's structural claims. |

### Knowledge lifecycle

| ID | Clause |
| --- | --- |
| 3.4.1 | Unknown is a typed claim value. `grain`, `entity_universe`, `multiplicity`, and `match_existence` state unknown through their own `unknown` value. Descriptive text is free text that may hold any wording and never establishes or negates a typed claim. |
| 3.4.2 | The YAML intermediary is the source-independent knowledge source of truth: complete dataset, relationship, and logical-identity definitions, not patches over another catalog. |
| 3.4.3 | The intermediary may come from original DDL, from DDL plus human or agent feedback, or from direct human or agent authoring. Every mode produces one complete intermediary. |
| 3.4.4 | The current graph artifact is the one published offline copy agents read. Changes reach it only through a validated batch rebuild and whole-artifact publication, never by mutation in place. |

### Abstract knowledge graph

| ID | Clause |
| --- | --- |
| 3.5.1 | An abstract knowledge graph (AKG) is the subset of graph datasets and relationships that a question-answering agent selects for one objective through incremental evidence discovery; no single tool response is itself an AKG. Its three pillars are datasets, relationships, and statistics. Every element is referenced by its canonical graph identifier and carries a trimmed copy of the graph properties the objective needs, with its claims and explicit unknowns unchanged, so an agent can fetch further properties and navigate related objects from it. Relationships are selected explicitly rather than implied by their datasets. |
| 3.5.3 | One AKG holds everything that serves one objective, and its connected components are derived from its selected relationships. Disconnected components are a valid answer: the objective may need disjoint facts, or the data model may lack the connection, in which case the AKG identifies an outstanding data gap. The agent never invents a connection to join components. A question with materially different readings has one objective, and one AKG, per reading. |
| 3.5.5 | Query reasoning, such as anchors, column usage, traversal direction, preserved populations, aggregation choices, comparisons, and identified data gaps, is recorded as annotations on the elements it concerns or as document-level gaps and comparisons. It is distinguishable from graph properties, never changes one, and never adds a dataset or relationship. |

### Preparation evidence

| ID | Clause |
| --- | --- |
| 3.6.1 | Preparation evidence has four classes: static resources (`S`: DDL, schema dumps, comments, constraints), optional user input (`H`: answers, overrides, supplementary business information), direct data inspection (`D`: statistics from bundled read-only queries), and schema rules (`R`: values fixed or constrained by the intermediary schema). |

## Exclusions

### Scope

| ID | Clause |
| --- | --- |
| 4.1.1 | The product does not generate, validate, or execute queries: no SQL, join predicates, recommended join types, dialect translation, natural-language query generation, or choice of a single path or physical replica for execution. |
| 4.1.3 | The graph service reads no source data and provides no semantic-similarity or general full-text search beyond word matching of multi-word queries against dataset and logical-identity names. |
| 4.1.5 | The local service is read-only and sessionless: it accepts no knowledge changes, validation, rebuild, or publication requests, retains no client state, and takes no caller-held intermediate results as input. |
| 4.1.7 | The builder accepts only complete project-schema YAML. It reads no external definition formats, applies no overlays or override precedence, infers no relationships from database keys, and does not assess or repair the business meaning of schema-valid knowledge. |
| 4.1.12 | The product does not score agent-assembled AKGs or measure the tools' effect on downstream GenAI or SQL-query accuracy. |

### Reserved for a future release

| ID | Clause |
| --- | --- |
| 4.2.1 | Reserved for a later release: source change subscription that queues batch refreshes, usage statistics, human approval of collected knowledge, serving data statistics, an online knowledge store, retrieval instrumentation that never alters response semantics, and caller-supplied intermediate results pinned to a snapshot. |
