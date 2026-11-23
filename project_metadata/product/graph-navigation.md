# Product requirements: graph navigation

## 1. Graph navigation

An agent can inspect relationships, explore a dataset's neighbourhood, list the entity links
at a logical entity, and find paths between logical entities. Directed edges and their metadata are
defined in product/graph-model.md.

### Capabilities

- Look up a canonical relationship with its endpoint definitions and datasets, optionally
  viewing it from one endpoint while preserving the canonical evidence. When both
  endpoints belong to the same dataset, the caller identifies the source definition
  by its columns.
- Inspect one dataset's outgoing relationships through `get_dataset_edges`. A source filter
  may select a logical entity realized on that dataset or one of its definitions.
  The selected source definitions establish the connected dataset neighbourhood.
  High fan-out is supported discovery behaviour; the agent can inspect its
  distribution and retrieve detailed relationship evidence. The agent explores further by
  inspecting the connected datasets it selects.
- Automatically present detailed results for a small filtered neighbourhood and an
  aggregated view when its distinct connected-dataset count exceeds a configured
  fan-out threshold. The caller can explicitly request either view. The response
  identifies the view returned and echoes the source scope and applied filters.
- In the aggregated view, report the exact total fan-out count and a group-by table
  of the 20 logical entities with the most entity definitions across the complete
  filtered connected-dataset set, or all groups when fewer than 20 exist. Each row
  identifies the logical entity, its entity-definition count, and the number of
  distinct connected datasets containing it. Order rows by descending definition
  count, then ascending logical entity ID, and indicate whether further groups
  were omitted. Compute these values before detailed-result limits or pagination.
- Drill down through `get_dataset_edges` by selecting logical entities that the connected
  datasets must contain. This target filter is separate from the source filter
  establishing the connection; a selected target entity need not occur on the
  source dataset. A multi-value target filter uses AND semantics: a dataset must
  contain at least one definition of every selected logical entity. The caller can
  select any registered logical entity, including one outside the displayed top 20.
- Refine discovery by adding, removing, or replacing target logical entities and
  resubmitting the complete filter list. Every request is self-contained. Apply
  the source and target filters before choosing the response view, counting
  fan-out, and computing the histogram. Subsequent counts and histogram rows
  describe the resulting filtered neighbourhood. An empty selection result has
  zero fan-out and no histogram rows.
- Retrieve bounded detailed results with a continuation mechanism until all matching
  connected datasets and their selected relationships can be inspected, including
  when further logical-entity filtering cannot narrow the result. Continuation
  preserves the snapshot and selection scope. Detailed relationships retain their
  source-definition grouping, endpoint references, and directional evidence.
- Path search is a tool used by AI agents to find connectivity between logical entities.
  It does not judge which existing paths are wanted. It returns the paths of entity links between
  two logical entities that exist within bounds under the caller's filters, returns none
  when no such path exists, and returns no partial solutions. The caller can filter by entity
  link bound, entity link kind, multiplicity and match existence per entity link in the direction of travel
  and their order along the path, avoided logical entities, participating logical entities
  and how they participate, self links inside a path, and restatement of a shorter
  path on the same records. Claim
  filters apply to paths; a subgraph limited to the participating logical entities has no
  single direction of travel, so it takes none. Results present logical entities and their
  entity links with each entity link's claims, and list no datasets. Every response reports how the result
  would change under each claim filter and names each single filter change that would widen
  it, with the resulting count, so the agent can narrow or relax its next request; this holds
  for an empty result and for a non-empty one that may lack the wanted path. A count that the
  search could not complete is reported as a lower bound. Ranking uses
  deterministic metadata only: fewer entity links and fewer added logical entities rank first,
  and entity links with known claims rank before entity links with unknown claims. Equal results are reported
  as ties, not ordered by guesswork.
- List the entity links at a logical entity. Each entity link gives the other logical
  entity, the multiplicity and match existence derived on its common datasets read from
  the requested logical entity, its common dataset count, and the stated cross-entity
  relationship's descriptions and claims when one exists. The caller can restrict the
  list to stated entity links, filter by multiplicity and match existence, and avoid
  logical entities. Include an entity link count and bounded continuation so an agent
  can inspect the full list.
- Offer `essential`, `standard`, and `full` navigation detail levels, with named
  fields that callers may add. Detail selection does not change result bounds.
  Dataset records always identify their node ID and qualified name; directed
  edges identify their canonical edge ID, source and target definitions, and
  logical entity, either directly or through their containing group.
  `get_dataset_edges` results associate adjacency with datasets.
  Path-search and entity-link listing results present logical entities and their entity
  links, without directed edges or datasets, and take no detail level.

### Concepts

Fan-out is the number of distinct connected datasets other than the source dataset.
A dataset reached through several source definitions contributes once to that count
and once to the set used for aggregation. Each distinct entity definition on a
selected connected dataset contributes once to its logical entity's definition
count; multiple definitions of one entity on that dataset count separately. The
source dataset is excluded from these discovery aggregates. Same-dataset
relationships remain available as detailed relationship evidence.

A source logical-entity filter chooses how the source connects to its neighbours.
A target logical-entity filter chooses which of those neighbours to retain; it does
not change the identity or claims of the relationships connecting them. Histogram
counts describe entity occurrence and guide the agent's next selection. Concrete
relationships are inspected through detailed results and relationship lookup.

An agent may use path search to plan a route between logical entities, then resolve each
entity link to datasets through entity-definition and dataset-level discovery. Cross-entity
relationships never filter dataset-level discovery or change a relationship or its claims.

An entity link joins two logical entities that have entity definitions on a common dataset
(inferred) or a stated cross-entity relationship (stated). A stated entity link carries that
relationship's descriptions and claims. A path restates a shorter path on the same records
when, for every choice of common datasets and entity definitions for its entity links, two
consecutive entity links meet on one entity definition; a stated cross-entity relationship
never restates. A path repeats no logical entity, except that the caller may allow a logical
entity one self link, through two of its entity definitions on one dataset or a stated self
relationship, before the path moves on. `get_entity_links` lists the entity links at a
logical entity. `get_dataset_edges` lists the directed edges at a dataset, which join datasets
through a shared logical entity. `get_entity_definitions` maps an entity link to the datasets
that realize it, those holding entity definitions of both logical entities.

Dataset records use a consistent structure across lookup and navigation operations,
with metadata selected by the operation and detail level. Search subject rows are
abbreviated discovery records. The bundled graph API skill documents available fields,
bounds, and detail-level guidance.
