<!-- Generated format reference for a DDL collector survey. -->
# Preparation survey: example, round 1

2 decision(s) need an answer. Edit only the `answer` blocks, then run `ddl-collector apply`.

- `status`: `answered`, `unknown`, `waived`, or `blocking`. Leave `open` to defer.
- `value`: overrides of the proposal. `{}` accepts the proposal as written.
- `rationale`: why, or where the answer comes from.

Grain decisions come first, because relationship decisions depend on the identities they confirm.

## grain.orders

| Field | Value |
| --- | --- |
| Affected | `nodes[sqlite:example.orders].grain` |
| Required | yes |
| Topic | grain |

**Question.** Do columns `order_id` identify one record of `orders`, and does that key realize the business identity `orders_identity`? Override `identity_id` or `identity_name` to reuse or rename an identity, set `identity_id: null` for a record boundary that is not an identity, and set `entity_universe` to `complete` only if this dataset holds the whole population of that identity.

**Evidence.**

- S: declared primary key `order_id`
- S: dev_databases/example/example.sqlite PRAGMA table_info(orders).pk

**Proposal.**

```yaml
columns:
- order_id
identity_id: orders_identity
identity_name: Orders identity
entity_universe: unknown
```

```answer
status: open
value: {}
rationale: ''
```

## relationship.order_items.order_id.orders

| Field | Value |
| --- | --- |
| Affected | `edges[sqlite:example.order_items -> sqlite:example.orders]` |
| Required | no |
| Topic | relationship |

**Question.** Does `order_items` (`order_id`) identify the same business entity as `orders` (`order_id`)? The proposed claims come from the current data, which shows what is true now, not what is guaranteed. Keep `always` only where the rule holds by design; set `include: false` to drop the relationship. Direction `a_to_b` reads from the referencing dataset.

**Evidence.**

- S: declared foreign key `order_items` (`order_id`) -> `orders` (`order_id`)
- S: dev_databases/example/example.sqlite PRAGMA foreign_key_list(order_items) id=0

**Proposal.**

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

```answer
status: open
value: {}
rationale: ''
```
