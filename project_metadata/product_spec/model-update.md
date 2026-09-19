# Model Update

A user can request an update to the tracked data model. Updates change
evidence; they do not write edges.

## 3 User-requested updates

The product accepts requests that change catalog records, curated overlays, or
annotations, and requests that rebuild the graph from those artifacts.

### 3.1 Request kinds

Accepted request kinds are catalog upsert, curated overlay upsert, annotation
upsert, and rebuild.

### 3.2 Overlay field set

A curated overlay may change table role, entity-universe flag, grain, unique
keys, filtered unique keys, column logical names and transforms, key-usage
facets, additivity, synonyms, tags, descriptions, and logical entity keys.

### 3.3 No direct edge mutation

A user cannot create, edit, or delete a join relationship except by changing
the evidence in 3.1–3.2 and rebuilding.

### 3.4 Reproducible artifacts

Update artifacts persist in the repository so a rebuild is reproducible from
in-repo files.

### 3.5 Rebuild result

A successful rebuild identifies the new snapshot and produces the inference
report.

### 3.6 Not through the HTTP API

Update and rebuild requests are not accepted through the HTTP API. That API
only reads a written snapshot.
