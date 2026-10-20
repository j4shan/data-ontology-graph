# AKG file format

The [AKG schema](../../../resources/schema/akg.schema.json) is the authority; this page explains
it. One JSON file holds everything that serves one objective: the graph datasets and
relationships it needs, keyed by their graph IDs, and the reasoning that goes with them.
Connected components are derived from the relationships; disconnected components are valid.

Fields come from two writers:

- **graph**: copied from service responses by `scripts/akg.py`. Never edit them by hand; the
  finalize check compares them with the graph.
- **agent**: your reasoning, written with `annotate`, `gap`, and `comparison`.

Unknown keys are allowed anywhere. `check` reports them as `info` and never checks them.

## Document

| Field | Required | Writer | Content |
| --- | --- | --- | --- |
| `status` | yes | tool | `draft`, or `final` after `finalize`. Any `akg.py` write resets it to `draft`. |
| `question` | yes | agent | The question, verbatim (`init --question`). |
| `objective` | no | agent | The reading of the question this file serves (`init --objective`). |
| `graph.snapshot` | no | tool | `version` and `schema_fingerprint`, recorded by `init`. |
| `datasets` | yes | tool | Map from `node_id` to a dataset. May be empty. |
| `relationships` | yes | tool | Map from canonical `edge_id` to a relationship. May be empty. |
| `comparisons` | no | agent | Map from an ID you choose to a comparison. |
| `gaps` | no | agent | Map from an ID you choose to a data gap. |

## Dataset

| Field | Writer | Detail | Content |
| --- | --- | --- | --- |
| `name` | graph | all | The qualified name, such as `shop.main.fact_sale`. Required. |
| `source` | graph | all | The data system family, such as `sqlite`. Required. |
| `grain` | graph | all | The grain columns as one list, or `"unknown"`. |
| `columns` | graph | `essential`: named with `--columns`; `standard`, `full`: all | Map from column name to `description` and `value_description`; `full` adds `synonyms`. |
| `description` | graph | `standard`, `full` | The dataset description. |
| `entity_definitions` | graph | `standard`, `full` | `identity_id`, `dataset_columns`, `entity_universe`, and, when there is one, the effective `description` with its `description_source`: `entity` when the maintainer wrote it, `column` when it comes from the definition's single unmodified column. |
| `synonyms`, `tags` | graph | `full` | Dataset synonyms and tags. |
| `stats` | graph | — | Reserved for statistics once the graph serves them. |
| `usage` | agent | — | See below. |

Accessor properties, entity expressions, and entity metadata are never copied. Fetch them with
`graph_call.py get_dataset` when needed.

`usage` on a dataset:

| Field | Content |
| --- | --- |
| `role` | `anchor`, `grouping`, `filter`, or `bridge`. |
| `columns` | Map from a listed column name to `as` (`measure`, `count`, `group`, `filter`, `time`, `absence`, `join_only`, `output`), with optional `value` (a stated filter value or threshold) and `note`. |
| `note` | Free text. |

## Relationship

| Field | Writer | Content |
| --- | --- | --- |
| `endpoint_a`, `endpoint_b` | graph | `node_id`, `identity_id`, `dataset_columns`, in canonical order. |
| `a_to_b`, `b_to_a` | graph | `multiplicity` (`1:1`, `1:many`, `many:1`, `many:many`, `unknown`) and `match_existence` (`always`, `optional`, `unknown`) for each direction. |
| `stats` | graph | Reserved for statistics once the graph serves them. |
| `usage` | agent | See below. |

`a_to_b` describes how each `endpoint_a` row matches `endpoint_b` rows. Canonical order is not
traversal order: record the direction you traverse with `usage.from` and leave the claims as
they are.

`usage` on a relationship:

| Field | Content |
| --- | --- |
| `from` | The endpoint `node_id` the traversal starts from, normally the anchor side. |
| `keep` | Endpoint `node_id` values whose unmatched rows must stay visible. |
| `aggregate_before_join` | `true` when the far side must be aggregated to the `from` side's grain before combining. |
| `note` | Free text, such as the join that `keep` implies. |

## Comparison and gap

| Element | Field | Content |
| --- | --- | --- |
| Comparison | `anchors` | Two or more anchor `node_id` values. |
| | `shared_columns` | `{node_id, column}` pairs the anchors are compared on. |
| | `comparison` | `coverage`, `difference`, or `co_occurrence`. |
| Gap | `description` | What the graph cannot connect or supply. Required. |
| | `datasets`, `relationships` | The `node_id` and `edge_id` values involved. |

## Checks

`data-ontology-graph-akg check FILE` and `finalize FILE` report findings by location, rule, and
severity. Only errors block `finalize`.

| Rule | Severity |
| --- | --- |
| The file does not parse, or a required field is missing or has the wrong type or value | error |
| A relationship key differs from the canonical ID of its endpoints (`relationship_key`) | error |
| `usage.from` or `keep` names a dataset that is not an endpoint (`not_an_endpoint`) | error |
| A reference names a dataset or relationship missing from the file (`dangling_reference`) | warning; error at `finalize` |
| A `usage` column or shared column is not listed in the dataset's `columns` (`unlisted_column`) | warning; error at `finalize` |
| An element or graph field does not match the graph (`unknown_element`, `graph_mismatch`) | error; with `--socket` or `--yaml`, always at `finalize` |
| A key the contract does not name (`unknown_key`) | info |

## Example

An illustrative retail domain, abbreviated; the IDs do not exist in any shipped catalog.

```json
{
  "status": "draft",
  "question": "What is the refund value per selling store, including stores with no refunds?",
  "objective": "Sum refund amounts by the store on the original sale, keeping stores with none.",
  "datasets": {
    "sqlite:shop.fact_refund": {
      "name": "shop.main.fact_refund",
      "source": "sqlite",
      "grain": ["refund_id"],
      "columns": {"refund_amount": {"description": "refunded amount"}, "sale_id": {"description": "the refunded sale"}},
      "usage": {"role": "anchor", "columns": {"refund_amount": {"as": "measure"}}}
    },
    "sqlite:shop.fact_sale": {"name": "shop.main.fact_sale", "source": "sqlite", "grain": ["sale_id"], "columns": {"…": {}}, "usage": {"role": "bridge"}},
    "sqlite:shop.dim_store": {"name": "shop.main.dim_store", "source": "sqlite", "grain": ["store_id"], "columns": {"…": {}}, "usage": {"role": "grouping", "columns": {"store_name": {"as": "group"}}}}
  },
  "relationships": {
    "sqlite:shop.fact_refund:sale_identity:sale_id__sqlite:shop.fact_sale:sale_identity:sale_id": {
      "endpoint_a": {"node_id": "sqlite:shop.fact_refund", "identity_id": "sale_identity", "dataset_columns": ["sale_id"]},
      "endpoint_b": {"node_id": "sqlite:shop.fact_sale", "identity_id": "sale_identity", "dataset_columns": ["sale_id"]},
      "a_to_b": {"multiplicity": "many:1", "match_existence": "always"},
      "b_to_a": {"multiplicity": "1:many", "match_existence": "optional"},
      "usage": {"from": "sqlite:shop.fact_refund", "keep": ["sqlite:shop.fact_sale"], "note": "fact_sale LEFT JOIN fact_refund keeps sales with no refund."}
    },
    "sqlite:shop.dim_store:store_identity:store_id__sqlite:shop.fact_sale:store_identity:store_id": {"…": "…", "usage": {"from": "sqlite:shop.fact_sale", "keep": ["sqlite:shop.dim_store"]}}
  },
  "gaps": {
    "store-match": {"description": "Whether every sale matches a store is unknown.", "datasets": ["sqlite:shop.fact_sale", "sqlite:shop.dim_store"]}
  }
}
```

## Human-readable copy

`data-ontology-graph-akg export FILE --format markdown` writes a deterministic, read-only copy
for review: a dataset table with short aliases, the columns and their usage, each relationship
oriented by `usage.from` with its claims in plain sentences, comparisons, and gaps. For the
first relationship above:

```markdown
### fact_refund.sale_id → fact_sale.sale_id

- Every fact_refund row matches exactly one fact_sale row.
- Each fact_sale row matches any number of fact_refund rows; some match none.
- Keep unmatched rows of: fact_sale
- Note: fact_sale LEFT JOIN fact_refund keeps sales with no refund.
```

The export is never read back; the JSON file stays the only source of truth.
