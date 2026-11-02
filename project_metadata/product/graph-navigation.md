# Product requirements: graph navigation

## 1. Graph navigation

An agent can inspect relationships, explore dataset neighbourhoods, and retrieve
connections between caller-selected datasets. Directed edges and their metadata are
defined in product/graph-model.md.

### Capabilities

- Look up a canonical relationship with its endpoint definitions and datasets, optionally
  viewing it from one endpoint while preserving the canonical evidence. When both
  endpoints belong to the same dataset, the caller identifies the source definition
  by its columns.
- Explore the neighbourhood of one or more datasets to a caller-selected depth.
  Expanded datasets present detailed adjacency grouped by logical entity and entity
  definition. Depth-boundary datasets report outgoing-edge counts without listing
  adjacency. Node and edge limits may omit results; counts and truncation indicators
  expose those omissions.
- Inspect one dataset's outgoing relationships through `get_edges`. A source filter
  may select a logical entity realized on that dataset or one of its definitions.
  The selected source definitions establish the connected dataset neighbourhood.
  High fan-out is supported discovery behaviour; the agent can inspect its
  distribution and retrieve detailed relationship evidence.
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
- Drill down through `get_edges` by selecting logical entities that the connected
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
- Retrieve bounded, ranked paths between two datasets, each as an ordered sequence
  of directed edges identifying their logical entities. Paths rank by edge count,
  then by the sequence of canonical edge IDs and starting entity definitions.
  A path may revisit a dataset through another definition, never reuses a definition,
  and changes definitions between consecutive relationship traversals.
  An optional multiplicity filter applies in the traversal direction; unknown
  multiplicity passes a restrictive filter only when explicitly allowed.
- Retrieve one approximate connecting subgraph for at least two distinct selected
  datasets, including intermediate datasets where needed. The server-configured
  input maximum defaults to 16. The result is not a guaranteed minimum and does not
  enumerate alternatives. When the selected datasets cannot all be connected,
  report that outcome and return the selected datasets without connecting edges.
- Offer `essential`, `standard`, and `full` navigation detail levels, with named
  fields that callers may add. Detail selection does not change result bounds.
  Dataset records always identify their node ID and qualified name; directed
  edges identify their canonical edge ID, source and target definitions, and
  logical entity, either directly or through their containing group.
  Neighbourhood and connecting-subgraph results associate adjacency with datasets;
  ranked-path results present edges in path order with datasets listed separately.

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

Dataset records use a consistent structure across lookup and navigation operations,
with metadata selected by the operation and detail level. Search subject rows are
abbreviated discovery records. The bundled graph API skill documents available fields,
bounds, and detail-level guidance.
