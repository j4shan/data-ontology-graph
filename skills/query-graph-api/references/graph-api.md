# Graph service API

This document describes graph API version `5`.

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
  node_count: integer, entity_definition_count: integer, identity_count: integer,
  entity_relationship_count: integer
}
```

`api_version` names the API contract described here. It is the string `"5"`.
`entity_definition_count` is the number of entity definitions in the snapshot, and
`entity_relationship_count` the number of cross-entity relationships.
`graph.get_entity_definitions` provides filtered discovery.
`version` is the snapshot's UTC build time to the second (`YYYY-MM-DDTHH:MM:SSZ`).
Detailed `get_edges` and `get_entity_definitions` cursors bind to snapshot content as well as
the displayed build time.
Every response carries `snapshot`, including `graph.get_dataset` and `graph.get_relationship`.
Entity definition, column, and cross-entity relationship IDs are valid only in the snapshot
that issued them. A caller holding these IDs can detect a different snapshot by its `version`;
the service does not detect IDs from another snapshot.

Entity definitions, columns, and cross-entity relationships have IDs `D<n>`, `C<n>`, and
`X<n>`, respectively. Each decimal ordinal starts at 1 and follows the ascending order of
the object's natural key. Identical content yields identical IDs; any content change may
renumber them. These IDs are opaque. Contributor-authored `node_id` and `identity_id` remain
unchanged.

### Dataset and entity metadata

```text
Dataset = {
  node_id: string, qualified_name: string,
  accessor?: {kind?: string, endpoint?: string, labels?: {string: string}, properties?: object | null},
  grain?: "unknown" | {
    components: [{dataset_columns: string[], identity_id: string | null, description: string}],
    description: string
  },
  descriptor?: {display_name?: string, description?: string, synonyms?: string[], tags?: string[]},
  unknown_fields?: string[], columns?: Column[], entity_definitions?: Definition[],
  distance?: integer, edge_count?: integer, edge_groups?: EdgeGroup[]
}
Column = {id: string, name: string, description: string, value_description: string, synonyms: string[]}
Definition = {
  id: string, identity_id: string, dataset_columns: string[],
  entity_universe?: "complete" | "partial" | "unknown",
  unique?: boolean | "unknown", total?: boolean | "unknown", conforms?: boolean | "unknown",
  entity_expression?: string[], entity_metadata?: object, description?: string,
  effective_description?: string | null, description_source?: "entity" | "column" | null,
  unknown_fields?: string[]
}
```

`get_dataset` returns every metadata field, without navigation-only `distance`, `edge_count`,
or `edge_groups`. Dataset collections from `get_entity_definitions` and `get_relationship`
also omit `distance`, `edge_count`, and `edge_groups`. Other methods select dataset fields by
detail. Standalone definition collections put `id` before `node_id`; nested definitions take
`node_id` from their dataset.

- `qualified_name` identifies the deployed dataset in source terminology. `node_id` is its
  graph key. Display names need not be unique.
- `accessor` is a credential-free path of information to the dataset's data, written by the
  contributor. `kind` names the kind of system in the contributor's words, such as `postgresql`,
  `kafka`, or `sharepoint list`; it has no fixed vocabulary. `endpoint` is where the path starts:
  a server address, URI, account identifier, connection name configured in a connector plugin, or
  a shared document that holds connection details. `labels` is a map of strings, `{}` when
  absent. `properties` holds any further facts in any JSON shape, or `null` when absent. The
  graph does not follow, check, or interpret an accessor, and no dataset is assumed to be a SQL
  table.
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

### Collections and response format

`Collection<T>` is either a table `{"header": string[], "rows": any[][]}` (the default) or
an array of records `T[]` when `response_format: "records"` is supported and requested.
Each table row follows its header. Dotted headers are nested record paths: for example,
`accessor.kind`. Decode with the returned header, not assumed positions.

Detailed navigation in table format separates dataset fields, columns, definitions, and edge
groups. An aggregated `get_edges` response uses the separate shape documented below:

```text
Navigation = {
  detail: "essential" | "standard" | "full", fields: {object_name: string[]},
  edge_fields: string[], datasets: Collection<Dataset>, truncated: boolean,
  edge_groups?: [{node_id: string, identity_id: string, entity_definitions: GroupDefinition[]}],
  columns?: Table, entity_definitions?: Table
}
EdgeGroup = {identity_id: string, entity_definitions: GroupDefinition[]}
GroupDefinition = {
  id: string, dataset_columns: string[], edge_count: integer, truncated: boolean, edges: any[][]
}
```

In records format, `columns`, `entity_definitions`, and `edge_groups` nest in each dataset;
their separate top-level collections are omitted. Edge arrays and edge-group contents are the
same in both formats. In table format, column and definition headers start with `id`, then
`node_id`; each top-level edge group includes its owning `node_id`.

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
definition order. Node IDs and column names containing `,`, `[`, `]`, `"`, or `->` use JSON
string quoting; for example, node `a[b]` with column `id` appears as `"a[b]"[id]`.
The relationship's `edge_id` is `D<i>-D<j>`, the IDs of its two endpoint entity definitions
with `i < j` (for example, `D1-D8`). It is an opaque snapshot-local ID: compare it, never parse
it. Its direction comes from the `edge` label and owning entity definition. Endpoint details
are also available from `graph.get_relationship`. A self-relationship yields
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
`find_connecting_subgraph`. For aggregated `get_edges`, they select the echoed `detail` and
`fields` and the histogram's collection format; no dataset or edge fields are returned:

| Parameter | Type | Default | Effect |
| --- | --- | --- | --- |
| `response_format` | `"table"` or `"records"` | `"table"` | Dataset and metadata collection representation. |
| `detail` | `"essential"`, `"standard"`, or `"full"` | `"standard"` | Selects fields; never changes result bounds. |
| `fields` | Object mapping `dataset`, `edge`, or `entity_definition` to string arrays | `{}` | Adds fields to the chosen detail level. Unknown objects or field names are invalid. |

Detail levels are cumulative:

| Level | Dataset fields | Directed-edge fields |
| --- | --- | --- |
| `essential` | `node_id`, `qualified_name`, `accessor.kind`, `distance` where applicable, `edge_count`. | `edge`, `multiplicity`, `match_existence`, `edge_id`. |
| `standard` | Adds `accessor.endpoint`, `accessor.labels`, `grain`, `descriptor.description`, `unknown_fields`. | Adds reverse claims and endpoint descriptions. |
| `full` | Adds `descriptor.display_name`, `descriptor.synonyms`, `descriptor.tags`, `accessor.properties`, `columns`, `entity_definitions`. | Adds `annotation`. |

Use essential for initial exploration, standard for relationship analysis, and full when
complete metadata is needed. `node_id` and `qualified_name` are always present; `edge` and
`edge_id` are always present in edges, as is `identity_id` for paths.

The complete caller-added field catalog is:

| Object | Allowed field names |
| --- | --- |
| `dataset` | `node_id`, `qualified_name`, `distance`, `edge_count`, `accessor.kind`, `accessor.endpoint`, `accessor.labels`, `grain`, `descriptor.description`, `unknown_fields`, `descriptor.display_name`, `descriptor.synonyms`, `descriptor.tags`, `accessor.properties`, `columns`, `entity_definitions`. |
| `edge` | `edge`, `identity_id`, `multiplicity`, `match_existence`, `reverse_multiplicity`, `reverse_match_existence`, `from_description`, `to_description`, `annotation`, `edge_id`. |
| `entity_definition` | `id`, `identity_id`, `dataset_columns`, `entity_universe`, `unique`, `total`, `conforms`, `entity_expression`, `entity_metadata`, `description`, `effective_description`, `description_source`, `unknown_fields`. |

Requesting entity-definition fields also includes the definitions collection. Its identifying
`id`, `identity_id`, and `dataset_columns` are always present; full detail includes every definition
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
| `kind` | Array of `"identity"`, `"dataset"`, `"entity_definition"`, `"entity_relationship"`, `"column"` | Omitted or null searches all kinds; otherwise nonempty. |
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
| `entity_relationship` | `key`, `endpoints`. |
| `identity` | `key`, `name`. |

Groups appear in the order `column`, `dataset`, `entity_definition`, `entity_relationship`,
`identity`. A cross-entity relationship matches by its descriptions.

The match header is `key`, `match_type`, `match_field`, `matched_term`, `matched_value`.
Each matching field value has one match row. A dataset's key is its `node_id`, and an identity's
key is its logical entity ID. Column, entity definition, and cross-entity relationship keys are
their snapshot-local IDs (`C<n>`, `D<n>`, and `X<n>`). These keys do not substitute for dataset IDs.

Search normalizes Unicode, case, camel-case boundaries, punctuation, and whitespace. It
indexes names, IDs, descriptions, synonyms, dataset tags, accessor fields (`kind`, `endpoint`,
and the keys and values of `labels` and `properties`), column metadata, and entity-definition
metadata. Whole-value description placeholders such as `N/A` and `TBD` are not indexed;
returned descriptions remain unchanged.

Match types, strongest first, are `exact`, `prefix`, `phrase`, and `all_words`. Exact and prefix
compare normalized stored terms (whole values and individual words). Phrase and all-words
matching apply only to dataset qualified/display names and logical-entity names: query words
prefix consecutive words or words in any order within one value, respectively. Other fields
match a multi-word query only as a whole-value prefix or exact value. Subjects sort by best
match type, normalized label, then ID ordinal compared numerically for snapshot-local IDs
(or the authored ID for datasets and identities). This ordering does not decide semantic relevance.
The top-level `truncated` is true when any group's limit omitted eligible subjects.

### `graph.get_dataset`

Parameters: required nonempty string `node_id`. Returns one full `Dataset` record with
`snapshot: Snapshot` at the top level. It does not accept `detail`, `fields`, or
`response_format`.

### `graph.get_entity_definitions`

Find datasets containing a primary logical entity, optionally alongside up to four more
logical entities. This is dataset-level co-occurrence: a matching dataset is a candidate
bridge, but the result does not establish row-level value co-occurrence or business meaning.
Use the returned definitions and relationship evidence to assess an analytical question.

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `identity_id` | string, required | Canonical primary logical entity ID. |
| `entity_universe` | Array of `"complete"`, `"partial"`, `"unknown"` | Omitted or null leaves primary definitions unfiltered; otherwise nonempty. Duplicates are removed and values sorted. |
| `target_identity_ids` | string array | `[]`; at most four distinct IDs. Every selected dataset must contain a definition of each target. IDs must be nonempty; duplicates are removed and IDs sorted. |
| `view` | `"auto"`, `"aggregated"`, or `"detailed"` | `"auto"`. |
| `dataset_threshold` | integer | 200; range 1–10000. Applies to distinct filtered datasets. |
| `limit` | integer | 100; range 1–1000 datasets per detailed page. |
| `response_format` | `"table"` or `"records"` | `"table"`. |
| `cursor` | opaque string | Omitted or null starts a selection; if supplied, nonempty and at most 4096 characters. Cannot be used with `view: "aggregated"`. |

The primary `identity_id` is separate from the targets. `entity_universe` filters only its
definitions, before matching datasets and calculating counts. A dataset qualifies when it has
at least one qualifying primary definition and at least one definition of every target. Target
definitions are not filtered by `entity_universe`. Listing the primary again as a target does
not restore primary roles excluded by that filter; it still counts toward the four-target
limit. An unknown primary or target ID returns resource-not-found (`-32004`); invalid filters
return invalid parameters (`-32602`). Known filters with no matching datasets return zero
counts and empty collections.

Both response shapes include the resolved selection:

```text
EntityDefinitionsSelection = {
  snapshot: Snapshot, identity_id: string, name: string,
  description: string, synonyms: string[],
  entity_universe: string[] | null, target_identity_ids: string[],
  limit: integer, dataset_threshold: integer,
  dataset_count: integer, primary_definition_count: integer,
  view: "aggregated" | "detailed"
}
```

`dataset_count` is the exact number of matching distinct datasets.
`primary_definition_count` counts all qualifying primary roles on those datasets, before
detailed paging. Returned filters are canonical: universes and target IDs are sorted and
deduplicated. `view: "auto"` selects `aggregated` only when `dataset_count` exceeds
`dataset_threshold`; equality selects `detailed`. Explicit views override this choice. A
cursor continues detail even if `view` is `auto` and the count exceeds the threshold. Read the
returned `view` before interpreting its collections.

An aggregated response adds:

```text
{
  histogram: Collection<{
    identity_id: string, name: string,
    entity_definition_count: integer, dataset_count: integer
  }>,
  logical_entity_count: integer, truncated: boolean
}
```

The histogram scans every definition on every matching dataset, except the primary entity.
It includes selected non-primary targets and counts separate roles of one entity separately in
`entity_definition_count`; histogram `dataset_count` counts distinct matching datasets
containing that entity. Rows sort by descending definition count, then ascending
`identity_id`. Only the first 20 rows appear. `logical_entity_count` counts all eligible
non-primary entities, and `truncated` means more than 20 groups exist. This response has no
`datasets`, `entity_definitions`, or `next_cursor`.

A detailed response adds `datasets: Collection<Dataset>`,
`entity_definitions: Collection<Definition with node_id>`, `truncated: boolean`, and
`next_cursor: string | null`. Pages contain whole datasets, sorted by `node_id`, with up to
`limit` datasets per page. Each page includes its qualifying primary definitions and every
definition of the selected targets on those datasets. Definitions sort by `node_id`, then
`identity_id`, then `dataset_columns`, and include full metadata, effective descriptions,
and unknown fields. Datasets use standard lookup metadata without navigation-only
`distance`, `edge_count`, or nested edge groups. Detailed pages do not include a histogram.
Here `truncated` means the page omits some matching datasets, including datasets on earlier
pages; it can remain true on the last page. Only `next_cursor: null` marks completion.

To continue, repeat the original primary and target filters, `entity_universe`, `limit`,
`dataset_threshold`, and `response_format` with the returned cursor. The stateless cursor
binds to those values, the method, API version, and snapshot content. Equivalent target and
universe orderings or duplicates are canonicalized. `view` may be `auto` or `detailed` on
continuation; `aggregated` with a cursor is invalid. Do not decode or modify cursors.
Malformed, stale, mismatched, or out-of-range cursors return `-32602`. This method does not
accept navigation `detail` or `fields`.

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
  snapshot: Snapshot, edge_id: string, identity_id: string,
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

### `graph.get_entity_relationships`

A cross-entity relationship states in descriptive text how two registered logical entities
relate in the business, independently of any dataset. Its endpoints are an unordered pair of
logical entity IDs, possibly the same logical entity twice, and it holds one description per way
the two relate, such as "An order is placed on one calendar day." and "An order is shipped on
one calendar day once it ships." It also states one `multiplicity` for the pair, read from its
first endpoint to its second, and one `match_existence` per endpoint: whether every instance of
that logical entity relates to at least one instance of the other. Both cover all descriptions
together; `unknown` is an explicit value. It has no dataset fields. Its claims are stated by the
contributor, never derived from entity definitions, and it never changes a relationship between
entity definitions or its claims.

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `identity_id` | string, required | A registered logical entity; unknown is resource not found. |
| `limit` | integer | 200; range 1–1000 per page. |
| `cursor` | string | Omitted or null starts at the first page; bound to the snapshot and request. |

Returns:

```text
{
  snapshot: Snapshot, identity_id: string, name: string, limit: integer,
  relationship_count: integer,
  entity_relationships: [{
    id: string, identity_id: string, name: string, descriptions: string[],
    multiplicity: string, match_existence: string,
    reverse_match_existence: string, unknown_fields: string[]
  }],
  truncated: boolean, next_cursor: string | null
}
```

Each item gives the cross-entity relationship's `id`, the other logical entity's `identity_id`
and `name`, and the relationship's descriptions. `multiplicity` is read from the requested
logical entity to the other; `match_existence` is for the requested logical entity and
`reverse_match_existence` for the other; `unknown_fields` names which of these three are
`unknown`. For example, from `impression` the pair (`click`, `impression`) stated as `many:1`,
`[always, optional]` reads `1:many`, `optional`, `always`. Items are ordered by the other logical
entity's ID. A relationship of a logical entity with itself appears once, with its claims read
in endpoint order. `relationship_count` counts every cross-entity relationship at the logical entity;
`truncated` reports whether this page omits some, and `next_cursor` is null on the last page.
An empty list means no cross-entity relationship is stated for that logical entity; it does not
mean the data cannot relate it to others.

### `graph.find_entity_relationship_paths`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `from_identity_id` | string, required | Starting logical entity. |
| `to_identity_id` | string, required | Target logical entity; must differ from `from_identity_id`. |
| `max_steps` | integer | 4; range 1–10. |
| `k` | integer | 6; range 1–100 paths. |

Returns:

```text
{
  snapshot: Snapshot, from_identity_id: string, to_identity_id: string,
  max_steps: integer, k: integer, path_count: integer,
  paths: [[{
    from_identity_id: string, to_identity_id: string, descriptions: string[],
    multiplicity: string, match_existence: string,
    reverse_match_existence: string, unknown_fields: string[]
  }]],
  truncated: boolean
}
```

Each path is a travel-ordered array of steps over cross-entity relationships; a step names its
two logical entities in the path's direction and carries the descriptions of their cross-entity
relationship, `multiplicity` in the direction of travel, `match_existence` for the logical entity
at the start of the step, `reverse_match_existence` for the one at its end, and `unknown_fields`
for these claims. Paths never repeat a logical entity and rank by step count, then by the sequence of
logical entity IDs. `path_count` counts returned paths, and `truncated` indicates a further path
or an interrupted search. Equal endpoints are invalid params; an unknown logical entity is
resource not found. Zero paths means no stated path exists within `max_steps`.

The response describes stated knowledge only. Where the data realizes a step is found through
`graph.get_entity_definitions` with the other logical entity as a target, and through
relationships between datasets. A step with no realizing dataset is valid stated knowledge that
the data does not hold.

## Traversal methods

Each method accepts the shared navigation parameters above. `get_edges` can return either its
aggregated shape or `Navigation` with the selection fields below. The other methods return
`Navigation` plus their method-specific fields. Edges are explicit; returning two datasets does
not imply selecting every relationship between them.

### `graph.get_edges`

| Parameter | Type | Default and constraints |
| --- | --- | --- |
| `node_id` | string, required | Starting dataset. |
| `limit` | integer | 200; range 1–1000, applied independently to each source definition on each detailed page. |
| `identity_id` | string | Omitted or null leaves source logical entities unfiltered. |
| `from_dataset_columns` | Nonempty string array | Requires `identity_id`; selects one source definition. |
| `target_identity_ids` | string array | `[]`; connected datasets must contain at least one definition of every listed entity. Duplicate IDs are removed and the list is sorted. |
| `view` | `"auto"`, `"aggregated"`, or `"detailed"` | `"auto"`. |
| `fan_out_threshold` | integer | 200; range 1–10000. |
| `cursor` | opaque string | Omitted or null starts a new selection; if supplied, nonempty and at most 4096 characters. Cannot be used with `view: "aggregated"`. |

`identity_id` and `from_dataset_columns` select the source definitions that establish the
connections. `target_identity_ids` then retains connected datasets containing every requested
logical entity. Target entities need not occur on the source or in a previously returned
histogram. All filters apply before counts, aggregation, view selection, and detailed paging.
An unknown target identity returns resource-not-found (`-32004`); a known target with no
matching connected dataset produces an empty result. A source filter matching no source
definition is invalid parameters (`-32602`).

Fan-out is the number of distinct connected datasets other than the source dataset, even when
several source definitions connect to the same dataset. With `view: "auto"`, `get_edges` returns
`aggregated` only when `fan_out_count` is greater than `fan_out_threshold`; equality returns
`detailed`. Explicit `view` selects that view regardless of the count. A cursor always continues
the detailed view, including when `view` is `auto` and fan-out exceeds the threshold.

Both response shapes include these resolved selection fields:

```text
EdgesSelection = {
  snapshot: Snapshot, node_id: string, limit: integer,
  identity_id: string | null, from_dataset_columns: string[] | null,
  target_identity_ids: string[], fan_out_count: integer,
  fan_out_threshold: integer, view: "aggregated" | "detailed"
}
```

The returned target IDs are sorted and unique. The actual `view` identifies which response
shape to read. An aggregated response has this shape in addition to `EdgesSelection`:

```text
AggregatedEdgesResponse = {
  detail: "essential" | "standard" | "full", fields: {object_name: string[]},
  histogram: Collection<{
    identity_id: string, name: string,
    entity_definition_count: integer, dataset_count: integer
  }>,
  logical_entity_count: integer, truncated: boolean
}
```

The histogram covers all distinct selected connected datasets before detailed pagination. It
excludes the source dataset and counts every entity definition on a connected dataset, including
separate roles of the same entity. `dataset_count` counts distinct connected datasets containing
the entity. Rows sort by descending `entity_definition_count`, then ascending `identity_id`.
Only the first 20 rows appear. `logical_entity_count` counts all groups before that cutoff;
aggregated `truncated` is true only when more than 20 groups exist. The histogram is a discovery
summary, not relationship evidence. This response has no `datasets`, `edge_fields`, or
`next_cursor`.

A detailed response adds `Navigation` and `next_cursor: string | null` to `EdgesSelection`.
It lists outgoing directed edges by logical entity and source definition. Each page includes up
to `limit` eligible edges independently for each source definition, in the existing target
order. A group's `edge_count` counts all its eligible matches, even when the current page lists
none. Group `truncated` is true when any eligible match is omitted from that page, including
matches on earlier pages. Top-level detailed `truncated` is true when any group is truncated,
so it can remain true on the last page. Only `next_cursor: null` means enumeration is complete.
Groups already exhausted can remain with their full count and an empty edge list.

The source dataset has distance 0; other targets listed on the page have distance 1. Eligible
same-dataset relationships remain in detail when the source satisfies the target filters, but
they do not increase fan-out or contribute to the histogram. Detailed edges retain their
source-definition grouping and endpoint claims. Only relationships on the current page are
derived.

To continue, send the returned opaque `next_cursor` with the original `node_id`, source and
target filters, `limit`, `fan_out_threshold`, `detail`, `fields`, and `response_format`. The
cursor is stateless and bound to the snapshot's content, API version, and those request values;
the service keeps no cursor session. `view` may switch between `auto` and `detailed` across
pages. Do not decode or modify the cursor. A malformed, stale, mismatched, or out-of-range
cursor returns invalid parameters (`-32602`).

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
To find datasets that define a primary entity and also contain a selected target, start with
an aggregate summary:

```json
{"identity_id":"ACCOUNT_ID","target_identity_ids":["REGION_ID"],"view":"aggregated"}
```

Use those params with `graph.get_entity_definitions`. For full definitions, call it again
with `view: "detailed"` and, if `next_cursor` is non-null, repeat that detailed request with
the cursor until `next_cursor` is null. Keep the same filters, `limit`,
`dataset_threshold`, and `response_format` across pages.

For edges, inspect `view` in the response. Automatic aggregation is useful when the source has
many connected datasets:

```json
{"node_id":"sqlite:lending.loan","view":"auto","fan_out_threshold":200}
```

To inspect concrete relationships on connected datasets containing both selected logical
entities, keep the same source scope and request detail:

```json
{"node_id":"sqlite:lending.loan","target_identity_ids":["ACCOUNT_ID","REGION_ID"],"view":"detailed","limit":200,"response_format":"records"}
```

If that response has a non-null `next_cursor`, repeat the same parameters with the returned
cursor, until `next_cursor` is null. The ID strings above are illustrative; use registered
logical entity IDs from the served graph. To retain standard claims while adding selected
dataset metadata in a detailed response:

```json
{"node_id":"sqlite:lending.loan","view":"detailed","detail":"standard","response_format":"records","fields":{"dataset":["columns","accessor.properties"]}}
```

For paths restricted to outgoing non-fan-out multiplicities:

```json
{"from_node_id":"sqlite:lending.loan","to_node_id":"sqlite:lending.region","allowed_multiplicities":["1:1","many:1"],"max_edges":4,"limit":6}
```

These dataset IDs are illustrative; they must resolve in the served graph. Choosing a path
still requires checking the meaning of its endpoint columns and intermediate datasets.
