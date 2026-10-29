# Graph service API

This document describes graph API version `1`.

The service discovers dataset metadata and explores relationships in one published graph.
It is read-only and sessionless: the caller selects evidence and maintains its own working
context. It does not execute queries against source datasets or return source rows.

Contents: [transport](#transport-and-errors), [shared schemas](#shared-response-schemas),
[detail and fields](#navigation-detail-and-fields), [discovery](#discovery-and-lookup-methods),
[traversal](#traversal-methods), and [examples](#examples).

## Transport and errors

Each call sends one newline-terminated JSON-RPC 2.0 object over a Unix-domain socket:

```json
{"jsonrpc":"2.0","id":1,"method":"graph.get_dataset","params":{"node_id":"DATASET_ID"}}
```

The service returns either `{"jsonrpc":"2.0","id":1,"result":...}` or
`{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Invalid params","data":...}}`.
`data` is optional. The bundled proxy prints only the unchanged `result` or `error` member
inside its wrapper. Local connection and input errors have a message but no service error code.

The socket interface also accepts nonempty JSON-RPC batches, processed sequentially. The
bundled proxy sends one request at a time. Every request requires an ID; notifications are
not supported.

| Code | Meaning |
| --- | --- |
| `-32700` | Invalid JSON. |
| `-32600` | Invalid request envelope, including a missing request ID. |
| `-32601` | Unknown method. |
| `-32602` | Invalid parameters, unsupported fields, bounds, or endpoint selection. |
| `-32603` | Internal service error. |
| `-32004` | Unknown dataset, logical entity, or relationship. |

All method parameters below belong in the `params` object. Unlisted parameters are rejected.
Required IDs are nonempty strings; copy canonical IDs from responses. Optional filters default
to no filter. Lists of enum filters are nonempty when supplied. Bounds below are defined by
the API; the skill adds no call-count or cost limits.

## Shared response schemas

The notation below describes JSON values: `T[]` is an array, `T | null` permits null, and `?`
marks a field that can be absent. Arbitrary JSON objects are written as `object`.

### Snapshot

```text
Snapshot = {
  api_version: string, version: string,
  node_count: integer, edge_count: integer, identity_count: integer
}
```

`api_version` names the API contract described here. It is currently `1` and rises only on a
breaking change to a method, parameter, response field, or meaning; additions keep it.
`version` is the snapshot's UTC build time to the second (`YYYY-MM-DDTHH:MM:SSZ`) and
identifies the published data.

### Dataset and entity metadata

```text
Dataset = {
  node_id: string, qualified_name: string,
  accessor?: {schema_id?: string, properties?: object},
  grain?: "unknown" | {
    components: [{dataset_columns: string[], identity_id: string | null, description: string}],
    description: string
  },
  descriptor?: {display_name?: string, description?: string, synonyms?: string[], tags?: string[]},
  unknown_fields?: string[], columns?: Column[], entity_definitions?: Definition[],
  distance?: integer, edge_count?: integer, edge_groups?: EdgeGroup[]
}
Column = {name: string, description: string, value_description: string, synonyms: string[]}
Definition = {
  identity_id: string, dataset_columns: string[],
  entity_universe?: "complete" | "partial" | "unknown",
  unique?: boolean | "unknown", total?: boolean | "unknown", conforms?: boolean | "unknown",
  entity_expression?: string[], entity_metadata?: object, description?: string,
  effective_description?: string | null, description_source?: "entity" | "column" | null,
  unknown_fields?: string[]
}
```

`get_dataset` returns every metadata field, without navigation-only `distance`, `edge_count`,
or `edge_groups`. Lookup dataset collections from `get_identity` and `get_relationship` also
omit `distance` and `edge_count`. Other methods select dataset fields by detail. Standalone definition
collections add `node_id`; nested definitions take it from their dataset.

- `qualified_name` identifies the deployed dataset in source terminology. `node_id` is its
  graph key. Display names need not be unique.
- `accessor` is a credential-free location recipe. Its `schema_id` selects provider-specific
  properties; do not assume all datasets are SQL tables.
- `grain` describes one record's boundary. Composite components together define that boundary.
- An entity definition realizes a logical entity through its `dataset_columns` and describes
  the role of those columns. `entity_expression` contains descriptive labels, not executable
  expressions or a positional column-mapping contract.
- `entity_universe` describes key coverage: `complete`, `partial`, or unassessed. It does not
  establish record uniqueness. `unique` means each non-null entity instance occurs at most
  once; `total` means every record has a non-null key; `conforms` means every non-null key
  belongs to the logical entity's population.
- `effective_description` uses the definition's description, otherwise the description of
  its single unmodified column when applicable, otherwise null. `description_source` records
  which supplied it.
- `unknown_fields` names typed claims whose value is `unknown`. Descriptive text does not
  establish or override a typed claim.

Supported accessor recipes currently include:

| `schema_id` | Properties |
| --- | --- |
| `accessor.sqlite.v1` | `host`, absolute `database_path`, `schema`, `object`. |
| `accessor.sql-database.v1` | `host`, `database`, `schema`, `object`, `dialect`, optional `format`. |
| `accessor.snowflake.v1` | `account`, `database`, `schema`, `object`, optional `format`. |
| `accessor.databricks-unity.v1` | `workspace_host`, `catalog`, `schema`, `object`, optional `format`. |
| `accessor.s3.v1` | `bucket`, `prefix`, `format`. |

These property values are strings; optional `format` may be null.

### Collections and response format

`Collection<T>` is either a table `{"header": string[], "rows": any[][]}` (the default) or
an array of records `T[]` when `response_format: "records"` is supported and requested.
Each table row follows its header. Dotted headers are nested record paths: for example,
`accessor.schema_id`. Decode with the returned header, not assumed positions.

Navigation in table format separates dataset fields, columns, definitions, and edge groups:

```text
Navigation = {
  detail: "essential" | "standard" | "full", fields: {object_name: string[]},
  edge_fields: string[], datasets: Collection<Dataset>, truncated: boolean,
  edge_groups?: [{node_id: string, identity_id: string, entity_definitions: GroupDefinition[]}],
  columns?: Table, entity_definitions?: Table
}
EdgeGroup = {identity_id: string, entity_definitions: GroupDefinition[]}
GroupDefinition = {
  dataset_columns: string[], edge_count: integer, truncated: boolean, edges: any[][]
}
```

In records format, `columns`, `entity_definitions`, and `edge_groups` nest in each dataset;
their separate top-level collections are omitted. Edge arrays and edge-group contents are the
same in both formats. In table format, column and definition rows are keyed by `node_id`;
each top-level edge group includes its owning `node_id`.

Only expanded datasets have edge groups. A definition with no relationships may have no
edge-group entry. A boundary dataset's missing edge groups do not mean it has no relationships:
its `edge_count` reports the total number of directed edges leaving it in the graph.

### Directed edges and claims

Each edge is an array whose positions are named once by `edge_fields`. The normal order is:

```json
["edge","multiplicity","match_existence","reverse_multiplicity","reverse_match_existence","from_description","to_description","annotation","edge_id"]
```

Only selected fields appear. `edge` is first and `edge_id` last. Path arrays additionally
include `identity_id` immediately after `edge`. Grouped navigation normally holds it in the
enclosing group, and `get_relationship` holds it at the top level. Caller-added edge fields
may also include it in grouped edge arrays.

`edge` is `start_node_id[col1,col2] -> end_node_id[col1,col2]`. Columns are in the returned
definition order. Names containing a comma, square bracket, double quote, or `->` use JSON
string quoting, for example `bank.t["a,b"]`. An edge ID identifies the underlying relationship;
its direction comes from the label and owning entity definition. A self-relationship yields
two directed edges on the same dataset, distinguished by their starting columns.

| Field | Type and meaning |
| --- | --- |
| `multiplicity`, `reverse_multiplicity` | `1:1`, `1:many`, `many:1`, `many:many`, or `unknown`. Outgoing and reverse row multiplicities. |
| `match_existence`, `reverse_match_existence` | `always`, `optional`, or `unknown`. Outgoing and reverse match existence. |
| `from_description`, `to_description` | Effective endpoint descriptions, string or null. |
| `annotation` | `{edge_id: string, description: string, tags: string[]}` or null. Descriptive relationship metadata. |

`always` means every record on that side has a match. `optional` permits zero matches;
it does not assert observed unmatched records. `unknown` establishes neither. Match existence
and multiplicity are independent. Which population an analytical question preserves is caller
reasoning, not a change to these claims.

## Navigation detail and fields

These parameters apply to `get_edges`, `expand_subgraph`, `find_paths`, and
`find_connecting_subgraph`:

| Parameter | Type | Default | Effect |
| --- | --- | --- | --- |
| `response_format` | `"table"` or `"records"` | `"table"` | Dataset and metadata collection representation. |
| `detail` | `"essential"`, `"standard"`, or `"full"` | `"standard"` | Selects fields; never changes result bounds. |
| `fields` | Object mapping `dataset`, `edge`, or `entity_definition` to string arrays | `{}` | Adds fields to the chosen detail level. Unknown objects or field names are invalid. |

Detail levels are cumulative:

| Level | Dataset fields | Directed-edge fields |
| --- | --- | --- |
| `essential` | `node_id`, `qualified_name`, `accessor.schema_id`, `distance` where applicable, `edge_count`. | `edge`, `multiplicity`, `match_existence`, `edge_id`. |
| `standard` | Adds `grain`, `descriptor.description`, `unknown_fields`. | Adds reverse claims and endpoint descriptions. |
| `full` | Adds `descriptor.display_name`, `descriptor.synonyms`, `descriptor.tags`, `accessor.properties`, `columns`, `entity_definitions`. | Adds `annotation`. |

Use essential for initial exploration, standard for relationship analysis, and full when
complete metadata is needed. `node_id` and `qualified_name` are always present; `edge` and
`edge_id` are always present in edges, as is `identity_id` for paths.

The complete caller-added field catalog is:

| Object | Allowed field names |
| --- | --- |
| `dataset` | `node_id`, `qualified_name`, `distance`, `edge_count`, `accessor.schema_id`, `grain`, `descriptor.description`, `unknown_fields`, `descriptor.display_name`, `descriptor.synonyms`, `descriptor.tags`, `accessor.properties`, `columns`, `entity_definitions`. |
| `edge` | `edge`, `identity_id`, `multiplicity`, `match_existence`, `reverse_multiplicity`, `reverse_match_existence`, `from_description`, `to_description`, `annotation`, `edge_id`. |
| `entity_definition` | `identity_id`, `dataset_columns`, `entity_universe`, `unique`, `total`, `conforms`, `entity_expression`, `entity_metadata`, `description`, `effective_description`, `description_source`, `unknown_fields`. |

Requesting entity-definition fields also includes the definitions collection. Its identifying
`identity_id` and `dataset_columns` are always present; full detail includes every definition
field. Adding dataset `entity_definitions` alone at a lower level returns identifying fields.
`distance` is omitted for paths and connecting subgraphs even if requested.

## Discovery and lookup methods

### `graph.snapshot_info`

Parameters: none (`{}`). Returns `Snapshot`. Use it to check the connection and inspect the
served graph's metadata.

### `graph.search`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `query` | string, required | Nonempty. |
| `kind` | Array of `"identity"`, `"dataset"`, `"entity_definition"`, `"column"` | Omitted or null searches all kinds; otherwise nonempty. |
| `limit` | integer | 50; range 1–1000, applied per kind. |

Returns:

```text
{
  snapshot: Snapshot, query: string, normalized_query: string, truncated: boolean,
  groups: [{kind: string, truncated: boolean,
    subject_row_header: string[], subject_rows: (string | string[] | null)[][],
    match_row_header: string[], match_rows: string[][]}]
}
```

Join a group's subject and match rows on `key`. Subject headers by kind are:

| Kind | Subject header |
| --- | --- |
| `column` | `key`, `node_id`, `column_name`. |
| `dataset` | `key`, `qualified_name`, `unknown_fields`. |
| `entity_definition` | `key`, `entity_expression`, `node_id`, `identity_id`, `dataset_columns`, `unknown_fields`. |
| `identity` | `key`, `name`. |

The match header is `key`, `match_type`, `match_field`, `matched_term`, `matched_value`.
Each matching field value has one match row. Dataset and identity keys are their canonical IDs;
other subject keys identify search rows and should not be substituted for dataset IDs.

Search normalizes Unicode, case, camel-case boundaries, punctuation, and whitespace. It
indexes names, IDs, descriptions, synonyms, dataset tags/accessors, column metadata, and
entity-definition metadata. Whole-value description placeholders such as `N/A` and `TBD`
are not indexed; returned descriptions remain unchanged.

Match types, strongest first, are `exact`, `prefix`, `phrase`, and `all_words`. Exact and prefix
compare normalized stored terms (whole values and individual words). Phrase and all-words
matching apply only to dataset qualified/display names and logical-entity names: query words
prefix consecutive words or words in any order within one value, respectively. Other fields
match a multi-word query only as a whole-value prefix or exact value. Subjects sort by best
match type, normalized label, then key. This lexical ordering does not decide semantic relevance.
The top-level `truncated` is true when any group's limit omitted eligible subjects.

### `graph.get_dataset`

Parameters: required nonempty string `node_id`. Returns one full `Dataset` record. It does
not accept `detail`, `fields`, or `response_format`.

### `graph.get_identity`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `identity_id` | string, required | Canonical logical entity ID. |
| `entity_universe` | Array of `"complete"`, `"partial"`, `"unknown"` | Omitted or null leaves coverage unfiltered; otherwise nonempty. |
| `limit` | integer | 100; range 1–1000, counts entity definitions. |
| `response_format` | `"table"` or `"records"` | `"table"`. |

Returns `{identity_id: string, name: string, description: string, synonyms: string[],
entity_definitions: Collection<Definition with node_id>, datasets: Collection<Dataset>,
truncated: boolean}`. Definitions include all their metadata and sort by `node_id`, then
`dataset_columns`. Coverage filtering happens before the limit. Datasets use standard detail
and appear once per selected dataset. `truncated` means eligible definitions were omitted.

### `graph.get_relationship`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `edge_id` | string, required | Canonical relationship ID. |
| `from_node_id` | string | Omitted or null keeps only the canonical view. |
| `from_dataset_columns` | Nonempty string array | Requires `from_node_id`; required to distinguish self-relationship endpoints. |
| `response_format` | `"table"` or `"records"` | `"table"`. |

Returns:

```text
{
  edge_id: string, identity_id: string,
  endpoint_a: {node_id: string, dataset_columns: string[]},
  endpoint_b: {node_id: string, dataset_columns: string[]},
  a_to_b: {multiplicity: string, match_existence: string},
  b_to_a: {multiplicity: string, match_existence: string},
  unknown_fields: string[], annotation: object | null,
  from_node_id: string | null, from_dataset_columns: string[] | null,
  edge_fields: string[] | null, edge: any[] | null,
  datasets: Collection<Dataset>, entity_definitions: Collection<Definition with node_id>
}
```

Canonical endpoints and both directions are always returned. With `from_node_id`, `edge`
is the directed view leaving that endpoint at standard positions, and `edge_fields` names
them. Without it those fields are null. Endpoint datasets use standard detail; the separate
definitions include full metadata. This method does not accept navigation detail or fields.

## Traversal methods

Each method accepts the shared navigation parameters above. All return `Navigation` plus
the method-specific fields below. Edges are explicit; returning two datasets does not imply
selecting every relationship between them.

### `graph.get_edges`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `node_id` | string, required | Starting dataset. |
| `limit` | integer | 200; range 1–1000 per entity definition. |
| `identity_id` | string | Omitted or null leaves logical entities unfiltered. |
| `from_dataset_columns` | Nonempty string array | Requires `identity_id`; selects one starting definition. |

Adds `{node_id: string, limit: integer}` to `Navigation`. Lists outgoing edges grouped by
logical entity and starting definition. A filter matching no definition is invalid parameters.
The start has distance 0, including targets of self-relationships; other listed targets are
boundary datasets at distance 1. Group
`edge_count` counts eligible outgoing edges before its limit, and `truncated` reports cuts.
Top-level `truncated` means at least one definition's edge list was cut. There is no paging.

### `graph.expand_subgraph`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `seed_node_ids` | Nonempty string array, required | Starting datasets; duplicates are deduplicated. |
| `max_depth` | integer | 1; range 0–10. |
| `max_nodes` | integer | 1000; range 1–10000, at least the number of unique seeds. |
| `limit` | integer | 200; range 1–1000 per entity definition. |

Adds `{snapshot: Snapshot, seed_node_ids: string[], max_depth: integer, max_nodes: integer,
limit: integer}`. Expands breadth-first, with datasets ordered by distance then `node_id`.
Datasets below `max_depth` list edges; boundary datasets list only metadata and counts.
`max_nodes` caps datasets and `limit` caps each definition's edges; edges to omitted targets
are not listed. `truncated` reports omitted results from either cap. A depth boundary alone
does not mean the result is truncated.

### `graph.find_paths`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `from_node_id` | string, required | Starting dataset. |
| `to_node_id` | string, required | Target dataset. |
| `max_edges` | integer | 4; range 1–10. |
| `limit` | integer | 6; range 1–100 paths. |
| `allowed_multiplicities` | Array of `"1:1"`, `"1:many"`, `"many:1"`, `"many:many"`, `"unknown"` | Omitted or null leaves traversal unrestricted; otherwise 1–5 entries. |

Adds `{snapshot: Snapshot, from_node_id: string, to_node_id: string, path_count: integer,
paths: any[][][]}`. `paths` is a ranked array of paths, each a travel-ordered array of directed
edges. Each edge includes `identity_id`. `path_count` counts returned paths, not all possible
paths. `datasets` contains the path datasets once each, without nested edge groups or distances.

Paths rank by edge count, then canonical edge IDs and starting definitions. A path can revisit
a dataset through different definitions; it never reuses a definition or takes two consecutive
edges on the same key. Multiplicity filtering applies in traversal direction. Unknown
multiplicity passes a restrictive filter only when `"unknown"` is explicitly allowed.
`truncated` indicates an additional eligible path or interrupted path search. Zero returned
paths means none were found under the supplied bounds and filters.

### `graph.find_connecting_subgraph`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `node_ids` | Array of distinct nonempty strings, required | At least 2 datasets; server-configured maximum, default 16. |

Adds `{snapshot: Snapshot, node_ids: string[], status: "completed" | "disconnected",
algorithm: "mehlhorn_unweighted"}`. Returns one approximate connecting tree, including
intermediate datasets, rather than alternatives or a guaranteed minimum. Selected dataset
IDs are echoed in sorted order. Datasets appear in `node_id` order, each with the outgoing directed
edges of the tree's relationships. On `disconnected`, returns the selected datasets without
connecting edges. No distance is returned, and `truncated` is false. This method has no
`limit`, `max_depth`, or multiplicity-filter parameter; its fields and detail remain configurable.

## Examples

Find datasets and inspect their full metadata:

```json
{"query":"opening region","kind":["dataset","column"],"limit":50}
```

Use those params with `graph.search`, then call `graph.get_dataset` with a returned `node_id`.
For edges, retain standard claims while adding selected dataset metadata:

```json
{"node_id":"sqlite:lending.loan","detail":"standard","response_format":"records","fields":{"dataset":["columns","accessor.properties"]}}
```

For paths restricted to outgoing non-fan-out multiplicities:

```json
{"from_node_id":"sqlite:lending.loan","to_node_id":"sqlite:lending.region","allowed_multiplicities":["1:1","many:1"],"max_edges":4,"limit":6}
```

These dataset IDs are illustrative; they must resolve in the served graph. Choosing a path
still requires checking the meaning of its endpoint columns and intermediate datasets.
