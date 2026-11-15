# Product requirements: object search

## 1. Object discovery and lookup

An agent can discover graph objects, inspect their metadata, and find datasets where selected logical entities have physical realizations.

### Capabilities

- Search logical entities, datasets, entity definitions, columns, and cross-entity relationships using deterministic lexical matching, optionally restricted by kind. Match cross-entity relationships by their descriptions. Support exact and prefix matching, plus phrase and all-words matching for multi-word dataset and logical-entity names.
- Return matching field values unchanged, with their best match type. Order results by match type, normalized label, and object key. Apply limits per kind and report omitted results.
- Exclude whole-value placeholders such as `N/A`, `unknown`, and `TBD` from description search while preserving published metadata. Names, synonyms, and tags remain searchable.
- Look up a dataset with its complete published metadata using the shared dataset structure.
- Provide `get_entity_definitions`, replacing `get_identity`, to discover datasets realizing a required primary `identity_id`.
- Support two optional filters:
  - `entity_universe`: restrict qualifying **primary entity definitions** to the selected coverage statuses.
  - `target_identity_ids`: retain datasets containing **every** selected logical entity. Allow up to **four distinct additional entities**, deduplicated and sorted. An omitted or empty list adds no restriction.
- Apply filters before counts, view selection, aggregation, and pagination. Allow any registered target entity, including entities outside the displayed histogram. Unknown entity IDs return resource-not-found; invalid filters return invalid parameters; an empty intersection returns zero counts.
- Support `auto`, `aggregated`, and `detailed` views. Under `auto`, return aggregated results above a configurable threshold of **200 distinct matching datasets**, and detailed results otherwise. Explicit view selection overrides this choice.
- Report the actual view, applied filters, exact matching-dataset count, and exact qualifying primary-entity-definition count.
- Aggregate **other logical entities** across all matching datasets, excluding the primary entity. Return the top 20 groups with entity-definition and distinct-dataset counts, ordered by descending definition count and ascending entity ID. Already-selected target entities remain visible. Report the total group count and whether histogram groups were omitted.
- Page detailed results by dataset, keeping its selected entity definitions together. Include qualifying primary definitions and definitions satisfying the target filters. Default to 100 datasets per page, with a maximum of 1,000.
- Support deterministic, stateless continuation within the same snapshot and selection scope until every matching dataset can be inspected. A null `next_cursor` indicates completion. Changing filters starts a new selection.

### Concepts

An **entity definition** is one dataset’s physical realization of a logical entity through a particular column set. Multiple roles on one dataset count as separate entity definitions but contribute once to the dataset count.

Multi-entity filtering identifies candidate bridge datasets. Dataset-level co-occurrence does not establish that particular values occur together in source records or determine the business meaning of a path.

### Exclusions

Discovery does not provide semantic-similarity search, read source records, or infer cross-entity relationships.
