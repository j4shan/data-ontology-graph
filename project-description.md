# Data Ontology Graph — Project Description

> **Status:** This document describes the legacy SQL inference path retained for
> compatibility. The initial-release product contract is the
> [Data Modeling Spec](project_metadata/product/data/data-modeling-spec.md).

A persistent knowledge graph that connects datasets, using nodes and edges to capture
relationships and data models. This document merges the two source specifications:

1. **[Knowledge Graph Data Model](#part-1--knowledge-graph-data-model)** — what is persisted.
2. **[Join Relationship Inference](#part-2--join-relationship-inference)** — how edges are created.

---

# Part 1 — Knowledge Graph Data Model

## A shared semantic map for measurement datasets

The knowledge graph describes datasets, their row identity, their columns, and the join
surfaces that connect them.

Its purpose is to give a text-to-SQL agent enough structural and semantic context to choose
datasets and compose joins without inventing relationships.

## The model at a glance

The graph has two principal records:

- A **dataset node** describes one physical dataset and its semantic meaning.
- A **join relationship** describes one physical connection between two dataset nodes.

Supporting records describe columns, grain, keys, source locations, replicas, annotations,
and snapshot metadata.

The persisted relationship is bidirectional. Direction appears only when a consumer
traverses it from one endpoint to the other.

## Dataset node fields

| Field | Type | Required or default | Ownership | Description |
| --- | --- | --- | --- | --- |
| `node_id` | string | Required | Ingested | Stable graph identity for the dataset. |
| `table_name` | string | Required | Ingested | Physical table or dataset name. |
| `table_role` | fact, dimension, bridge, aggregate, or unknown | `unknown` | Authored | Structural warehouse role. Unknown means the role has not been assessed. |
| `is_entity_universe` | boolean | `false` | Authored or mapped at ingest | Whether a dimension contains the complete universe of its entities. |
| `data_source` | source-specific object | Required | Ingested | Physical source identity and location. |
| `primary_key` | list of column names | Empty list | Ingested or overlay-supplied when absent | Unconditional primary key. |
| `foreign_key_declarations` | list of foreign-key declarations | Empty list | Ingested from declared metadata | Source evidence used to produce declared joins. |
| `grain` | list of grain components | Empty list | Authored or synthesized from a primary key | One product expression defining row identity. Empty means unknown. |
| `unique_keys` | list of column-name lists | Empty list | Ingested or authored | Alternate unconditional unique constraints. |
| `filtered_unique_keys` | list of conditional unique keys | Empty list | Ingested or authored | Unique constraints that hold only under a predicate. |
| `columns` | list of column metadata | Empty list | Ingested and enriched | Physical and semantic column inventory. |
| `description` | string | Empty string | Authored or ingested | Plain-language dataset description. |
| `synonyms` | list of strings | Empty list | Authored | Alternative dataset names used for discovery. |
| `tags` | list of strings | Empty list | Authored | Open-ended semantic facets, including warehouse subtypes and usage patterns. |
| `dataset_layer` | primary or secondary | `primary` | System-classified | Distinguishes source-of-truth datasets from replica or storage copies. |
| `primary_ref` | primary dataset reference or absent | Absent | System-detected or curated | A secondary dataset's pointer to its logical primary. |
| `replica_node_ids` | list of node IDs | Empty list | System-resolved | Reverse references from a primary to its known secondary copies. |
| `pk_child_entity` | child node ID to column metadata map | Empty map | System-derived | Non-unique child-entity subkeys discovered inside a composite primary key. |
| `logical_entity_key` | entity name to column-name list map | Empty map | Curated | Explicit non-unique entity subkeys used as join surfaces. |

## Dataset node invariants

- Column names within a node are unique.
- Primary-key and local foreign-key columns must exist in the column inventory of a primary node.
- Unconditional and filtered unique-key columns must resolve to physical columns.
- A curated logical entity key must use existing columns.
- When a primary key exists, a curated logical entity key must be a subset of it.
- Secondary nodes are storage stubs and do not own join relationships.
- Empty grain components are discarded because they carry no row-identity information.

## Column metadata fields

| Field | Type | Required or default | Meaning |
| --- | --- | --- | --- |
| `name` | string | Required | Physical column name. |
| `data_type` | string | Empty string | Physical SQL or storage type. |
| `description` | string | Empty string | Plain-language column meaning. |
| `synonyms` | list of strings | Empty list | Alternative names for search and language grounding. |
| `is_nullable` | boolean | `true` | Whether the physical column accepts nulls. |
| `additivity` | fully additive, semi-additive, non-additive, dimension, or unknown | `unknown` | Measure-versus-dimension classification and aggregation behavior. |
| `key_spec` | key-usage facet or absent | Absent | How the column functions as a key when explicitly known. |
| `logical_name` | string or absent | Absent | Logical Column Name shared by physically different but join-equivalent columns. |
| `logical_transform` | string or absent | Absent | Function that maps the physical value into the logical column's canonical join space. |

For matching purposes, the effective logical name is `logical_name` when supplied and
otherwise the physical `name`.

## Key-usage facet

The optional `key_spec` block distinguishes an unassessed column from a column whose key
role is known.

| `kind` value | Meaning | Join implication |
| --- | --- | --- |
| `surrogate` | System-generated key with no business meaning. | May identify a dimension or record but usually requires business-key context for conformance. |
| `natural` | Key derived from stable business attributes. | Can support business-level identity and conformance. |
| `durable` | Stable key that survives source-system or version changes. | Useful for long-lived entity identity. |
| `degenerate` | Transaction identifier stored on a fact with no parent dimension. | Excluded as a source of inferred relationships. |

An absent `key_spec` means key usage was never assessed. It does not mean "not a key."

## Grain fields

| Field | Type | Required or default | Description |
| --- | --- | --- | --- |
| `entity_name` | string | Required | Semantic entity contributed by this grain factor. |
| `columns` | list of column names | Required | Physical columns that identify the factor. |
| `provenance` | declared, inferred from primary key, or absent | Absent | How the grain component was asserted. Absence is treated as authored but unspecified provenance. |

The `grain` list is one combinatory product. If a row is identified jointly by campaign and
tracking tag, both components jointly define the row.

The list is not a menu of alternative grains. Alternative uniqueness belongs in
`unique_keys`; conditional uniqueness belongs in `filtered_unique_keys`.

## Key and reference records

### Declared foreign key

| Field | Type | Required or default | Description |
| --- | --- | --- | --- |
| `local_columns` | list of column names | Required | Columns on the declaring dataset. |
| `ref_table` | string | Required | Referenced table name. |
| `ref_columns` | list of column names | Required | Referenced columns on the target table. |
| `is_mandatory` | boolean | `false` | Whether all local columns are non-null according to the declaration source. |

This record is input evidence. It is converted into a join relationship during graph construction.

### Filtered unique key

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `columns` | list of column names | Yes | Columns unique only for rows satisfying the filter. |
| `filter_predicate` | string | Yes | Predicate under which uniqueness holds. |

Filtered uniqueness is descriptive and query-relevant, but it is not treated as
unconditional uniqueness during join detection.

### Primary dataset reference

| Field | Type | Required or default | Description |
| --- | --- | --- | --- |
| `qualified_name` | string | Required | Source-system identity of the primary dataset. |
| `source_type` | string | Required | Source category of the primary dataset. |
| `node_id` | string or absent | Absent until resolved | Bound graph identity of the primary when available. |

## Physical source variants

Every dataset has one discriminated `data_source` value.

| Source type | Fields | Defaults and meaning |
| --- | --- | --- |
| `s3` | `type`, `bucket`, `prefix`, `format`, `partition_keys` | `type` is fixed to `s3`; `format` defaults to parquet; partition keys default to an empty list. |
| `databricks_unity` | `type`, `workspace_host`, `catalog`, `schema`, `table` | `type` is fixed to `databricks_unity`; the remaining fields form the fully qualified Unity Catalog identity. |
| `sql_db` | `type`, `host`, `database`, `schema`, `table`, `dialect` | `type` is fixed to `sql_db`; `dialect` defaults to Microsoft SQL Server. |
| `snowflake` | `type`, `account`, `database`, `schema`, `table` | `type` is fixed to `snowflake`; the remaining fields form the fully qualified Snowflake identity. |

> The source block identifies storage and integration boundaries. It does not determine
> semantic role, grain, or join behavior.

## Primary and secondary dataset layers

| Layer | Purpose | Semantic metadata | Join participation |
| --- | --- | --- | --- |
| Primary | Source-of-truth logical dataset | Full structural and semantic model | Owns inferred and declared relationships |
| Secondary | Replica or storage copy | Source location, available columns, and primary reference | Excluded from relationship inference |

A primary may list its replicas in `replica_node_ids`. A secondary may point back through
`primary_ref`.

Logical search and traversal prefer primary nodes. Physical source selection among a primary
and its replicas is a separate concern.

## Join endpoint fields

Each relationship contains two symmetric endpoints.

| Field | Type | Required or default | Stored meaning |
| --- | --- | --- | --- |
| `node_id` | string | Required | Dataset attached to this endpoint. |
| `columns` | list of column names | Required | Physical columns participating on this side. |
| `is_unique` | boolean | Required | Whether these columns cover an unconditional unique key on this node. |
| `transform` | string or absent | Absent | Function applied before comparison with the opposite endpoint. Absence means identity. |
| `participation` | total, partial, or unknown | `unknown` | Whether every row on this endpoint is known to match the other side. |

Endpoint columns remain physical even when matching was discovered through a shared Logical
Column Name.

## Join relationship fields

| Field | Type | Required or default | Description |
| --- | --- | --- | --- |
| `edge_id` | string | Required | Deterministic identity derived from the unordered endpoint node-and-column pairs. |
| `endpoint_a` | join endpoint | Required | First canonical endpoint. |
| `endpoint_b` | join endpoint | Required | Second canonical endpoint. |
| `precedence` | inferred or declared | `declared` | Provenance strength of the relationship evidence. |

One relationship represents both directions. A query-time traversal orients it from the
current node to the next node.

## Derived relationship facts

These facts are calculated from stored endpoint metadata rather than persisted as
independent truth.

| Derived fact | Inputs | Result |
| --- | --- | --- |
| Cardinality | `is_unique` on both endpoints plus traversal direction | `1:1`, `N:1`, `1:N`, or `M:N` |
| Unique side | Endpoint uniqueness | The single unique endpoint when exactly one exists |
| Entity anchor | Endpoint columns compared with complete primary keys by logical name | The node whose full primary key represents the identified entity, when determinable |
| Effective weight | Optional annotation for the edge | Human-adjustable traversal weight, defaulting to 1.0 |

Cardinality rules:

| Endpoint A unique | Endpoint B unique | Relationship shape |
| --- | --- | --- |
| Yes | Yes | `1:1` |
| No | Yes | `N:1` from A to B |
| Yes | No | `1:N` from A to B |
| No | No | `M:N` |

## Referential participation

Participation answers a different question from cardinality: "Will preserving this side with
an inner join lose rows?"

| Value | Meaning | Conservative query interpretation |
| --- | --- | --- |
| `total` | Every row on this endpoint is known to match the other side. | Inner join can be lossless for this preserved side. |
| `partial` | Some rows may have no match, including nullable references. | Use a left join when preserving this side. |
| `unknown` | Completeness cannot be proven. | Treat like partial unless the query has stronger evidence. |

Total participation is only asserted for a non-unique many side with non-null join columns
targeting the full primary key of a complete dimension universe.

## Join annotation fields

Human descriptive metadata is separated from structural relationship truth.

| Field | Type | Required or default | Description |
| --- | --- | --- | --- |
| `edge_id` | string | Required | Relationship being annotated. |
| `weight` | number | `1.0` | Mutable traversal preference. |
| `description` | string | Empty string | Human explanation of the relationship. |
| `tags` | list of strings | Empty list | Open-ended relationship labels. |
| `notes` | string | Empty string | Additional curation notes. |

Annotations do not approve, reject, or gate traversal.

## Traversal-oriented relationship view

A traversal hop adds direction without changing the stored relationship.

| Field | Type | Description |
| --- | --- | --- |
| `relationship` | join relationship | Original bidirectional record. |
| `from_node_id` | string | Node being left. |
| `to_node_id` | string | Node being entered. |
| Cardinality | derived string | Relationship cardinality from the hop's direction. |

This separation keeps persistence symmetric while allowing direction-dependent explanations.

## Snapshot envelope

The materialized graph is versioned and schema-checked.

| Field | Type | Required or default | Description |
| --- | --- | --- | --- |
| `version` | string | `2.0` | Snapshot contract version. |
| `schema_fingerprint` | string or absent | Absent only for legacy snapshots | Fingerprint of the node, relationship, and annotation schemas. |
| `built_at` | timestamp | Required | UTC build time. |
| `nodes` | list of dataset nodes | Required | Materialized dataset inventory. |
| `edges` | list of join relationships | Required | Materialized join inventory. |

Nodes and edges may be stored in separate files carrying the same version, build time, and
schema fingerprint. An annotation sidecar may be stored separately.

## Explicit unknowns are first-class

The model distinguishes three states:

1. **Confirmed classification**, such as `dimension` or `fully_additive`.
2. **Explicit unknown**, such as `table_role = unknown` or `additivity = unknown`.
3. **Unassessed dependent facet**, represented by an absent optional block such as `key_spec`.

This prevents missing metadata from being silently interpreted as negative evidence or as
permission to aggregate, group, or join.

## Kimball concepts directly modeled

This section inventories fields in the legacy inference model. The
[initial-release Data Modeling Spec](project_metadata/product/data/data-modeling-spec.md)
defines which concepts are product requirements and where the target model
differs from this implementation.

| Kimball concept | Representation in the graph | Query relevance |
| --- | --- | --- |
| Fact table | `table_role = fact` | Carries events, measurements, and dimensional references. |
| Dimension table | `table_role = dimension` | Supplies descriptive attributes and entity context. |
| Bridge table | `table_role = bridge` | Represents multi-valued or many-to-many associations. |
| Aggregate table | `table_role = aggregate` | Stores pre-aggregated results at a declared grain. |
| Grain | Product of grain components | Defines what one row represents and guards aggregation correctness. |
| Surrogate key | `key_spec.kind = surrogate` | Separates warehouse identity from business identity. |
| Natural key | `key_spec.kind = natural` | Represents business-derived identity. |
| Durable key | `key_spec.kind = durable` | Preserves identity across source or version changes. |
| Degenerate dimension | `key_spec.kind = degenerate` | Transaction identifier without a parent dimension. |
| Additive measure | `additivity = fully_additive` | Safe to sum across supported dimensions. |
| Semi-additive measure | `additivity = semi_additive` | Additive across some dimensions but not all, commonly time. |
| Non-additive measure | `additivity = non_additive` | Requires formulas or controlled aggregation. |
| Dimension attribute | `additivity = dimension` | Confirmed descriptive or grouping column. |
| Slowly changing dimension signal | Filtered unique keys and history tags | Expresses current-row or time-bounded uniqueness without treating it as universal. |
| Conformed key or attribute | Shared Logical Column Name | Aligns equivalent business meaning across physical schemas. |
| Referential completeness | Endpoint participation | Supports conservative inner-versus-left join decisions. |

## Kimball concepts carried as advisory metadata

Some concepts are labels or query-time guidance rather than enforced graph structure.

| Concept | Representation | Enforcement level |
| --- | --- | --- |
| Fact subtype | Tags such as transaction, periodic snapshot, accumulating snapshot, or factless | Descriptive only |
| Dimension subtype | Tags for role-playing, outrigger, junk, mini-dimension, or history pattern | Descriptive only |
| Point-in-time usage | Usage tags and advisory predicates | Consumer judgment |
| Drill-across | Conformance and compatible-grain analysis | Suggested structure, not automatic SQL |
| Bridge staging | Bridge role and fan-out metadata | Consumer judgment |
| Fact-to-fact joins | Served as valid topology | Not prohibited by a structural rule engine |

The graph exposes metadata and topology. It does not enforce a universal Kimball join-shape
policy.

## Practical interpretation for text-to-SQL

Before composing a query, an agent should ask:

- Is each selected dataset primary or a secondary copy?
- What does one row represent?
- Which columns are confirmed dimensions or measures?
- Does a join cover a complete unconditional key?
- What cardinality appears in the intended direction?
- Is participation total, partial, or unknown?
- Does the relationship require a transform?
- Is an apparent many-to-many edge appropriate for row expansion, or does the question
  require pre-aggregation?

The data model supplies evidence for these decisions while preserving unknowns for the agent
to handle explicitly.

---

# Part 2 — Join Relationship Inference

## Turning dataset metadata into executable join connections

The relationship inference process is the only mechanism that creates graph edges.

It combines declared database evidence with deterministic structural matching. It uses no
language model, data profiling query, or manually authored edge file.

## Core principle

A relationship is created when one dataset provides a complete join surface for a matchable
entity key on another dataset.

The key must be covered in full. Partial overlap is not enough unless the target explicitly
exposes that partial key as a child-entity join surface.

The result is one bidirectional relationship with two physical endpoints.

## Where human knowledge enters

Human knowledge does not enter as an asserted edge.

It enters through:

- Declared foreign keys from source metadata.
- Logical Column Name labels on columns.
- Optional logical transforms into a shared join space.
- Curated logical entity keys for meaningful non-unique subkeys.
- Semantic role and completeness metadata used for participation.

The normal inference process translates that evidence into relationships.

## Construction sequence

| Order | Stage | Join-relevant outcome |
| --- | --- | --- |
| 1 | Ingest declared database metadata | Primary keys, alternate unique keys, foreign-key declarations, columns, and nullability |
| 2 | Ingest catalog metadata | Physical columns, descriptions, source locations, and replica signals |
| 3 | Apply curated dataset metadata | Logical names, transforms, grain, roles, key facets, and curated entity keys |
| 4 | Resolve description-carried logical metadata | Previously unlabeled columns may receive Logical Column Names and transforms |
| 5 | Synthesize missing grain from a primary key | A known row identity is recorded without semantic guessing |
| 6 | Decompose composite primary keys | Reusable child-entity subkeys become matchable surfaces |
| 7 | Infer join relationships | Declared and structural evidence produce edges |
| 8 | Resolve replica links | Secondary copies are linked to their primary datasets |
| 9 | Persist a versioned snapshot | Nodes and relationships are saved with schema identity |

## Two evidence channels

| Channel | Evidence | Relationship provenance |
| --- | --- | --- |
| Declared | A source-system foreign-key declaration names local columns, a referenced table, and referenced columns | `declared` |
| Structural | A dataset's available columns completely cover a registered entity key by Logical Column Name | `inferred` |

Both channels feed the same relationship model and the same precedence-aware merge behavior.

## Declared relationship detection

For each foreign-key declaration on a primary dataset:

1. Resolve the referenced table name case-insensitively.
2. Accept the target only when exactly one matching primary dataset exists.
3. Count and skip an unresolved or ambiguous target.
4. Count and skip a self-reference rather than creating a self-edge.
5. Preserve the declared local and referenced physical columns.
6. Determine whether each endpoint covers an unconditional unique key.
7. Infer endpoint participation and parent completeness.
8. Create the relationship with `declared` precedence.

Declared relationships retain identity transforms. Declared provenance outranks inferred
provenance, so structural Logical Column Name matching cannot update the endpoints or
transforms of the same declared relationship. A transform required specifically by a declared
relationship is not representable by the current declared-evidence path.

## Structural relationship detection

Structural inference evaluates each primary dataset as a possible source of join columns.

The process:

1. Group source columns by effective Logical Column Name.
2. Exclude degenerate keys from acting as relationship sources.
3. Look up every registered entity key containing each logical name.
4. Count logical-name coverage separately for every target and key category.
5. Continue only when every logical name in a key is covered.
6. Expand multiple physical columns sharing a logical name into separate physical join candidates.
7. Preserve physical columns and their endpoint transforms.
8. Determine uniqueness and participation on both sides.
9. Create an `inferred` relationship candidate.

This is deterministic metadata matching, not fuzzy matching.

## The four matchable entity-key categories

| Category | Origin | Unique on target? | Typical relationship shape |
| --- | --- | --- | --- |
| Primary key | Complete `primary_key` | Yes | `N:1` or `1:1` |
| Alternate unique key | One complete entry in `unique_keys` | Yes | `N:1` or `1:1` |
| Auto-derived child entity | Reusable strict subset of a composite primary key | No | Often `M:N` |
| Curated child entity | Explicit `logical_entity_key` | No | Often `M:N` |

Filtered unique keys are excluded because their uniqueness is conditional on a predicate.

## Non-preempted matching

The four key categories are evaluated independently.

If one dataset completely covers several valid keys on another dataset, every covered key can
produce a relationship. A full primary-key edge does not suppress a child-entity edge, and a
curated child edge does not suppress an alternate-unique-key edge.

This preserves legitimate choices at different levels of granularity.

The text-to-SQL consumer must select the relationship appropriate to the question.

## Complete coverage rule

| Target key | Source coverage | Result |
| --- | --- | --- |
| Single-column key | Matching logical column present | Candidate relationship |
| Composite key | Every logical column present | Candidate relationship |
| Composite key | Only some logical columns present | No relationship for that key |
| Declared or derived child subkey | Every logical column in the subkey present | Candidate relationship on the subkey |

Completeness prevents accidental joins on incomplete composite identifiers.

## Logical Column Name

A Logical Column Name, or LCN, is a column-level join-equivalence label.

It answers:

> Which columns represent the same joinable concept after any declared transformation?

The LCN is distinct from:

- The physical column name.
- The dataset's grain entity name.
- A table role such as fact or dimension.
- A general synonym used only for search.

### Effective logical name

| Column state | Effective logical name | Matching behavior |
| --- | --- | --- |
| `logical_name` supplied | The supplied LCN | Can match differently named columns carrying the same LCN |
| `logical_name` absent | Physical `name` | Reproduces exact physical-name matching |

Most columns can remain unlabeled. LCN coverage can grow incrementally as reliable
equivalence knowledge becomes available.

LCN comparison is exact. Labels must be authored consistently.

### Why LCN matters

Physical schemas often encode one business concept under different names or representations.

| Dataset | Physical column | Logical Column Name | Transform |
| --- | --- | --- | --- |
| Identity events | `IdentityKey` | `device_identity` | `xxhash64` |
| Device index | `DeviceIdHash64` | `device_identity` | Identity |

The shared LCN establishes semantic equivalence. The transform preserves how the values reach
the same canonical comparison space.

The resulting predicate means: hash the raw identity value, then compare it with the
already-hashed device identifier.

## Physical columns remain authoritative

LCN is used for discovery, but relationship endpoints persist physical column names.

This matters because:

- The two sides may use different physical names.
- SQL must reference real columns.
- A transform may apply to only one side.
- Multiple physical columns may share one LCN.

The logical label explains equivalence; the endpoint fields keep the relationship executable.

## Transform handling

| Endpoint shape | Stored transform |
| --- | --- |
| One matched column | That column's `logical_transform`, if present |
| Several matched columns with one shared transform | The shared transform |
| Several matched columns with mixed transform requirements | No composite transform is inferred |
| No transform metadata | Identity |

Per-column mixed transforms for a composite key are outside the current inference contract.

Transform-bearing relationships require explicit metadata. The system does not discover
transformations by profiling values.

## LCN fan-out

One dataset may contain several physical columns with the same LCN.

Each physical combination that completely covers the target key becomes a separate
relationship candidate. This keeps different executable predicates visible instead of
choosing one silently.

Fan-out increases choice, but it also increases the need for query-intent judgment.

## Endpoint uniqueness

An endpoint is unique when its join columns cover:

- The complete primary key, or
- One complete unconditional alternate unique key.

Covering additional columns does not remove uniqueness.

Filtered unique keys do not establish endpoint uniqueness because their guarantee holds only
after applying a predicate.

## Cardinality is derived

Cardinality is not independently authored.

| Source endpoint unique | Target endpoint unique | Cardinality from source to target |
| --- | --- | --- |
| No | Yes | `N:1` |
| Yes | No | `1:N` |
| Yes | Yes | `1:1` |
| No | No | `M:N` |

The same bidirectional relationship can therefore present different directional cardinality
depending on traversal.

## Participation is stored

Participation describes referential completeness rather than row-count cardinality.

| Situation on an endpoint | Participation |
| --- | --- |
| Non-unique many side, all join columns non-null, full primary-key target, target is a complete dimension universe | `total` |
| Non-unique many side with at least one nullable join column | `partial` |
| Unique side, many-to-many relationship, one-to-one relationship, or completeness cannot be proven | `unknown` |

Consumers treat `unknown` conservatively when deciding between inner and left joins.

## Canonical relationship identity

The relationship identity is derived from:

- Both endpoint node IDs.
- The sorted physical columns on each endpoint.
- A canonical ordering of the two endpoints.

Swapping traversal direction does not create a second relationship.

Different column pairs between the same datasets remain different relationships.

## Precedence-aware merging

| Existing evidence | Incoming evidence | Outcome |
| --- | --- | --- |
| None | Inferred or declared | Insert the relationship |
| Inferred | Declared for the same identity | Replace endpoint details and promote to declared |
| Declared | Inferred for the same identity | Keep the declared relationship |
| Same precedence | Corrected assertion for the same identity | Replace endpoint details with the incoming assertion |

The ordering is `inferred` below `declared`.

This allows corrected uniqueness, transform, or participation metadata to replace an earlier
equal-or-weaker assertion without creating a duplicate edge.

## What merging does not do

> Precedence merging handles duplicate relationship identity. It does not resolve
> contradictions between distinct relationship identities.

A contradiction may exist when the same source endpoint appears to target different columns
on the same other dataset.

Those cases are:

- Preserved in the graph.
- Detected by separate validation.
- Reported for investigation.
- Never auto-resolved by relationship inference.

The contradiction check is not part of the normal build sequence.

## Inference report

Each inference run summarizes:

| Metric | Meaning |
| --- | --- |
| `declared_edges` | Resolved declared relationships attempted |
| `inferred_edges` | Structurally matched relationships attempted |
| `unresolved_declared` | Declared references with no single primary target |
| `self_referential` | Declared self-references skipped |
| `total` | Distinct relationships present after merging |

Attempt counts can exceed the final total because declared and inferred evidence may converge
on the same canonical relationship.

## Persistence

After enrichment:

1. Every dataset node is revalidated.
2. A schema fingerprint is computed for the persisted contract.
3. Nodes are written to `nodes.json`.
4. Relationships are written to `edges.json`.
5. Both files carry the same version, build timestamp, and schema fingerprint.

The versioned output directory is selected before the build stages begin. Relationship
annotations may be stored separately. Query-time consumers load the latest version rather
than rebuilding sources.

## Worked mental model: declared relationship

Suppose an event dataset declares `CampaignId` as a foreign key to a campaign dataset.

- The event endpoint is non-unique on `CampaignId`.
- The campaign endpoint is unique because `CampaignId` is its complete key.
- The relationship is `N:1` from event to campaign.
- Provenance is declared.
- If the event column is nullable, event-side participation is partial.
- If it is non-null and campaign is a complete dimension universe, participation can be total.

## Worked mental model: transformed relationship

Suppose a raw identity dataset stores `IdentityKey`, while a device index stores
`DeviceIdHash64`.

- Both columns carry the LCN `device_identity`.
- `IdentityKey` declares the transform `xxhash64`.
- `DeviceIdHash64` is already in canonical form.
- Complete LCN coverage establishes the candidate relationship.
- The two endpoint records retain their different physical column names.
- The stored transform tells a query composer to hash only the raw side.

No edge file is authored; correcting this relationship means correcting the column metadata
and rebuilding.

## Guardrails

- Secondary datasets never produce or receive inferred relationships.
- Degenerate keys do not act as structural edge sources.
- Partial composite-key overlap does not create a full-key relationship.
- Conditional uniqueness does not become unconditional cardinality.
- Self-referential declared foreign keys do not become graph self-edges.
- Unresolvable declared targets are counted, not fabricated.
- Unknown participation is not treated as proof of completeness.
- Parallel many-to-many edges remain visible because choosing among them depends on query intent.

## What the inferrer deliberately does not decide

- Which of several valid many-to-many relationships best answers a question.
- Whether a coarse relationship requires pre-aggregation or distinct keys.
- Whether two contradictory relationships should be merged or deleted.
- Whether an inferred transformation is likely based on sampled data.
- Whether a physical replica should be selected for execution.
- Whether a fact-to-fact or bridge path is desirable for a specific analytical intent.

The inferrer records deterministic structural possibilities. The query-composing agent
applies intent.
