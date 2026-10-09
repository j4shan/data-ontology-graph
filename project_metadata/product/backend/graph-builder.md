# Graph Builder

The Graph Builder is the only mechanism that creates relationships. It turns
validated, source-independent YAML definitions into the current snapshot artifact.

## 2 Builder is the only edge writer

No other component inserts, edits, or deletes a join relationship.

### 2.1 Inputs

Each builder invocation accepts a configurable operating-system path to either
one assembled YAML file or one finalized `yaml/` directory. A directory has a
fixed `directory-manifest.yaml` beside it. That manifest uses schema version
`"3"` and names, relative to the YAML directory, exactly one logical-identity
file, one or more node files, and exactly one edge file. Each collection file
uses the same schema version and contains exactly its owned collection. The
node files partition one assembled node list; identities and edges are not
partitioned. The builder consumes the resulting intermediary as one coherent
input containing complete dataset node definitions, relationship edge
definitions, the global logical identity registry, node entity definitions,
and relationship properties. Source-controlled machine-readable schemas govern
the directory manifest and assembled intermediary. Project-schema YAML is the
builder's only input format: it does not consume tenant DDLs, source catalogs,
or other external definition formats directly.

### 2.2 Ingestion quality gate

Validation runs before ingestion. For directory input, the builder first
validates the sibling manifest, safe relative path containment, completeness of
the listed file inventory, collection ownership, and schema-version agreement.
It rejects missing, unlisted, duplicate, unsupported, or directory-escaping
files. It then assembles the three collections and validates the result against
the existing intermediary schema. A YAML input that violates either contract is
rejected with actionable location and rule findings and does not enter graph
construction. Single-file input is validated directly as an assembled
intermediary.

Each dataset accessor is a generic `schema_id` plus JSON `properties` envelope.
A known `schema_id` dispatches provider-specific property validation during
deserialization without adding provider fields to the universal dataset node.

### 2.3 Relationship construction

The builder materializes an explicit YAML edge only after both endpoints
resolve to registered entity definitions with the same `identity_id`. An
endpoint reference is `(node_id, identity_id, dataset_columns)`. Column-name
equality, foreign-key declarations, and composite-key subset decomposition are
not target relationship rules.

### 2.4 Construction sequence

After schema-gated ingestion, construction validates node and logical-identity
references, canonical dataset-column sets, entity-definition uniqueness, edge
endpoint resolution, shared endpoint identity, multiplicity, and match
existence. It also validates the dataset descriptor, accessor subtype, required
grain or explicit unknown grain, relevant column inventory, and entity-definition-scoped
`entity_universe`. It then indexes logical identities and entity definitions, derives
stable edge identities from canonical endpoint pairs, and writes the snapshot.
Entity-expression text is preserved without parsing or execution.

### 2.5 Snapshot and build report

A rebuild produces a complete snapshot candidate and a build report with definition
validation failures, unresolved dataset or identity references, incompatible
entity definitions, total relationships, and every typed claim whose value is
`unknown`, located by stable IDs for the upstream preparation cycle.

### 2.6 Contradiction report

Deterministic rule violations, including incompatible references and duplicate
definitions, are reported and never auto-resolved. The builder does not assess
the business meaning of otherwise schema-valid knowledge.

### 2.7 Publication quality

The batch publication process accepts only a candidate that passes the builder's
rule-based validation. Semantic validation belongs to the upstream YAML-generator
agent skill. Publication follows the single-current-artifact contract in
[Current Graph Artifact Publication](artifact-publication.md).

### 2.8 Upstream definition migration

The complete YAML intermediary may be produced from original DDL, from DDL
plus human or agent feedback, or through direct human or agent authoring.
Humans or external agents may iteratively create and refine the YAML directory
before marking it ready for a build. These preparation modes are upstream of
the builder. The builder does not modify prepared YAML, apply overlays, merge
feedback onto DDL metadata, or implement override precedence.

## 3 Upstream preparation boundary

The DDL collector in `src/ddl_collector/` and the source-family skills in `skills/`
prepare project-schema YAML from external definitions, evidence, and optional input
from the user running the collector.
They depend on the graph core's model and builder APIs. The graph core must remain
independent of the collector and skills. Collector output must enter construction
only as a finalized YAML intermediary through the validation gate in Section 2;
the builder must not accept collector evidence or decisions as alternate inputs.

The node identity composition rule remains in the source-controlled intermediary
schema. Field-preparation, column-inventory, accessor-recipe, and decision-log
requirements are in [YAML Preparation Skill Product Requirements](../data/yaml-preparation.md).
