# Product requirements: graph model

The graph model states what the published graph knows about business entities, datasets, and the
relationships between them. Clauses that moved from [`functional.md`](functional.md) §3.1–3.4
list their former IDs in the last column.

## Purpose

| ID | Clause | Former |
| --- | --- | --- |
| 0.1 | The graph model reduces ambiguity for an AI agent: the agent finds the relevant datasets, logical entities, and relationships faster and parses fewer irrelevant signals. The model does not enforce the strict alignment that SQL equality needs, such as identical value encodings or column-by-column key correspondence. | — |

## Business and logical entities

| ID | Clause | Former |
| --- | --- | --- |
| 1.1 | A business entity is a concept the business identifies and reasons about with a stable identity. It may be a physical object, party, event, agreement, or a condition or state that matters to the domain at a point in time, such as a planning slot: one item planned at one plant on one calendar day. | 3.1.1 |
| 1.2 | A logical entity names one business entity independently of any physical representation. A global registry gives each a stable logical entity ID (`identity_id`), a business name, and an optional description and confirmed synonyms. | 3.1.2 |
| 1.3 | A condition, state, or composite logical entity is registered only when the business identifies, compares, reconciles, or tracks records at that key. | 3.1.9 |

## Entity definitions

| ID | Clause | Former |
| --- | --- | --- |
| 1.4 | An entity definition is one physical realization of a logical entity in one dataset, identified by `(node_id, identity_id, dataset_columns)` with no separate ID. One dataset may hold several definitions of the same logical entity with different column sets, such as a source and a target role. Its fields are defined in clauses 1.5–1.13. | 3.1.3 |
| 1.5 | `identity_id`, the logical entity ID, names the registered logical entity the definition realizes. Every two definitions of one logical entity are related (3.1), so choosing the logical entity is how a contributor connects a dataset to knowledge outside their own domain. Values that cannot be compared directly, such as an old and a new customer numbering, belong to different logical entities; data owners maintain those boundaries. | — |
| 1.6 | `dataset_columns` is the complete, nonempty set of node-local physical columns the definition uses, held as a set without order. When the definition has no `entity_expression`, the logical entity is identified by the combination of its columns. It may be composite, and its columns may also belong to other definitions on the same dataset. It does not state which of its columns corresponds to which column of another dataset's definition. | 3.1.3, 3.1.8 |
| 1.7 | `entity_expression` holds zero or more unrestricted labels for the same realization. They are agent-facing text, preserved without parsing, executing, translating, or proving them. | 3.1.4 |
| 1.8 | `entity_metadata` holds the context needed to interpret the definition, including its expression context. | 3.1.5 |
| 1.9 | `description` says what the definition identifies in its dataset, such as the role the realization plays. The definition's effective description is that description, or, when there is none and it realizes the logical entity through a single unmodified column, that column's description. Relationship endpoints are presented with their effective descriptions, so relationships of the same logical entity remain distinguishable by role. | — |
| 1.10 | `entity_universe` states whether the definition's key values cover the logical entity's complete population (`complete`), part of it (`partial`), or is unassessed (`unknown`). One dataset may hold definitions with different universe status. A business entity need not have a complete definition; when none exists, every definition of the logical entity may be `partial` or `unknown`. All `complete` definitions of one logical entity hold the same key values, and evidence showing otherwise is a conflict. | 3.1.6, 3.1.7 |
| 1.11 | `unique` states whether an instance of the logical entity appears in at most one record of the dataset (`true`), may appear in several (`false`), or is unassessed (`unknown`). A record with a null key holds no instance and does not count. Value comparison details, such as case sensitivity and normalization, are external context that the user manages. Relationship multiplicity derives from it (3.2). | — |
| 1.12 | `total` states whether every record of the dataset has a non-null key (`true`), some records have a null key (`false`), or is unassessed (`unknown`). A record with a null key matches nothing, so relationship match existence derives from it (3.3). | — |
| 1.13 | `conforms` states whether every non-null key value belongs to the logical entity's population, with no orphan values (`true`), some values do not (`false`, which marks bad-quality data), or is unassessed (`unknown`). A `complete` definition conforms by definition. Relationship match existence derives from it (3.3). | — |

## Datasets

| ID | Clause | Former |
| --- | --- | --- |
| 2.1 | A dataset is an addressable data resource, not assumed to be a SQL table or tabular storage. Distinct datasets in different access locations never collapse because their display names match. | 3.2.1 |
| 2.2 | A dataset's descriptor holds its fully qualified deployed name, display name, description, synonyms, and tags in dataset terminology. Source-specific terms such as table, catalog, schema, or prefix belong only to the accessor. | 3.2.2 |
| 2.3 | A dataset's accessor is a credential-free recipe an external tool uses to locate the dataset: a provider `schema_id` and the provider-specific properties it validates. The common model prescribes no vendor-specific properties. | 3.2.3 |
| 2.4 | A dataset has exactly one grain: a grain whose components together describe one record boundary, or the explicit value `unknown`. Different record boundaries are different datasets. | 3.2.4 |
| 2.5 | A dataset records its physical columns for entity definitions, grain, search, and relationship context. The graph does not reproduce primary keys, foreign keys, unique constraints, nullability, SQL types, or other source-catalog primitives. | 3.2.5 |

## Relationships

| ID | Clause | Former |
| --- | --- | --- |
| 3.1 | A relationship connects two different entity definitions of the same logical entity, on different datasets or, as a self-join, on the same dataset. The graph build derives a relationship for every such pair; contributors do not author them. One relationship represents both directions; a traversal gives it a direction. | 3.3.1 |
| 3.2 | Multiplicity is a directional claim derived from both endpoints' `unique` (1.11): `1:1`, `1:many`, `many:1`, `many:many`, or `unknown`. From endpoint A to B, unique on both sides gives `1:1`, nonunique A and unique B gives `many:1`, unique A and nonunique B gives `1:many`, and nonunique on both gives `many:many`; `unknown` on either side gives `unknown`. | 3.3.2 |
| 3.3 | Match existence is a directional claim for each endpoint: `always` means every record there has a match on the other side, `optional` means zero matches are permitted without asserting that an unmatched record was observed, and `unknown` means neither is established. From A to B it is `always` when A is `total` and A's key values are contained in B's, `optional` when A is not `total` or its values are not contained in B's, and otherwise `unknown`. A's values are contained in B's when A `conforms` and B is `complete`, and are not when A is `complete` and B is `partial`; otherwise containment comes from relationship evidence (3.6) or is unknown. | 3.3.3 |
| 3.4 | Multiplicity and match existence are independent claims. A `many:1` link can still be optional from the many side. | 3.3.4 |
| 3.5 | When two datasets record different facts against the same registered logical entity, their entity definitions connect through an ordinary relationship. Its multiplicity may be `many:many` when both datasets hold several records per key. | 3.3.5 |
| 3.6 | Relationship evidence about whether one endpoint's key values are contained in the other's is optional. It is recorded only for the few relationships whose endpoint definitions do not settle containment, such as two `partial` definitions; most relationships have none. | 3.3.6 |
| 3.7 | An annotation is descriptive sidecar metadata on one relationship: a description and tags. It never creates, approves, rejects, or alters the relationship's structural claims. | 3.3.7 |
| 3.8 | A directed edge is a relationship traversed from one of its endpoints and carries the relationship's claims in that direction. A relationship with both endpoints on the same dataset yields two directed edges from that dataset, one from each endpoint. | — |

## Claims

| ID | Clause | Former |
| --- | --- | --- |
| 4.1 | Unknown is a typed claim value. `grain`, `entity_universe`, `unique`, `total`, `conforms`, `multiplicity`, and `match_existence` state unknown through their own `unknown` value. Descriptive text is free text that may hold any wording and never establishes or negates a typed claim. | 3.4.1 |
