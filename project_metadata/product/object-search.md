# Product requirements: object search

## 1. Object discovery and lookup

An agent can discover candidate graph objects and inspect their published metadata.
The graph model defines the objects and their properties.

### Capabilities

- Search logical entities, datasets, entity definitions, and columns using deterministic
  local lexical matching, optionally restricted to selected kinds. Matching supports
  `exact` and `prefix`; multi-word queries additionally support `phrase` and `all_words`
  against dataset qualified names, dataset display names, and logical-entity names.
- Report every matching indexed field value unchanged, with its best match type.
  Results are ordered by best match type, normalized label, and object key.
- Exclude whole-value placeholders such as `N/A`, `unknown`, and `TBD` from description
  and value-description search terms while preserving the original metadata. Text
  merely containing such a word is indexed normally; names, synonyms, and tags are
  unaffected.
- Apply a caller-selected result limit separately to each searched kind, within the
  supported maximum. Report when eligible results are omitted.
- Look up a logical entity with its physical entity definitions and their datasets.
  An optional universe filter applies before a limit on entity definitions, and the
  response reports truncation.
- Look up a dataset with its complete published metadata, as defined in
  product/graph-model.md. Dataset records in lookup responses use the same structure
  as navigation dataset records, with fields appropriate to the operation.

### Exclusions

Search provides lexical candidates, without semantic-similarity or general full-text
retrieval.
