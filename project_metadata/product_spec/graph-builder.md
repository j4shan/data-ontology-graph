# Graph Builder

The Graph Builder is the only mechanism that creates join relationships. It
turns catalog evidence and curated metadata into a versioned snapshot.

## 2 Builder is the only edge writer

No other component inserts, edits, or deletes a join relationship.

### 2.1 Inputs

Inputs are catalog metadata and curated overlays. Authored edge files are not
accepted.

### 2.2 Evidence channels

Declared evidence comes from foreign-key declarations. Inferred evidence comes
from complete Logical Column Name coverage of a registered entity key.

### 2.3 Construction sequence

Construction follows the sequence and guardrails in
[project-description.md](../../project-description.md) Part 2, including grain
synthesis, composite-key child-entity decomposition, precedence-aware merge,
and replica resolution.

### 2.4 Snapshot and inference report

A rebuild writes a new versioned snapshot and an inference report with
declared, inferred, unresolved, self-referential, and total relationship
counts.

### 2.5 Contradiction report

Contradictions between distinct relationship identities are detected by a
separate validation, reported, and never auto-resolved. That check is not part
of the normal build sequence.
