# AKG document format (version 1.0)

The [AKG schema](../../../resources/schema/akg.schema.json) is the authority; this page explains
it. One document answers one question. Write it as JSON, which is valid YAML, so `cut` output
pastes in unchanged; the example below uses YAML only for readability.

An AKG is a forest of graph cuts. A cut uses the graph's own node and edge model: its `nodes`,
`edges`, and `logical_identities` follow the definitions in
[`intermediary.schema.json`](../../../resources/schema/intermediary.schema.json), and every value
must equal the served snapshot's. The AKG format adds only the envelope and the reasoning.

## Envelope

| Field | Required | Content |
| --- | --- | --- |
| `akg_version` | yes | `"1.0"` |
| `question` | yes | The question text, verbatim. |
| `snapshot` | yes | `version` and `schema_fingerprint` from `snapshot_info`. |
| `akgs` | yes | One AKG per reading of the question, preferred reading first. |

## AKG

| Field | Required | Content |
| --- | --- | --- |
| `interpretation` | yes | The reading of the question this AKG answers, in one or two sentences. |
| `cuts` | yes | One or more graph cuts. |
| `reasoning` | no | Query reasoning; it never adds a node or edge. |

## Cut

Produce each cut with `scripts/graph_call.py cut` and paste it unchanged.

| Field | Required | Content |
| --- | --- | --- |
| `nodes` | yes | Whole dataset nodes, as the snapshot holds them. |
| `edges` | no | The selected relationships, each with `endpoint_a`, `endpoint_b`, `a_to_b`, and `b_to_a`. Endpoint order may be either way round, as long as the claims move with their endpoints. |
| `logical_identities` | when edges exist | Registry entries keyed by `identity_id`. Every identity an edge uses is required; other identities of the cut's entity definitions may be listed. `cut` lists exactly the edge identities. |

The validator enforces the forest shape:

- every edge endpoint is a node in the same cut;
- each cut is connected through its own edges, so a lone dataset is its own cut;
- no node appears in two cuts of one AKG.

## Reasoning

Datasets are named by `node_id`; columns by `node_id` and `column`. Every node and column named
here must be in a cut.

| Field | Content |
| --- | --- |
| `anchors` | Datasets whose grain carries a measure. |
| `attributes` | `node_id`, `column`, `usage`, and optional `value` and `note`. `usage` is `measure`, `count`, `group`, `filter`, `time`, `absence`, `join_only`, or `output`. |
| `traversals` | `origin` and `target` entity-definition references of one selected edge, from the anchor side, with optional `aggregate_before_join` and `note`. |
| `drill_across` | `anchors` (two or more), `shared_columns`, and `comparison` (`coverage`, `difference`, or `co_occurrence`). |
| `data_gaps` | `description`, and the `cuts` (zero-based indices) and `node_ids` involved. |

## Example (illustrative domain)

Nodes are abbreviated here; a real document holds each node exactly as `cut` prints it.

```yaml
akg_version: "1.0"
question: What is the refund value per selling store, and which stores have no refunds?
snapshot: {version: "5.0", schema_fingerprint: "0000000000000000"}
akgs:
  - interpretation: Sum refund amounts by the store on the original sale, keeping stores with none.
    cuts:
      - logical_identities:
          sale_identity: {name: Sale identity, description: "", synonyms: []}
          store_identity: {name: Store identity, description: "", synonyms: []}
        nodes:
          - node_id: sqlite:shop.fact_refund      # whole node, copied by `cut`
          - node_id: sqlite:shop.fact_sale
          - node_id: sqlite:shop.dim_store
        edges:
          - endpoint_a: {node_id: sqlite:shop.fact_refund, identity_id: sale_identity, dataset_columns: [sale_id]}
            endpoint_b: {node_id: sqlite:shop.fact_sale, identity_id: sale_identity, dataset_columns: [sale_id]}
            a_to_b: {multiplicity: "many:1", match_existence: always}
            b_to_a: {multiplicity: "1:many", match_existence: optional}
          - endpoint_a: {node_id: sqlite:shop.dim_store, identity_id: store_identity, dataset_columns: [store_id]}
            endpoint_b: {node_id: sqlite:shop.fact_sale, identity_id: store_identity, dataset_columns: [store_id]}
            a_to_b: {multiplicity: "1:many", match_existence: optional}
            b_to_a: {multiplicity: "many:1", match_existence: always}
    reasoning:
      anchors: [sqlite:shop.fact_refund]
      attributes:
        - {node_id: sqlite:shop.fact_refund, column: refund_amount, usage: measure}
        - {node_id: sqlite:shop.dim_store, column: store_name, usage: group}
      traversals:
        - origin: {node_id: sqlite:shop.fact_refund, identity_id: sale_identity, dataset_columns: [sale_id]}
          target: {node_id: sqlite:shop.fact_sale, identity_id: sale_identity, dataset_columns: [sale_id]}
        - origin: {node_id: sqlite:shop.fact_sale, identity_id: store_identity, dataset_columns: [store_id]}
          target: {node_id: sqlite:shop.dim_store, identity_id: store_identity, dataset_columns: [store_id]}
          note: Stores without refunds stay visible from the store side (1:many optional).
      data_gaps: []
```

When the question asks for unrelated facts, or the graph cannot connect two datasets, list each
part as its own cut. When the cause is missing knowledge, add a data gap:

```yaml
    cuts:
      - nodes: [ ... loan ... ]
      - nodes: [ ... region ... ]
    reasoning:
      data_gaps:
        - description: >-
            No relationship records the region where a loan was disbursed; the account's
            opening-branch region is a different role.
          cuts: [0, 1]
```
