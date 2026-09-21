# Knowledge Graph

The Knowledge Graph is the persisted semantic map used for entity and
relationship knowledge across a hybrid data estate. It records logical
business identities, their registered node entity definitions, the datasets
containing those definitions, and the connections between them.

## 1 Persist an entity and relationship semantic map

The product persists a graph of datasets, a global logical identity registry,
node entity definitions, and connections between registered definitions.
Query-time consumers load the current published offline artifact; they do not rebuild it.

### 1.1 Dataset node

A dataset node describes one addressable dataset. It contains a dataset
descriptor, a schema-identified accessor with provider-specific JSON
properties, relevant columns, zero or one grain, and registered entity
definitions. It does not reproduce a source catalog's SQL keys or other
database primitives. The initial-release adoption boundary is the
[Data Modeling Spec](../product/data/data-modeling-spec.md).

### 1.2 Logical identity and entity definition

A logical identity represents one business identity independently of its
physical encoding. A node entity definition records one realization using the
compound identity `(node_id, identity_id, dataset_columns)`. It carries one
or more unrestricted entity-expression labels, entity metadata, and its own
`is_entity_universe` value.

### 1.3 Bidirectional relationship

A relationship is one bidirectional connection between two registered entity
definitions of the same logical identity. Direction appears only when a
consumer traverses the relationship.

### 1.4 Relationship properties

Directional multiplicity and always/optional/unknown match existence are
stored from the validated intermediary. The edge stores endpoint references;
entity expressions and expression context remain on the connected nodes. The
[Data Modeling Spec](../product/data/data-modeling-spec.md) defines the target
contract.

### 1.5 Confirmed, unknown, and unassessed

The graph distinguishes confirmed classification, explicit unknown, and absent
unassessed facets. Absence is not negative evidence and is not permission to
aggregate, group, or join.

### 1.7 Current snapshot artifact

Persistence is a snapshot envelope of nodes, edges, and optional annotations.
The source-controlled repository contains only the current generated artifact;
the application does not retain prior graph releases. A consumer loads that
artifact without rebuilding sources.

### 1.8 Domain-model conformance

The initial-release target conforms to the
[Data Modeling Spec](../product/data/data-modeling-spec.md).
[project-description.md](../../project-description.md) Part 1 records the
legacy inference schema retained for compatibility.

### 1.9 Snapshot is read-only

A consumer does not create, edit, or delete dataset nodes, join relationships,
or annotations in the current artifact. A later batch rebuild replaces the
artifact as one complete validated unit. The application does not manage prior
versions or rollback copies.
