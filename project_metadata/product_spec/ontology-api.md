# Ontology API

The Ontology API assists a query author or text-to-SQL agent in composing SQL
from the latest snapshot.

## 4 SQL-assist from the latest snapshot

The API reads the latest snapshot. It does not rebuild the graph on every
query. It does not mutate graph knowledge.

### 4.1 Search

Search returns primary datasets matching a name, synonym, tag, or table role.

### 4.2 Dataset detail

Dataset detail returns grain, columns, keys, layer, and source identity.

### 4.3 Directed hops

Traversal hops from a node are directed views of stored relationships, with
derived cardinality and stored participation.

### 4.4 Ranked paths

Join-path search returns ranked paths between named datasets over primary
nodes. Each hop carries join advice: cardinality, participation, recommended
inner-versus-left join, and any transform. Paths are ranked by hop count, then
annotation weight. Every path within the caller’s maximum hop count is
returned; the API does not pick a single winner.

### 4.5 SQL ON fragment

A hop can be rendered as an executable SQL ON predicate using physical column
names and endpoint transforms. Fragments use the SQLite dialect.

### 4.6 Additivity guidance

Column guidance reports additivity and grouping safety, preserving unknown.

### 4.7 Out of scope

The API does not generate a complete query from natural language, pick a
single many-to-many path, choose a physical replica for execution, or execute
SQL.

### 4.8 In-repo public interface

The public interface is an HTTP API documented by OpenAPI, served from this
repository together with test cases. Tests run against the BIRD Mini-Dev
SQLite databases in `resources/data/dev_databases`.

### 4.9 Read-only HTTP surface

The HTTP API does not accept catalog upsert, overlay upsert, annotation
upsert, or rebuild requests. Path search and SQL-fragment requests do not
change stored nodes, edges, or annotations.
