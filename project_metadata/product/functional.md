# Product functional requirements

## Actors

| ID | Clause |
| --- | --- |
| 1.1 | The primary user is an AI reasoning agent on the local machine working on a SQL query task in a hybrid data system with both OLTP and OLAP queries. It reads published knowledge through the local tool interface and cannot change that knowledge. |
| 1.3 | A knowledge maintainer, human or external agent, authors and iteratively refines the YAML source of truth, then requests validation, rebuild, and publication in batches. |

## Capabilities

### Knowledge access

| ID | Clause |
| --- | --- |
| 2.1.1 | An agent can discover graph objects and relationships relevant to a query task and assemble a task-specific AKG from coordinated responses. Candidate selection, semantic relevance, path selection, and AKG content remain the agent's responsibility. Object discovery and lookup are specified in product/object-search.md §1, Object discovery and lookup; navigation is specified in product/graph-navigation.md §1, Graph navigation. |
| 2.1.14 | Graph references supplied by an agent, including references obtained from external tools, must resolve in the served snapshot. |

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

### AKG resolution

| ID | Clause |
| --- | --- |
| 2.4.1 | An agent can follow the `query-graph-api` skill bundled with this project to build an AKG for one objective in a local file, using graph responses to select datasets and relationships, and can finalize it after checking every element against the graph service or the YAML intermediary it was built from. |

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

## Exclusions

### Scope

| ID | Clause |
| --- | --- |
| 4.1.1 | The product does not generate, validate, or execute queries: no SQL, join predicates, recommended join types, dialect translation, natural-language query generation, or choice of a single path or physical replica for execution. |
| 4.1.3 | The graph service reads no source data. |
| 4.1.5 | The local service is read-only and sessionless: it accepts no knowledge changes, validation, rebuild, or publication requests, retains no client state, and takes no caller-held intermediate results as input. |
| 4.1.7 | The builder accepts only complete project-schema YAML. It reads no external definition formats, applies no overlays or override precedence, infers no relationships from database keys, and does not assess or repair the business meaning of schema-valid knowledge. |
| 4.1.12 | The product does not score agent-assembled AKGs or measure the tools' effect on downstream GenAI or SQL-query accuracy. |

### Reserved for a future release

| ID | Clause |
| --- | --- |
| 4.2.1 | Reserved for a later release: source change subscription that queues batch refreshes, usage statistics, human approval of collected knowledge, serving data statistics, an online knowledge store, retrieval instrumentation that never alters response semantics, and caller-supplied intermediate results pinned to a snapshot. |
