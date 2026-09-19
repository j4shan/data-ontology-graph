# Knowledge Graph

The Knowledge Graph is the persisted semantic map of one SQL data warehouse. It
records datasets, their row identity, their columns, and the join surfaces that
connect them so a query author can choose datasets and compose joins without
inventing relationships.

## 1 Persist a SQL-warehouse semantic map

The product persists a graph of warehouse datasets and the physical join
connections among them. Query-time consumers load that graph; they do not
rebuild it.

### 1.1 Dataset node

A dataset node describes one physical dataset, including its grain, keys,
columns, warehouse role, layer (primary or secondary), and source location.

### 1.2 Bidirectional join relationship

A join relationship is one bidirectional physical connection between two
primary dataset nodes. Direction appears only when a consumer traverses the
relationship.

### 1.3 Derived relationship facts

Cardinality, unique side, and entity anchor are derived from stored endpoint
metadata. Participation and annotation weight are stored; they are not
re-derived as independent truth except as specified in
[project-description.md](../../project-description.md) Part 1.

### 1.4 Confirmed, unknown, and unassessed

The graph distinguishes confirmed classification, explicit unknown, and absent
unassessed facets. Absence is not negative evidence and is not permission to
aggregate, group, or join.

### 1.5 Secondary datasets

Secondary datasets are storage stubs. They do not own join relationships.

### 1.6 Versioned snapshot

Persistence is a versioned snapshot envelope of nodes, edges, and optional
annotations. A consumer loads the latest snapshot without rebuilding sources.

### 1.7 Domain-model conformance

Persisted records and invariants conform to
[project-description.md](../../project-description.md) Part 1.

### 1.8 Snapshot is read-only

A written snapshot is immutable. A consumer does not create, edit, or delete
dataset nodes, join relationships, or annotations on that snapshot. A later
rebuild writes a new snapshot; it does not revise the previous one.
