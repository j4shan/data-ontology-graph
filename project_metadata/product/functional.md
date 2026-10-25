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
| 2.1.2 | An agent can obtain relationship links between registered physical representations of a logical entity, with enough relationship knowledge to distinguish plausible links when more than one exists. |
| 2.1.3 | An agent can assemble an AKG from multiple coordinated responses. No tool is required to emit a complete AKG in one response. |
| 2.1.4 | An agent can search logical entities, datasets, entity definitions, and columns with deterministic local lexical search, optionally limited to chosen kinds. Each result reports every matching field value and its match type: `exact` or `prefix`, plus `phrase` and `all_words` for multi-word queries against dataset qualified and display names and logical-entity names. |
| 2.1.5 | Search reduces irrelevant context. It does not decide which candidate is correct or select AKG content; the reasoning agent does. |
| 2.1.6 | A description or value description whose whole normalized value is a placeholder, such as `null`, `N/A`, `unknown`, `undefined`, `missing`, or `TBD`, contributes no search terms and is still returned unchanged in detail. Text that merely contains such a word is indexed normally, and names, synonyms, and tags are never filtered. |
| 2.1.7 | An agent can look up a logical entity with every dataset that realizes it, and a dataset with its descriptor, accessor, relevant columns, grain, and entity definitions with their metadata and universe status. |
| 2.1.8 | An agent can list a dataset's relationships as the directed edges leaving it, and look up one relationship, optionally oriented from one of its endpoints while keeping the canonical evidence. Listing a dataset's edges is neighbourhood exploration at depth 1 (2.1.9). |
| 2.1.9 | An agent can explore the neighbourhood of one or more named datasets to a chosen depth. Every dataset closer than that depth presents all directed edges leaving it; datasets at the depth present only how many directed edges they have. |
| 2.1.10 | An agent can retrieve ranked paths between two named datasets. Paths rank by their number of directed edges, then canonical edge IDs. The service does not pick a single winner; semantic analysis and path selection stay with the caller. |
| 2.1.11 | A ranked-path request may restrict each directed edge's multiplicity in the traversal direction. Omitting the filter leaves traversal unrestricted, and unknown multiplicity satisfies a restrictive filter only when explicitly allowed. |
| 2.1.12 | Given 2 to 16 distinct caller-selected datasets, with the maximum configurable server-side, an agent can obtain one compact connecting subgraph that includes intermediate datasets where needed. The result is approximate, not a guaranteed minimum or an enumeration of alternatives. Endpoint selection and semantic relevance stay with the caller. |
| 2.1.13 | Every search and navigation request enforces configurable functional bounds that are part of its response semantics: result-item counts, breadth-first depth, path length in directed edges, and for connecting subgraphs the input-dataset count. |
| 2.1.14 | Any external graph reference an agent supplies, such as an ID obtained from a separate enterprise search tool, must resolve in the served snapshot. |
| 2.1.15 | Every navigation answer presents relationships as directed edges ([graph-model.md](graph-model.md) clause 3.8), and a dataset's directed edges are presented with that dataset, so an agent reads a dataset's adjacency in one place. A dataset's directed edges are grouped by logical entity, then by entity definition, and result bounds apply to each entity definition, so every join column of the dataset stays visible. |
| 2.1.16 | Navigation responses offer three preset detail levels: identifying metadata for initial exploration, up to full metadata for analysis and validation. Detail levels never change result bounds. |
| 2.1.17 | A caller may add named fields to a detail level. A fixed set of identifying fields is always present: a dataset's node ID and qualified name, and a directed edge's edge ID, target dataset, logical entity ID, and columns. The bundled skill documents the available fields and which level suits which task. |
| 2.1.18 | Responses identify datasets by qualified name, with the node ID as the unique key. Display names are reserved for presentation to people. |

### Knowledge maintenance

| ID | Clause |
| --- | --- |
| 2.2.1 | A maintainer can submit batch changes to the YAML source files, such as logical entities, datasets and their entity definitions, the YAML schema, or annotations, and can request validation, rebuild, and publication. The graph builder uses the YAML source files to discover relationships between logical entities and to track their physical presence on dataset nodes. |
| 2.2.2 | Every build consumes one complete YAML intermediary from a configurable operating-system path: either one assembled file or one finalized directory whose sibling manifest inventories its collection files. |
| 2.2.3 | Schema and contract validation gates ingestion. A manifest, collection file, or assembled intermediary that violates its source-controlled contract is rejected with findings that name the invalid location and rule, before graph construction begins. |
| 2.2.5 | Deterministic rule violations, including incompatible references and duplicate definitions, are reported and never auto-resolved. |
| 2.2.6 | A rebuild produces a complete snapshot candidate and a build report of definition validation failures, unresolved dataset or logical entity references, incompatible entity definitions, total relationships, and every typed claim whose value is `unknown`, each located by stable IDs. |
| 2.2.7 | Publication accepts only a candidate that passes rule-based validation and replaces the one current graph artifact as a complete unit. |
| 2.2.8 | A runtime relationship changes only after a referenced entity definition changes and the graph is rebuilt. |
| 2.2.9 | A maintainer can install, start, reload, check the status of, and uninstall the local graph service against the current artifact's stable path. |

### Knowledge preparation

| ID | Clause |
| --- | --- |
| 2.3.1 | A collector user can turn curated evidence about one supported data-source family, plus optional user input, into complete project-schema YAML. Static definitions are evidence, not an authoritative description of business meaning. |
| 2.3.2 | Preparation never asserts business meaning without static (`S`), profiling (`D`), or user (`H`) evidence. Without it, preparation uses the schema's explicit `unknown` value or omits an optional field. |
| 2.3.3 | Preparation keeps traceability from source evidence, direct data inspection, and optional user input to every decision used to produce the finalized YAML. |
| 2.3.4 | Preparation distinguishes observed evidence from the agent's interpretation or proposal. |
| 2.3.5 | Static constraints may generate candidates and questions, but never by themselves establish logical entities, dataset grain, relationships, or population completeness. |
| 2.3.6 | An unanswered decision resolves to the collector's proposal when `S` or `D` evidence supports it, and otherwise to the schema's explicit `unknown` value when available. Shared columns or a declared key alone do not support a claim of a logical entity. |
| 2.3.7 | An unsupported optional candidate or field is omitted. A required field with neither a supported value nor a valid unknown representation blocks publication. |
| 2.3.8 | Collected statistics are preparation evidence. Preparation adds no raw statistics or undeclared properties to the finalized YAML unless the target schema defines a field for them. |
| 2.3.9 | A node's column inventory includes every physical source column by default. A column is omitted only through a recorded decision, and every YAML column must exist in the deployed dataset. |
| 2.3.10 | An optional field is populated only when evidence supports it; the literal text `unknown` is never a substitute unless the schema permits it. A required field that supports an explicit `unknown` value uses it rather than an unsupported answer. |
| 2.3.11 | Preparation records the deployed dataset's fully qualified name, not the path of a DDL resource or test fixture. |
| 2.3.12 | Preparation describes each entity definition's records from evidence, such as uniqueness statistics and coverage queries for null or unmatched keys, treating statistics as evidence, not proof. It does not infer `entity_universe` completeness from uniqueness alone. |
| 2.3.13 | Preparation proposes a condition, state, or composite logical entity when two or more datasets record facts against the same key columns and documentation or column descriptions show that the business compares or reconciles records at that key. |
| 2.3.14 | Shared dimension columns alone never establish an entity or a relationship. A candidate with only shared-column evidence that the user leaves unanswered is not registered, and that outcome is recorded as `defaulted`. |
| 2.3.15 | A registered composite candidate has one logical entity and one entity definition per dataset over the composite column set, with `entity_universe` set to `partial` when supported and `unknown` otherwise. |
| 2.3.17 | Preparation produces a readable, fillable Markdown survey that the user may answer without editing YAML. Answering is optional. |
| 2.3.18 | Survey questions are grouped by dataset and decision topic, deduplicated, and ordered so that answers about logical entities and grain inform later entity definition questions. |
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

The graph model (business and logical entities, datasets, relationships, and typed claims) is specified in
[graph-model.md](graph-model.md); clauses 3.1.x–3.3.x and 3.4.1 moved there.

### Knowledge lifecycle

| ID | Clause |
| --- | --- |
| 3.4.2 | The YAML intermediary is the source-independent knowledge source of truth: complete dataset and logical-entity definitions, not patches over another catalog. |
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
| 4.1.3 | The graph service reads no source data and provides no semantic-similarity or general full-text search beyond word matching of multi-word queries against dataset and logical-entity names. |
| 4.1.5 | The local service is read-only and sessionless: it accepts no knowledge changes, validation, rebuild, or publication requests, retains no client state, and takes no caller-held intermediate results as input. |
| 4.1.7 | The builder accepts only complete project-schema YAML. It reads no external definition formats, applies no overlays or override precedence, infers no relationships from database keys, and does not assess or repair the business meaning of schema-valid knowledge. |
| 4.1.12 | The product does not score agent-assembled AKGs or measure the tools' effect on downstream GenAI or SQL-query accuracy. |

### Reserved for a future release

| ID | Clause |
| --- | --- |
| 4.2.1 | Reserved for a later release: source change subscription that queues batch refreshes, usage statistics, human approval of collected knowledge, serving data statistics, an online knowledge store, retrieval instrumentation that never alters response semantics, and caller-supplied intermediate results pinned to a snapshot. |
