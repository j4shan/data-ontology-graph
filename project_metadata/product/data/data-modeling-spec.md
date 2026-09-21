# Data Modeling Spec: Initial-Release Adoption Boundary

This spec defines the entity and relationship concepts adopted for the initial release. A dataset is an addressable data resource and is not assumed to be a SQL table or even tabular storage. Source-specific definitions are normalized before graph construction.

The initial release persists and serves **entity and relationship** knowledge in a local offline copy. Source-specific data definitions are normalized into a YAML intermediary before graph construction. The builder consumes that intermediary and does not require a SQL catalog mental model. The reasoning agent assembles an AKG from coordinated local tool responses. Data statistics remain deferred under the [project PRD](../backend/project-prd.md).

## 1. Adopted modeling concepts

| Concept | Initial-release boundary |
| --- | --- |
| Business entity and entity definitions | Identify a business entity through a global logical identity and register each node-scoped entity definition across datasets. Preserve each definition's dataset-column set and node location. |
| Universal definition intermediary | Express datasets, logical identities, physical identity forms, and relationship properties in source-independent YAML consumed by the builder. |
| Grain and identity | Record what one row represents and which registered logical identities occur in the dataset. Do not infer identity from a column name alone. |
| Relationship structure | Connect registered node entity definitions of the same logical identity and persist directional multiplicity and whether a matching row always exists, may be absent, or is unknown. |

## 2. Dataset node contract

| ID | Requirement |
| --- | --- |
| 2.1.1 | Each node has a stable `node_id` and represents one addressable dataset. Distinct datasets in different access locations must not collapse merely because their display names match. |
| 2.1.9 | A node carries one `descriptor` containing its fully qualified dataset name, display name, description, synonyms, and tags. Dataset terminology is used in the universal model; source-specific terms such as table, catalog, schema, or prefix remain accessor properties. |
| 2.1.10 | A node carries one generic `accessor` envelope with a non-empty `schema_id` and a JSON `properties` object. The common model does not prescribe vendor-specific accessor properties. |
| 2.1.11 | During deserialization, a known accessor `schema_id` selects its subtype validator. The validated properties remain available as the original JSON object so an agent can interpret the provider-specific combination. |
| 2.1.12 | A node records only the relevant dataset columns needed for entity, grain, search, and relationship context. The canonical graph does not reproduce primary keys, foreign keys, unique constraints, nullability, SQL types, or other source-catalog primitives. |
| 2.1.13 | A node has zero or one `grain`. One grain may contain multiple components that collectively state what one dataset record represents. Absence means unknown or unassessed; different record boundaries are represented as different dataset nodes. |
| 2.1.14 | A node carries its registered `entity_definition` records. Each definition may carry one or more unrestricted `entity_expression` labels and entity metadata. |

## 3. Logical identity registry and YAML intermediary

| ID | Requirement |
| --- | --- |
| 3.1.1 | A global logical identity registry assigns a stable `identity_id` and business meaning to each identity that may occur across datasets and systems. |
| 3.1.2 | A node-scoped `entity_definition` identifies one physical realization of a logical identity by the compound key `(node_id, identity_id, dataset_columns)`. A separate entity-definition ID is not required. |
| 3.1.3 | `dataset_columns` is the complete set of node-local physical columns used by the definition. In source-controlled YAML it is a non-empty, duplicate-free list in ascending exact-name order, and every member must exist in the node's column inventory. |
| 3.1.4 | `entity_expression` is an unrestricted agent-facing text label for the physical realization. The field is a list and may contain more than one redundant label for the same compound key. The builder preserves the labels without parsing, executing, translating, or proving them. |
| 3.1.5 | Expression context belongs to entity metadata beside the entity definition. A canonical edge references that definition and does not duplicate its context. |
| 3.1.6 | The registry supports search by logical identity, business name, dataset, system, dataset-column set, and node entity metadata so an agent can locate every registered realization of an identity. |
| 3.1.7 | Complete dataset node definitions, relationship edge definitions, and the global logical identity registry are supplied through one source-independent YAML intermediary. |
| 3.1.8 | The YAML definitions and their machine-readable schema are source-controlled source-of-truth artifacts. A schema change and the definitions that depend on it remain reviewable and reproducible together. |
| 3.1.9 | A schema validator gates ingestion before graph construction. A definition that violates the source-controlled schema is rejected with findings that identify the invalid location and rule. |
| 3.1.10 | The builder receives one complete YAML artifact. It does not apply overlays, override pre-existing DDL metadata, or merge layered metadata sources. |
| 3.1.11 | `is_entity_universe` belongs to an entity definition, not its dataset node. It states whether that particular logical identity realization represents the complete entity population described by the authored knowledge. |

The following illustrative intermediary shows two node entity definitions for one logical identity and an explicit edge between them. The example omits unrelated node properties for brevity.

```yaml
schema_version: "2"

logical_identities:
  customer_identity:
    name: Customer identity

nodes:
  - node_id: table_a
    descriptor:
      qualified_name: main.example.table_a
      display_name: Dataset A
    accessor:
      schema_id: accessor.databricks-unity.v1
      properties:
        workspace_host: databricks.example
        catalog: main
        schema: example
        object: table_a
    columns:
      - name: c1
      - name: c2
      - name: c3
    entity_definitions:
      - identity_id: customer_identity
        dataset_columns: [c1, c2, c3]
        is_entity_universe: false
        entity_expression:
          - "[c1, xxhash64(c2, c3)]"
        entity_metadata:
          expression_context: Spark SQL

  - node_id: table_b
    descriptor:
      qualified_name: s3://example/table-b/
      display_name: Dataset B
    accessor:
      schema_id: accessor.s3.v1
      properties:
        bucket: example
        prefix: table-b/
        format: parquet
    columns:
      - name: d1
      - name: d2
    entity_definitions:
      - identity_id: customer_identity
        dataset_columns: [d1, d2]
        is_entity_universe: true
        entity_expression:
          - "[d1, d2]"

edges:
  - endpoint_a:
      node_id: table_a
      identity_id: customer_identity
      dataset_columns: [c1, c2, c3]
    endpoint_b:
      node_id: table_b
      identity_id: customer_identity
      dataset_columns: [d1, d2]
    a_to_b:
      multiplicity: "many:1"
      match_existence: optional
    b_to_a:
      multiplicity: "1:many"
      match_existence: unknown
```

The query agent reads the endpoint definitions in context and interprets the equality as `c1 = d1` and `xxhash64(c2, c3) = d2`. The builder only validates and preserves the registered definitions and edge.

Three metadata-provisioning modes may produce the complete intermediary: original DDL translated to YAML, original DDL combined with human or agent feedback and resolved to YAML, or direct human or agent authoring. These are external preparation modes. The builder sees the resulting YAML only.

## 4. Relationship edge contract

| ID | Requirement |
| --- | --- |
| 4.1.1 | A relationship connects two registered entity definitions of the same `identity_id`. Each endpoint is the compound reference `(node_id, identity_id, dataset_columns)`. The stored edge represents one connection in both directions; a traversal gives it direction for the agent. |
| 4.1.2 | The stable edge identity is derived from the canonical unordered pair of endpoint references. The edge stores endpoint references and relationship properties; entity expressions, expression context, accessor information, and other node metadata remain on the connected nodes. |
| 4.1.3 | The edge exposes directional multiplicity: `1:1`, `1:many`, `many:1`, `many:many`, or `unknown`. Multiplicity is supplied by the intermediary or remains unknown; the builder does not derive it from SQL key categories. |
| 4.1.4 | The edge separately exposes directional match existence for each endpoint: `always`, `optional`, or `unknown`. `Always` means every row on that endpoint has a matching row on the other side; `optional` means a row may have no match. `Unknown` is used when the intermediary cannot establish either claim. |
| 4.1.5 | Multiplicity and match existence are independent. A `many:1` link can still be optional from the many side. An unknown existence value must not be presented as a proven optional or always relationship in the AKG. |
| 4.1.6 | Local knowledge tools expose the logical identity, both endpoint references, directional multiplicity, and match existence. The agent-assembled AKG includes the connected node entity definitions so their expressions and context remain nearby without being duplicated on the canonical edge. |

For traversal from endpoint A to endpoint B, confirmed uniqueness on both sides gives `1:1`; nonunique A and unique B gives `many:1`; unique A and nonunique B gives `1:many`; and nonunique on both gives `many:many`. If the evidence does not establish a needed uniqueness state, multiplicity is `unknown`.

`Optional` means zero matches are permitted; it does not assert that an unmatched record was observed. Entity-universe status is reusable context about one entity definition, while directional match existence is the relationship-specific evidence used to determine whether an inner join would preserve records from that direction.

## 5. Explicit exclusions and deferred techniques

The initial release does not persist source-catalog primitives, infer relationships from database keys, generate vendor-specific SQL, implement physical connectors, or retain compatibility models for older artifacts. Data statistics and automatic translation from external definitions into the YAML intermediary remain outside the current scope.
