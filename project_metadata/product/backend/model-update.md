# Model Update

A user can request a batch update to the YAML knowledge source of truth.
Updates change source definitions; runtime edges are materialized only by a
rebuild. A successful publication replaces the current generated graph artifact
as one complete unit; the local read service never edits it.

## 3 Batch updates and publication

The product accepts source-controlled changes to complete YAML node and edge
definitions, logical identities, node entity definitions, relationship
properties, or annotations, then rebuilds and publishes the validated current artifact
for local agents. Accuracy takes precedence over refresh frequency.

### 3.1 Request kinds

Accepted request kinds are YAML node or edge definition update, YAML schema
update, annotation update, validation, rebuild, and publication.

### 3.2 Definition field set

A YAML definition may change a dataset descriptor, accessor, grain, columns, logical
identities, canonical dataset-column sets, entity expressions, node entity
metadata, endpoint references, multiplicity, match existence, synonyms, tags,
and descriptions.

### 3.3 Complete definitions without overrides

Each accepted YAML input contains complete node and edge definitions. The
update path does not apply overlays, merge corrections over DDL metadata, or
maintain override precedence. A runtime graph edge changes only after its YAML
edge definition or referenced node entity definition changes and the graph is
rebuilt.

### 3.4 Reproducible artifacts

YAML node and edge definitions and their machine-readable schema persist in
source control so every accepted definition and schema change is reviewable
and a rebuild is reproducible from in-repo files.

### 3.5 Ingestion gate

The source-controlled schema validator runs before ingestion. Schema-invalid
YAML is rejected with actionable findings and cannot enter a rebuild.

### 3.6 Rebuild and publication result

A successful rebuild produces the snapshot candidate and its build and validation
report. Publication safely replaces the one current source-controlled artifact.
A failed publication leaves the current artifact unchanged. The application does
not retain prior releases; see
[Current Graph Artifact Publication](artifact-publication.md).

### 3.7 Outside local knowledge tools

Update and rebuild requests are not accepted through the local read interface.
That interface only reads a published snapshot.

### 3.8 Collection quality before publication

Semantic validation of ambiguous, conflicting, or unsupported business meaning
belongs to the upstream YAML-generator agent skill. The builder and publisher
apply rule-based validation only and preserve explicit unknowns rather than
promoting them to confirmed knowledge.

### 3.9 Upstream source-definition migration

The intermediary may be prepared by translating original DDL, resolving DDL
plus human or agent feedback, or direct human or agent authoring. Humans or
external agents may iteratively refine a YAML directory, but each rebuild
accepts one finalized directory through a configurable operating-system path.
These modes all produce one complete project-schema YAML input. The builder
does not accept DDL, source catalogs, or another external format. Automated
source preparation is outside the initial release.

### 3.10 Future source change subscription

A future release will subscribe to CRUD events on all connected data sources
to detect knowledge changes. Detected changes feed a batch update of the
source of truth; they do not update published offline copies in real time.

## 4 Non-normative preparation proposal

The initial preparation proposal is a bundle of agent skills shipped with
external-definition parsing tools and YAML-authoring instructions. It would
help an external agent iteratively create the finalized YAML directory; it
would not become part of graph construction or widen the builder's accepted
input formats.
