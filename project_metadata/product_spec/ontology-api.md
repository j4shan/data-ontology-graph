# Ontology Access Interface

The initial knowledge-access interface is provided by one OS-managed
background graph service against an immutable offline copy. Local reasoning
agents call the same JSON-RPC 2.0 request/response tool interface over a
Unix-domain socket in production and development. Every request carries an
`id`; fire-and-forget notifications are not supported. The service provides
entity and relationship evidence for downstream reasoning and has no network
boundary.

## 4 Local knowledge access from a published snapshot

Local tools read a published snapshot. They do not rebuild the graph on every
query or mutate graph knowledge.

### 4.1 Search

Search returns a reduced candidate set of logical identities and associated
entity-definition and dataset references. Candidates may match a stable ID,
business name, synonym, tag, qualified dataset name, accessor property,
dataset-column set, or entity
entity metadata. Results include enough match provenance and identifying
metadata for the reasoning agent to choose what to inspect next.

The initial search implementation mechanically normalizes indexed terms and
queries, then performs exact lookup and prefix-descendant enumeration over a
static `marisa-trie` `RecordTrie`. Posting records reference authoritative
snapshot objects rather than duplicating them. Multiple terms, including
authored synonyms, may reference the same object; one term may reference more
than one object. Straightforward filtering, deduplication, stable ordering, and
caller-configurable result limiting after trie retrieval are sufficient for the expected domain
scale of at most about 10,000 business entities. The service does not require a
dedicated relevance-ranking structure.

Search narrows irrelevant context; it does not decide which candidate is
correct. The reasoning agent may coordinate with separate enterprise entity,
terminology, semantic, or full-text search tools to obtain canonical terms or
IDs before calling the graph service. Every supplied ID must still resolve in
the pinned graph snapshot.

### 4.2 Dataset detail

Dataset detail returns the descriptor, accessor, relevant columns, optional
grain, and entity definitions with entity metadata and universe status.

### 4.3 Directed hops

Traversal hops from a node are directed views of stored relationships, with
directional multiplicity and always/optional/unknown match existence as
defined in the [Data Modeling Spec](../product/data/data-modeling-spec.md).

### 4.4 Subgraph expansion

Subgraph expansion performs breadth-first traversal from one or more named
dataset seeds with caller-configurable maximum depth and result-item bounds. It
returns deduplicated dataset nodes, relationship edges, compound endpoint
references, directional relationship properties, and distance from a seed.
The returned node and edge collections respect the configured bounds. The
returned subgraph is downstream reasoning evidence; it is not itself a
completed AKG.

### 4.5 Ranked paths

Join-path search returns ranked paths between named datasets. Each hop carries
its logical identity, compound endpoint references,
directional multiplicity, and match existence. Paths are ranked by
hop count, then annotation weight. Callers supply maximum hop and result-item
limits, and returned paths respect both bounds. The interface does not pick a
single winner.

### 4.6 Relationship detail

A hop exposes its `identity_id`, endpoint node IDs and dataset-column sets,
directional relationship properties, and relationship identity. Connected
node detail supplies entity expressions, expression context, and accessor
metadata for the agent's AKG. The interface does not generate or validate SQL,
join predicates, or recommended SQL join types.

### 4.7 Entity-model guidance

Detail reports the dataset descriptor and accessor, its single optional grain,
registered logical identities, entity definitions, entity expressions, entity
metadata, and entity-universe status.

### 4.8 Singleton and sessionless request model

One OS-level background graph service loads a published snapshot and serves all
local query-resolution requests. It may keep the pinned immutable snapshot,
the static lexical trie, object maps, graph adjacency, and disposable caches in
memory. Those structures are service infrastructure, not reasoning-session
state.

Every request is independently interpretable. The service does not retain
conversation history, selected candidates, partially assembled AKGs, traversal
frontiers, or other client-session state. Evicting a cache may affect
performance but never response semantics. The initial public surface is one
JSON-RPC 2.0 request/response interface over a Unix-domain socket, used by both
production callers and local development. Every call requires a request `id`
and receives exactly one result or error response; notification messages are
outside the interface. The operating system manages the singleton process, and
socket filesystem permissions restrict access to the local user. HTTP/OpenAPI
is not part of the target interface.

### 4.9 Out of scope

The interface does not generate a complete query from natural language, pick
a single many-to-many path, choose a physical replica for execution, generate
or validate SQL, or execute SQL. General semantic-similarity and full-text
search are also outside the graph service; callers may coordinate with separate
tools for those capabilities. Data-statistics retrieval is deferred.

### 4.10 Read-only local surface

Local knowledge tools do not accept YAML definition updates, annotation
updates, validation, rebuild, or publication requests. Search and traversal do
not change the published offline copy. An online knowledge store is an
optional future enhancement.

### 4.11 Functional request bounds

Search and graph-navigation operations expose configurable bounds appropriate
to the operation, including result-item counts, breadth-first expansion depth,
and path hop count. These bounds are part of response semantics and are high
priority. Response-byte counters, tool-call tracing, task-level context totals,
and benchmarking instrumentation are not required for bounded operation.

## 5 Non-normative proposals

The proposals in this section record ideas under consideration. They are not
initial-release requirements or release gates unless they are promoted into a
numbered requirement elsewhere in the product specification.

### 5.1 Retrieval instrumentation and service benchmarking

Lower-priority instrumentation could record response-byte counts, tool-call
traces, task-level context totals, result volumes, and traversal work for
monitoring or service-level benchmarking. It is not required to enforce the
functional request bounds in section 4.11.

Such measurements describe graph-service behavior only. Benchmarking whether
the tools improve a GenAI system's reasoning, AKG selection, or SQL-query
accuracy is outside this project and is TBD in a separate project.

Instrumentation could run in local tests or a separate monitoring workflow by
wrapping the same local tool interface. Persistent production tracing,
telemetry, and usage-statistics collection are not implied and are not release
prerequisites for search, lookup, or graph navigation.

### 5.2 Caller-supplied intermediary results

A future tool contract could accept caller-held intermediary results, such as
known node IDs, edge IDs, or a traversal frontier, to constrain later search or
continue subgraph expansion without retaining server-side session state. Any
such request would identify the snapshot release, and the graph service would
resolve all references against its authoritative copy rather than trusting
duplicated caller-supplied graph metadata.

The initial release does not require tools to accept prior subgraphs,
partially assembled AKGs, traversal frontiers, or other intermediary results.
