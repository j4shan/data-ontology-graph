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
  Listing one dataset's outgoing edges is depth-one exploration and may be restricted
  to a logical entity or one of its definitions. Expanded datasets present adjacency
  grouped by logical entity and entity definition, with edge limits applied per
  definition. Depth-boundary datasets report outgoing-edge counts without listing
  adjacency. Node and edge limits may omit results; counts and truncation indicators
  expose those omissions.
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

Dataset records use a consistent structure across lookup and navigation operations,
with metadata selected by the operation and detail level. Search subject rows are
abbreviated discovery records. The bundled graph API skill documents available fields,
bounds, and detail-level guidance.
