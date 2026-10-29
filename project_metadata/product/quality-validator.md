# Product requirements: knowledge quality validator

The quality validator checks whether published knowledge gives an AI agent the context a person
would use for the same task. It is a planned capability, not part of the initial release.

## Scope

| ID | Clause |
| --- | --- |
| 1.1 | The quality validator runs independently of the validation that gates graph construction and publication. It reports findings and never changes knowledge. |
| 1.2 | A finding is measured against the graph model's purpose ([graph-model.md](graph-model.md) clause 0.1): the knowledge should let an agent resolve ambiguity with the same quality a person would, given the same context. |
| 1.3 | Each finding names the affected entity definitions and columns and the reason, so a data owner can correct the knowledge at its source. |

## Column context of entity definitions

| ID | Clause |
| --- | --- |
| 2.1 | The graph does not record which column of one composite entity definition corresponds to which column of another ([graph-model.md](graph-model.md) clause 1.6). In production, a person pairs them by comparing the columns' text or meaning, and an agent reaches the same quality given the same context. Column descriptions are therefore most useful as part of the entity definition they belong to. |
| 2.2 | The validator flags a composite entity definition with a column that has no description. |
| 2.3 | The validator flags a composite entity definition whose column descriptions are too alike to tell its columns apart. |
| 2.4 | The validator flags two composite definitions of the same logical entity whose columns cannot be paired one to one by the text or semantic similarity of their names and descriptions. |
