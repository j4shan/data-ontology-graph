# Knowledge Graph Product Requirements

## 1. Purpose and architecture

The Knowledge Graph is the read-only semantic map used by local reasoning agents to discover
datasets, inspect registered business identities, and navigate explicit relationships. Upstream
preparation produces a source-independent YAML intermediary. The graph builder validates it and
materializes the current offline snapshot.

| ID | Requirement |
| --- | --- |
| 1.1.1 | The graph must persist a global logical-identity registry, addressable dataset nodes, node-scoped entity definitions, and explicit relationships between registered entity definitions. |
| 1.1.2 | A dataset must be treated as an addressable data resource, not assumed to be a SQL table or tabular storage object. Source-specific location details belong only in its accessor. |
| 1.1.3 | Only relationship definitions in the validated YAML intermediary may produce edges. |
| 1.1.4 | One stored edge must represent both directions. Directional multiplicity and match existence must be preserved independently for each traversal direction. |
| 1.1.5 | Typed claims must use their explicit `unknown` value for unresolved knowledge. Descriptive text does not establish or negate a typed claim. |
| 1.1.6 | Query-time consumers must read the current published snapshot without rebuilding or mutating it. Changes enter through a validated batch rebuild and whole-artifact publication. |

The [Data Modeling Spec](data-modeling-spec.md) defines the semantic adoption boundary. The
[Graph Builder](../backend/graph-builder.md), [Ontology Access Interface](../backend/ontology-api.md),
and [Current Graph Artifact Publication](../backend/artifact-publication.md) define construction,
access, and publication behavior.

## 2. Logical identity properties

A logical identity names one business identity independently of any physical representation.

| ID | Property | Type | Required or default | Product meaning |
| --- | --- | --- | --- | --- |
| 2.1.1 | `identity_id` | string | Required; unique | Stable registry identifier reused by every physical definition of the identity. |
| 2.1.2 | `name` | string | Required | Human-readable business name. |
| 2.1.3 | `description` | string | Empty string | Business definition. |
| 2.1.4 | `synonyms` | list of strings | Empty list | Confirmed alternate discovery terms. |

## 3. Dataset node properties

### 3.1 Node envelope

| ID | Property | Type | Required or default | Product meaning |
| --- | --- | --- | --- | --- |
| 3.1.1 | `node_id` | string | Required; unique | Stable identity of one addressable dataset at its access location. |
| 3.1.2 | `descriptor` | dataset descriptor | Required | Source-independent name and discovery metadata. |
| 3.1.3 | `accessor` | dataset accessor | Required | Credential-free recipe for an external tool to locate the dataset. |
| 3.1.4 | `grain` | grain object or `unknown` | Required | What one dataset record represents, or an explicit unresolved state. |
| 3.1.5 | `columns` | list of column metadata | Required; non-empty | Physical columns retained for identity, grain, search, and relationship context. |
| 3.1.6 | `entity_definitions` | list of entity definitions | Empty list | Registered physical realizations of logical identities on this node. |

### 3.2 Descriptor, accessor, and column properties

| ID | Object | Property | Type | Required or default | Product meaning |
| --- | --- | --- | --- | --- | --- |
| 3.2.1 | Descriptor | `qualified_name` | string | Required | Fully qualified deployed dataset name. |
| 3.2.2 | Descriptor | `display_name` | string | Required | Human-readable dataset name. |
| 3.2.3 | Descriptor | `description` | string | Empty string | Supported description of purpose and contents. |
| 3.2.4 | Descriptor | `synonyms` | list of strings | Empty list | Confirmed alternate dataset names. |
| 3.2.5 | Descriptor | `tags` | list of strings | Empty list | Confirmed classification and discovery labels. |
| 3.2.6 | Accessor | `schema_id` | string | Required | Registered provider schema that validates the accessor properties. |
| 3.2.7 | Accessor | `properties` | JSON object | Required | Provider-specific location and configuration, excluding credentials. |
| 3.2.8 | Column | `name` | string | Required; unique within node | Exact physical column name. |
| 3.2.9 | Column | `description` | string | Empty string | Supported column meaning. |
| 3.2.10 | Column | `value_description` | string | Empty string | Supported description of the value domain or interpretation. |
| 3.2.11 | Column | `synonyms` | list of strings | Empty list | Confirmed alternate business terms. |

Provider-specific location fields remain in the accessor's `properties` object, which is validated
against the named `schema_id`.

### 3.3 Grain and entity-definition properties

| ID | Object | Property | Type | Required or default | Product meaning |
| --- | --- | --- | --- | --- | --- |
| 3.3.1 | Grain | `components` | list of grain components | Required; non-empty | Components that collectively define one record boundary. |
| 3.3.2 | Grain | `description` | string | Empty string | Supported explanation of the collective grain. |
| 3.3.3 | Grain component | `dataset_columns` | list of strings | Required; non-empty | Canonically ordered physical columns realizing the component. |
| 3.3.4 | Grain component | `identity_id` | string or null | Null | Registered identity realized by the component, when confirmed. |
| 3.3.5 | Grain component | `description` | string | Empty string | Supported explanation of the component. |
| 3.3.6 | Entity definition | `identity_id` | string | Required | Reference to one registered logical identity. |
| 3.3.7 | Entity definition | `dataset_columns` | list of strings | Required; non-empty | Complete canonical physical-column set realizing the identity. |
| 3.3.8 | Entity definition | `entity_universe` | `complete`, `partial`, or `unknown` | Required | Population coverage of this identity realization. |
| 3.3.9 | Entity definition | `entity_expression` | list of strings | Empty list | Unrestricted agent-facing labels preserved without parsing or execution. |
| 3.3.10 | Entity definition | `entity_metadata` | JSON object | Empty object | Context needed to interpret the physical realization. |

An entity definition is identified by `(node_id, identity_id, dataset_columns)`; it has no separate
entity-definition ID. Every referenced column must exist in the node inventory. Column sets are
duplicate-free and sorted by exact name. A grain component that supplies `identity_id` must resolve
to an entity definition with the same column set on that node.

## 4. Relationship properties

### 4.1 Edge and endpoint contract

| ID | Object | Property | Type | Required or default | Product meaning |
| --- | --- | --- | --- | --- | --- |
| 4.1.1 | Edge | `edge_id` | string | Builder-generated; unique | Stable identity derived from the canonical unordered endpoint pair. |
| 4.1.2 | Edge | `endpoint_a` | endpoint reference | Required | First endpoint after canonical ordering. |
| 4.1.3 | Edge | `endpoint_b` | endpoint reference | Required | Second endpoint after canonical ordering. |
| 4.1.4 | Edge | `a_to_b` | relationship direction | Required | Claims for traversal from endpoint A to endpoint B. |
| 4.1.5 | Edge | `b_to_a` | relationship direction | Required | Claims for traversal from endpoint B to endpoint A. |
| 4.1.6 | Endpoint | `node_id` | string | Required | Dataset containing the referenced entity definition. |
| 4.1.7 | Endpoint | `identity_id` | string | Required | Logical identity shared by both endpoints. |
| 4.1.8 | Endpoint | `dataset_columns` | list of strings | Required; non-empty | Exact canonical column set of the referenced entity definition. |
| 4.1.9 | Direction | `multiplicity` | `1:1`, `1:many`, `many:1`, `many:many`, or `unknown` | Required | Number of possible matches in this traversal direction. |
| 4.1.10 | Direction | `match_existence` | `always`, `optional`, or `unknown` | Required | Whether each row at the traversal origin is guaranteed a match. |

The endpoints must be different registered definitions of the same `identity_id`. Multiplicity and
match existence are independent authored claims; the builder validates and preserves them but does
not derive their business meaning. Swapping traversal direction does not create another edge.

### 4.2 Annotation properties

| ID | Property | Type | Required or default | Product meaning |
| --- | --- | --- | --- | --- |
| 4.2.1 | `edge_id` | string | Required | Existing relationship being described. |
| 4.2.2 | `description` | string | Empty string | Human explanation of the relationship. |
| 4.2.3 | `tags` | list of strings | Empty list | Relationship discovery and classification labels. |

Annotations are descriptive sidecar metadata. They do not create, approve, reject, or alter an
edge's structural claims.

## 5. Snapshot properties and lifecycle

| ID | Property | Type | Required or default | Product meaning |
| --- | --- | --- | --- | --- |
| 5.1.1 | `version` | string | Defaults to `5.0` | Snapshot data-contract version. |
| 5.1.2 | `schema_fingerprint` | string or null | Set on built and persisted snapshots; null by model default | Fingerprint of the node, identity, relationship, and annotation schemas. |
| 5.1.3 | `built_at` | timestamp | Required; builder supplies UTC | Time the complete snapshot candidate was built. |
| 5.1.4 | `logical_identities` | list of logical identities | Empty list | Materialized global identity registry. |
| 5.1.5 | `nodes` | list of dataset nodes | Required | Materialized dataset inventory. |
| 5.1.6 | `edges` | list of relationships | Required | Materialized relationship inventory. |
| 5.1.7 | `annotations` | list of annotations | Empty list | Optional descriptive relationship metadata. |

| ID | Requirement |
| --- | --- |
| 5.2.1 | A snapshot must reject duplicate node, logical-identity, or edge IDs and references to unknown nodes, identities, entity definitions, or edges. |
| 5.2.2 | All files representing one persisted snapshot must agree on version, build time, and schema fingerprint. |
| 5.2.3 | The application must expose one current snapshot and replace it as a complete validated unit. It must not maintain release history or rollback artifacts. |
| 5.2.4 | Consumers must treat the snapshot as read-only. Local knowledge access must not create, edit, or delete nodes, relationships, definitions, or annotations. |
