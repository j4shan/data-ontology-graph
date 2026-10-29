# AKG format

The bundled [JSON Schema](akg.schema.json) defines the AKG contract. An AKG selects graph
datasets and directed relationships for one analytical objective. It may be disconnected.
The service currently supplies no statistics.

## Document

Required fields are `status` (`"draft"` or `"final"`), `question`,
`edge_fields`, and `datasets`. Optional fields are `objective`, `graph`, `comparisons`, and
`gaps`. Use `draft` while constructing the file. Only graph-aware validation establishes
`final`; schema validation alone does not check graph facts or analytical sufficiency.

The AKG has no format version; its schema follows the graph API version.
`graph.snapshot`, when recorded, holds the service's `api_version` and `version` as returned
by `graph.snapshot_info`.
The snapshot block is optional; its schema requires nonempty strings for both fields.

## Selected graph knowledge

Each dataset record requires `node_id`, `qualified_name`, and `accessor.schema_id`.
Optional graph fields include `accessor.properties`, `grain`, `descriptor`, `unknown_fields`,
`columns`, and `entity_definitions`. Copy their values from API responses, keeping the columns
and properties relevant to the objective. Omit response-only `distance`, `edge_count`, and
entity-definition navigation counts and truncation flags.

Selected directed edges belong to the dataset they leave, inside its `edge_groups`:

```text
datasets[]
  edge_groups[]
    identity_id
    entity_definitions[]
      dataset_columns
      edges[]
      usage: {edge_id: edge reasoning}
```

Each `edges` entry is an array at the standard positions named by the document's `edge_fields`:

```json
["edge", "multiplicity", "match_existence", "reverse_multiplicity", "reverse_match_existence", "from_description", "to_description", "edge_id"]
```

Use the response's `edge_fields` header to select those positions. A path response also has
`identity_id` in each edge array; move it to the containing edge group. Full responses may
include `annotation`, which is outside the standard AKG edge positions. Decode table responses
into records using their headers. These structural conversions preserve the selected values.
An essential-detail edge lacks standard fields; obtain them before including it.

Keep both endpoint datasets for every selected edge. Preserve the returned `edge_id`, edge
label, and claims exactly; never invent relationships to connect selected datasets.

## Analytical reasoning

Put reasoning in dataset `usage`, edge-definition `usage`, `comparisons`, and `gaps`:

- Dataset `usage`: optional `role` (`anchor`, `grouping`, `filter`, `bridge`), `note`, and
  `columns`. Each column usage has `as` (`measure`, `count`, `group`, `filter`, `time`,
  `absence`, `join_only`, `output`) and optional `value` and `note`.
- Edge-definition `usage`: keyed by a selected `edge_id`, with optional `keep` (endpoint
  dataset IDs whose unmatched rows should survive), `aggregate_before_join`, and `note`.
- `comparisons`: keyed by an agent-chosen ID. Each comparison has at least two `anchors`,
  nonempty `shared_columns` (`node_id`, `column`), and `comparison` (`coverage`, `difference`,
  `co_occurrence`).
- `gaps`: keyed by an agent-chosen ID. Each gap requires `description` and may name `datasets`
  and selected directed `edges` (`node_id`, `edge_id`).

Unknown keys are permitted by the schema. They do not authorize changing graph facts.
For a dataset-only selection, `edge_groups` may be absent; keep the document's `edge_fields`.
