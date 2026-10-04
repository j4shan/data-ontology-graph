<!-- Generated format reference for a DDL collector decision log. -->
# Decision log: example

2 decisions (answered 2).

## grain.orders

| Field | Value |
| --- | --- |
| Status | answered |
| Affected | `nodes[sqlite:example.orders].grain` |
| Required | yes |
| Answered in round | 1 |

**Question.** Do columns `order_id` identify one record of `orders`, and does that key realize the business identity `orders_identity`? Override `identity_id` or `identity_name` to reuse or rename an identity, set `identity_id: null` for a record boundary that is not an identity, and set `entity_universe` to `complete` only if this dataset holds the whole population of that identity.

**Evidence.**

- S: declared primary key `order_id`
- S: dev_databases/example/example.sqlite PRAGMA table_info(orders).pk

**Resolved value.**

```yaml
columns:
- order_id
identity_id: orders_identity
identity_name: Orders identity
entity_universe: unknown
```

**Rationale.** Confirmed by the schema owner.

## relationship.order_items.order_id.orders

| Field | Value |
| --- | --- |
| Status | answered |
| Affected | `edges[sqlite:example.order_items -> sqlite:example.orders]` |
| Required | no |
| Answered in round | 1 |

**Question.** Does `order_items` (`order_id`) identify the same business entity as `orders` (`order_id`)? The proposed claims come from the current data, which shows what is true now, not what is guaranteed. Keep `always` only where the rule holds by design; set `include: false` to drop the relationship. Direction `a_to_b` reads from the referencing dataset.

**Evidence.**

- S: declared foreign key `order_items` (`order_id`) -> `orders` (`order_id`)
- S: dev_databases/example/example.sqlite PRAGMA foreign_key_list(order_items) id=0

**Resolved value.**

```yaml
include: true
entity_universe: unknown
a_to_b:
  multiplicity: unknown
  match_existence: unknown
b_to_a:
  multiplicity: unknown
  match_existence: unknown
```

**Rationale.** Confirmed by the schema owner.
