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

Search returns a reduced candidate set of logical identities, datasets, entity
definitions, and columns. The optional `kind` request field is a non-empty list
of one or more of `identity`, `dataset`, `entity_definition`, and `column`;
omitting it searches all four kinds. Candidates may match a stable ID, business
name, synonym, tag, description, qualified dataset name, accessor property,
dataset-column set, column metadata, or entity metadata. Each match reports its
match type, field, matched term, and original value.

The response contains one group for each requested kind, in lexical order:
`column`, `dataset`, `entity_definition`, `identity`. A group holds two row
tables. Each table has a header that names the value at each position of its
rows, so callers read rows by position rather than by repeated property keys:

| Header | Columns |
| --- | --- |
| `subject_row_header`, `column` | `key`, `node_id`, `column_name` |
| `subject_row_header`, `dataset` | `key`, `display_name`, `unknown_fields` |
| `subject_row_header`, `entity_definition` | `key`, `entity_expression`, `node_id`, `identity_id`, `dataset_columns`, `unknown_fields` |
| `subject_row_header`, `identity` | `key`, `name` |
| `match_row_header`, every kind | `key`, `match_type`, `match_field`, `matched_term`, `matched_value` |

`subject_rows` has one row per matched subject. `match_rows` has one row for
each of that subject's field values that matched, joined to its subject by
`key`. `match_field` names the property that holds `matched_value`, the
original field text, and `matched_term` is the normalized text that matched.
Stored terms are the whole normalized value and each of its words.
`match_type` is one of:

| `match_type` | Meaning |
| --- | --- |
| `exact` | A stored term equals the normalized query. |
| `prefix` | A stored term starts with the normalized query. |
| `phrase` | Multi-word query, word-match value only: consecutive words of the value start with the query words, in order. |
| `all_words` | Multi-word query, word-match value only: each query word starts some word of the value, in any order or position. |

A value that matches more than one way reports only its best type, in table
order. The word-match values are a dataset's `qualified_name` and
`display_name` and a logical identity's `name`. All query words must occur in
the same value; words spread across values or subjects do not match. Every
other value matches a multi-word query only when it starts with the phrase.

Subjects are ordered by their best match type, then normalized label, then key.
A subject's match rows are ordered by match type, then field. The result limit
applies to the subjects of each group separately; a group's `truncated` is true
when the limit omits eligible subjects, and the response `truncated` is true
when any group's is.

The initial search implementation mechanically normalizes indexed terms and
queries, then performs exact and prefix lookup over a static `marisa-trie`
`RecordTrie`. A multi-word query also looks up each word and intersects the
values that contain every word. Posting
records reference authoritative snapshot objects rather than duplicating them.
Multiple terms, including authored synonyms, may reference the same object;
one term may reference more than one object. Filtering, deduplication, stable
ordering, and a per-kind result limit are sufficient for the expected domain scale
of at most about 10,000 business entities. The service does not require a
dedicated relevance-ranking structure.

At build time, a description or value description whose whole normalized value is a
placeholder, such as `null`, `N/A`, `unknown`, `undefined`, `missing`, or `TBD`, contributes no
search terms. The text is still returned unchanged in detail responses. Text that only contains
such a word, such as "unknown sender flag", is indexed normally. Names, synonyms, and tags are
never filtered.

Search narrows irrelevant context; it does not decide which candidate is
correct. The reasoning agent may coordinate with separate enterprise entity,
terminology, semantic, or full-text search tools to obtain canonical terms or
IDs before calling the graph service. Every supplied ID must still resolve in
the pinned graph snapshot.

### 4.2 Dataset detail

Dataset detail returns the descriptor, accessor, relevant columns, grain, and
entity definitions with entity metadata and universe status.

Every dataset, entity definition, and relationship in a response carries
`unknown_fields`, the typed claims whose value is `unknown`. Callers read unknown
state from `unknown_fields` rather than interpreting field values. Search hits
report each subject's `unknown_fields`; unknown claim values are not search terms.
Directed hops and path hops report unknown fields relative to the traversal
direction (`direction.*` and `reverse_direction.*`).

### 4.3 Directed hops

Traversal hops from a node are directed views of stored relationships, with
directional multiplicity and always/optional/unknown match existence as
defined in the [Data Modeling Spec](../data/data-modeling-spec.md).

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
its logical identity, compound endpoint references, and both directional claims
of multiplicity and match existence: `direction` moves from the hop's
`from_node_id` to its `to_node_id`, and `reverse_direction` moves back.
`unknown_fields` names unknown claims as `direction.*` or `reverse_direction.*`,
as on hop and oriented relationship detail. Paths are ranked by
hop count, then canonical edge IDs. Callers supply maximum hop and result-item
limits, and returned paths respect both bounds. The interface does not pick a
single winner. Semantic analysis and path selection remain the caller's responsibility.

An optional `allowed_multiplicities` filter constrains each hop in the traversal
direction. Omission leaves traversal unrestricted. Unknown multiplicity is
eligible only when explicitly allowed. Disallowed hops are pruned before
expansion; filtering must not worsen asymptotic traversal time or space complexity.

### 4.6 Relationship detail

Relationship lookup accepts an `edge_id` and optional `from_node_id`, which
must identify one of the edge's endpoint nodes. Its detail always includes
canonical `endpoint_a`, `endpoint_b`, `a_to_b`, and `b_to_a`. When
`from_node_id` is supplied, `direction` contains claims moving away from that
node and `reverse_direction` contains claims moving toward it. `unknown_fields`
then names unknown claims as `direction.*` or `reverse_direction.*`. Without an
origin, `from_node_id`, `direction`, and `reverse_direction` are null, and
`unknown_fields` uses canonical `a_to_b.*` and `b_to_a.*` names. The relative
fields are a view of the same edge; they do not change its persisted endpoint
order or directional claims.

Relationship detail also exposes its `identity_id`, endpoint node IDs and
dataset-column sets, and relationship identity. Connected node detail supplies
entity expressions, expression context, and accessor metadata for the agent's
AKG. The interface does not generate or validate SQL, join predicates, or
recommended SQL join types.

### 4.7 Entity-model guidance

Detail reports the dataset descriptor and accessor, its grain or explicit unknown grain,
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
search are also outside the graph service, except for word matching of
multi-word queries against dataset qualified and display names and logical-identity
names. Callers may coordinate with
separate tools for broader search. Data-statistics retrieval is deferred.

### 4.10 Read-only local surface

Local knowledge tools do not accept YAML definition updates, annotation
updates, validation, rebuild, or publication requests. Search and traversal do
not change the published offline copy. An online knowledge store is an
optional future enhancement.

### 4.11 Functional request bounds

Search and graph-navigation operations expose configurable bounds appropriate
to the operation, including result-item counts, breadth-first expansion depth,
and path hop count. Connecting-subgraph requests additionally bound the input
dataset count. These bounds are
part of response semantics and are high priority. Response-byte counters,
tool-call tracing, task-level context totals, and benchmarking instrumentation
are not required for bounded operation.

### 4.12 Connecting selected datasets

`graph.find_connecting_subgraph` accepts caller-selected dataset endpoints in
`node_ids` and returns one compact connecting tree, including intermediate
datasets and their relationship evidence. The initial request accepts 2–16
distinct datasets; the maximum is configurable server-side. Endpoint selection and semantic
interpretation remain the caller's responsibility.

Use a polynomial-time undirected Steiner-tree approximation based on
Mehlhorn's multi-source approach. Connectivity considers relationships
traversable in either direction, while responses preserve both directional
claims. The result is approximate, not a guaranteed minimum or an enumeration
of all alternatives. Response ordering must be deterministic.

The search runs in time linear in the graph size and stops as soon as the
tree is settled, so nearby endpoints touch only their neighbourhood. Responses
report `status` as `completed` or `disconnected`, with dataset and relationship
collections; a disconnected response returns the endpoint datasets and no
relationships. The approximation guarantee applies to connected inputs.
Graph computation runs outside the request event loop, with bounded concurrent
computations and cancellation support.

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
