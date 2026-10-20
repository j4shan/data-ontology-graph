# Product requirements: graph model

The graph model states what the published graph knows about business entities, datasets, and the
relationships between them. Clauses 1.1–3.7 and 4.1 moved from
[`functional.md`](functional.md) §3.1–3.4; their former IDs are listed in the last column.

## Entities and identities

| ID | Clause | Former |
| --- | --- | --- |
| 1.1 | A business entity is a concept the business identifies and reasons about with a stable identity. It may be a physical object, party, event, agreement, or a condition or state that matters to the domain at a point in time, such as a planning slot: one item planned at one plant on one calendar day. | 3.1.1 |
| 1.2 | A logical identity names one business identity independently of any physical representation. A global registry gives each a stable `identity_id`, a business name, and an optional description and confirmed synonyms. | 3.1.2 |
| 1.3 | An entity definition is one physical realization of a logical identity in one dataset, identified by `(node_id, identity_id, dataset_columns)` with no separate ID. `dataset_columns` is the complete set of node-local physical columns the definition uses. | 3.1.3 |
| 1.4 | An entity definition may carry one or more unrestricted `entity_expression` labels for the same realization. They are agent-facing text, preserved without parsing, executing, translating, or proving them. | 3.1.4 |
| 1.5 | Entity metadata beside an entity definition holds the context needed to interpret it, including its expression context. | 3.1.5 |
| 1.6 | `entity_universe` belongs to an entity definition and states whether that realization covers the complete entity population (`complete`), part of it (`partial`), or is unassessed (`unknown`). One dataset may hold definitions with different universe status. | 3.1.6 |
| 1.7 | A business entity does not need a dataset holding its complete population. When none does, every definition of that identity may be `partial` or `unknown`. | 3.1.7 |
| 1.8 | An entity definition may use a composite column set whose columns also realize other identities on the same dataset; a column may belong to more than one entity definition. | 3.1.8 |
| 1.9 | A condition, state, or composite logical identity is registered only when the business identifies, compares, reconciles, or tracks records at that key. | 3.1.9 |
| 1.10 | An entity definition may carry a description of what it identifies in its dataset, such as the role the realization plays. Its effective description is that description, or, when there is none and it realizes the identity through a single unmodified column, that column's description. Relationship endpoints are presented with their effective descriptions, so relationships of the same identity remain distinguishable by role. | — |

## Datasets

| ID | Clause | Former |
| --- | --- | --- |
| 2.1 | A dataset is an addressable data resource, not assumed to be a SQL table or tabular storage. Distinct datasets in different access locations never collapse because their display names match. | 3.2.1 |
| 2.2 | A dataset's descriptor holds its fully qualified deployed name, display name, description, synonyms, and tags in dataset terminology. Source-specific terms such as table, catalog, schema, or prefix belong only to the accessor. | 3.2.2 |
| 2.3 | A dataset's accessor is a credential-free recipe an external tool uses to locate the dataset: a provider `schema_id` and the provider-specific properties it validates. The common model prescribes no vendor-specific properties. | 3.2.3 |
| 2.4 | A dataset has exactly one grain: a grain whose components together describe one record boundary, or the explicit value `unknown`. Different record boundaries are different datasets. | 3.2.4 |
| 2.5 | A dataset records its physical columns for identity, grain, search, and relationship context. The graph does not reproduce primary keys, foreign keys, unique constraints, nullability, SQL types, or other source-catalog primitives. | 3.2.5 |

## Relationships

| ID | Clause | Former |
| --- | --- | --- |
| 3.1 | A relationship connects two different registered entity definitions of the same logical identity. One stored relationship represents both directions; a traversal gives it a direction. | 3.3.1 |
| 3.2 | Multiplicity is a directional claim: `1:1`, `1:many`, `many:1`, `many:many`, or `unknown`. From endpoint A to B, uniqueness on both sides gives `1:1`, nonunique A and unique B gives `many:1`, unique A and nonunique B gives `1:many`, and nonunique on both gives `many:many`; unestablished uniqueness gives `unknown`. | 3.3.2 |
| 3.3 | Match existence is a directional claim for each endpoint: `always` means every record there has a match on the other side, `optional` means zero matches are permitted without asserting that an unmatched record was observed, and `unknown` means neither is established. | 3.3.3 |
| 3.4 | Multiplicity and match existence are independent authored claims. A `many:1` link can still be optional from the many side. | 3.3.4 |
| 3.5 | When two datasets record different facts against the same registered identity, their entity definitions connect through an ordinary relationship. Its multiplicity may be `many:many` when both datasets hold several records per key. | 3.3.5 |
| 3.6 | Entity-universe status is reusable context about one entity definition; directional match existence is the relationship-specific evidence for whether an inner join preserves records from that direction. | 3.3.6 |
| 3.7 | An annotation is descriptive sidecar metadata on one relationship: a description and tags. It never creates, approves, rejects, or alters the relationship's structural claims. | 3.3.7 |

## Claims

| ID | Clause | Former |
| --- | --- | --- |
| 4.1 | Unknown is a typed claim value. `grain`, `entity_universe`, `multiplicity`, and `match_existence` state unknown through their own `unknown` value. Descriptive text is free text that may hold any wording and never establishes or negates a typed claim. | 3.4.1 |
