# AKG file format

The [AKG schema](../../../resources/schema/akg.schema.json) is the authority; this page explains
it. One JSON file holds everything that serves one objective: the graph datasets it needs,
keyed by `node_id`; in each dataset, the selected directed edges that leave it, as navigation
responses list them; and the reasoning that goes with them. Connected components are derived
from the directed edges; disconnected components are valid.

Fields come from two writers:

- **graph**: copied from service responses by `scripts/akg.py`. Never edit them by hand; the
  finalize check compares them with the graph.
- **agent**: your reasoning, written with `annotate`, `gap`, and `comparison`.

Unknown keys are allowed anywhere. `check` reports them as `info` and never checks them.

## Document

| Field | Required | Writer | Content |
| --- | --- | --- | --- |
| `format_version` | yes | tool | `2`. A file without it, holding a `relationships` map, is converted with `akg.py migrate`. |
| `status` | yes | tool | `draft`, or `final` after `finalize`. Any `akg.py` write resets it to `draft`. |
| `question` | yes | agent | The question, verbatim (`init --question`). |
| `objective` | no | agent | The reading of the question this file serves (`init --objective`). |
| `graph.snapshot` | no | tool | `version` and `schema_fingerprint`, recorded by `init`. |
| `datasets` | yes | tool | Map from `node_id` to a dataset. May be empty. |
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
| `edges` | graph | — | The selected directed edges leaving this dataset, written by `add-edge`. See below. |

Accessor properties, entity expressions, and entity metadata are never copied. Fetch them with
`graph_call.py get_dataset` when needed.

`usage` on a dataset:

| Field | Content |
| --- | --- |
| `role` | `anchor`, `grouping`, `filter`, or `bridge`. |
| `columns` | Map from a listed column name to `as` (`measure`, `count`, `group`, `filter`, `time`, `absence`, `join_only`, `output`), with optional `value` (a stated filter value or threshold) and `note`. |
| `note` | Free text. |

## Directed edge

A directed edge is a relationship read from the dataset that holds it, which is where traversal
starts. It is identified by `edge_id` and `from_dataset_columns`: a relationship with both ends
on one dataset, such as a link table's two device columns, gives that dataset two directed
edges. A relationship traversed from each end appears once in each end's dataset.

| Field | Writer | Content |
| --- | --- | --- |
| `edge_id` | graph | The relationship's canonical ID. |
| `identity_id` | graph | The logical entity ID both entity definitions share. |
| `from_dataset_columns` | graph | The start entity definition's columns, on this dataset. |
| `to_node_id`, `to_dataset_columns` | graph | The end dataset and the end entity definition's columns. |
| `multiplicity`, `match_existence` | graph | How each start row matches end rows: `1:1`, `1:many`, `many:1`, `many:many`, or `unknown`; and `always`, `optional`, or `unknown`. |
| `reverse_multiplicity`, `reverse_match_existence` | graph | The same claims from the end back to the start. |
| `from_description`, `to_description` | graph | The effective descriptions of the two entity definitions, when there are any. |
| `stats` | graph | Reserved for statistics once the graph serves them. |
| `usage` | agent | See below. |

`usage` on a directed edge:

| Field | Content |
| --- | --- |
| `keep` | The start or end `node_id` whose unmatched rows must stay visible. |
| `aggregate_before_join` | `true` when the end must be aggregated to the start's grain before combining. |
| `note` | Free text, such as the join that `keep` implies. |

## Comparison and gap

| Element | Field | Content |
| --- | --- | --- |
| Comparison | `anchors` | Two or more anchor `node_id` values. |
| | `shared_columns` | `{node_id, column}` pairs the anchors are compared on. |
| | `comparison` | `coverage`, `difference`, or `co_occurrence`. |
| Gap | `description` | What the graph cannot connect or supply. Required. |
| | `datasets` | The `node_id` values involved. |
| | `edges` | The directed edges involved, as `{node_id, edge_id}` with the dataset that holds each. |

## Checks

`data-ontology-graph-akg check FILE` and `finalize FILE` report findings by location, rule, and
severity. Only errors block `finalize`.

| Rule | Severity |
| --- | --- |
| The file does not parse, or a required field is missing or has the wrong type or value | error |
| The file still holds a `relationships` map (`unconverted_relationships`) | error |
| An `edge_id` differs from the canonical ID of the edge's two entity definitions (`edge_key`) | error |
| A dataset holds the same directed edge twice (`duplicate_edge`) | error |
| `keep` names a dataset that is neither the start nor the end (`not_an_endpoint`) | error |
| A reference names a dataset or directed edge missing from the file, including an edge's end dataset (`dangling_reference`) | warning; error at `finalize` |
| A `usage` column or shared column is not listed in the dataset's `columns` (`unlisted_column`) | warning; error at `finalize` |
| An element or graph field does not match the graph (`unknown_element`, `graph_mismatch`) | error; with `--socket` or `--yaml`, always at `finalize` |
| A key the contract does not name (`unknown_key`) | info |

## Example

An illustrative retail domain, abbreviated; the IDs do not exist in any shipped catalog.

```json
{
  "format_version": 2,
  "status": "draft",
  "question": "What is the refund value per selling store, including stores with no refunds?",
  "objective": "Sum refund amounts by the store on the original sale, keeping stores with none.",
  "datasets": {
    "sqlite:shop.fact_refund": {
      "name": "shop.main.fact_refund",
      "source": "sqlite",
      "grain": ["refund_id"],
      "columns": {"refund_amount": {"description": "refunded amount"}, "sale_id": {"description": "the refunded sale"}},
      "usage": {"role": "anchor", "columns": {"refund_amount": {"as": "measure"}}},
      "edges": [
        {
          "edge_id": "sqlite:shop.fact_refund:sale_identity:sale_id__sqlite:shop.fact_sale:sale_identity:sale_id",
          "identity_id": "sale_identity",
          "from_dataset_columns": ["sale_id"],
          "to_node_id": "sqlite:shop.fact_sale",
          "to_dataset_columns": ["sale_id"],
          "multiplicity": "many:1", "match_existence": "always",
          "reverse_multiplicity": "1:many", "reverse_match_existence": "optional",
          "from_description": "the refunded sale", "to_description": "the id of the sale",
          "usage": {"keep": ["sqlite:shop.fact_sale"], "note": "fact_sale LEFT JOIN fact_refund keeps sales with no refund."}
        }
      ]
    },
    "sqlite:shop.fact_sale": {"name": "shop.main.fact_sale", "source": "sqlite", "grain": ["sale_id"], "columns": {"…": {}}, "usage": {"role": "bridge"},
      "edges": [{"edge_id": "sqlite:shop.dim_store:store_identity:store_id__sqlite:shop.fact_sale:store_identity:store_id", "…": "…", "usage": {"keep": ["sqlite:shop.dim_store"]}}]},
    "sqlite:shop.dim_store": {"name": "shop.main.dim_store", "source": "sqlite", "grain": ["store_id"], "columns": {"…": {}}, "usage": {"role": "grouping", "columns": {"store_name": {"as": "group"}}}}
  },
  "gaps": {
    "store-match": {"description": "Whether every sale matches a store is unknown.", "datasets": ["sqlite:shop.fact_sale", "sqlite:shop.dim_store"]}
  }
}
```

## Human-readable copy

`data-ontology-graph-akg export FILE --format markdown` writes a deterministic, read-only copy
for review: a dataset table with short aliases, the columns and their usage, each directed edge
from the dataset that holds it with its claims in plain sentences, comparisons, and gaps. For
the first directed edge above:

```markdown
### fact_refund.sale_id → fact_sale.sale_id

- Every fact_refund row matches exactly one fact_sale row.
- Each fact_sale row matches any number of fact_refund rows; some match none.
- Keep unmatched rows of: fact_sale
- Note: fact_sale LEFT JOIN fact_refund keeps sales with no refund.
```

The export is never read back; the JSON file stays the only source of truth.
