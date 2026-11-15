---
name: query-graph-api
description: Discover dataset metadata and explore relationships through the local Data Ontology Graph service. Generate an abstract knowledge graph (AKG) as a surrogate objective for a SQL analytical question.
---

# Query the graph API

This skill acts as a proxy for the Data Ontology Graph service: it discovers dataset metadata
and explores relationships between datasets. For SQL analytical questions, it generates an
abstract knowledge graph (AKG) as a surrogate objective: a selection of dataset nodes,
relationship edges, and available graph properties that support answering the question.
The skill does not generate queries or translate an AKG into a query language. The service
does not currently provide data statistics.

## Skill configuration

Automatic invocation is disabled in [agents/openai.yaml](agents/openai.yaml). Invoke the skill
explicitly as `$query-graph-api` in Codex.

## Setup

The bundled tools require Python 3.12 or later and use only its standard library. The local
graph service must already be installed and configured with a published graph. Starting it
through `scripts/service.py` requires macOS and `launchctl`; a service already running on a
Unix-domain socket can be queried directly.

Run the commands below from this skill's directory. Start the service when needed:

```bash
python3 scripts/service.py start
```

`running` or `started` means it is ready. Other states include a message describing what needs
attention. The default socket is `~/.data-ontology-graph/graph.sock`. `$DOG_HOME` changes the
service home; `$DOG_SOCKET` or `--socket PATH` overrides the socket for API calls.

Create a temporary working directory outside the skill and set the original question:

```bash
GRAPH_WORK=$(mktemp -d)
GRAPH_CONTEXT="$GRAPH_WORK/question.json"
QUESTION='How many loans are there per region?'
python3 scripts/query.py snapshot_info --context "$GRAPH_CONTEXT" --question "$QUESTION"
```

Use a separate temporary directory for each analytical question. The proxy writes File A to
`$GRAPH_CONTEXT` and File B to the same path with its suffix replaced by `.traversals.md`.
In this example, the files are `question.json` and `question.traversals.md`.

## API documentation

Read [references/graph-api.md](references/graph-api.md) for the complete method catalog,
request parameters, response schemas, field selection, and traversal behavior.

Call any documented method with the bundled proxy:

```bash
python3 scripts/query.py search '{"query":"loan","kind":["dataset","identity"]}' \
  --context "$GRAPH_CONTEXT"
python3 scripts/query.py get_entity_definitions '{"identity_id":"ACCOUNT_ID"}' \
  --context "$GRAPH_CONTEXT"
python3 scripts/query.py get_edges '{"node_id":"sqlite:lending.loan"}' \
  --context "$GRAPH_CONTEXT" --entity 'Account'
```

`graph.` is optional in method names. The proxy prints the service's `result` or `error`
payload without changing its structure. `--entity NAME` adds a logical entity name to the
question file; repeat it for additional names. Use names returned by the service.
The proxy exits 0 for a result, 1 for a service or connection error, and 2 for invalid local
input. A local input error makes no API call.

## Best practices

Use discovery to identify relevant datasets and logical entities, then explore their
relationships. Select the graph knowledge that serves the analytical question, using the
datasets' grain, column descriptions, entity roles, and directional relationship claims.

Use `get_entity_definitions` to discover where a primary logical entity is defined. Its
`identity_id` is required. An optional `entity_universe` list limits primary definitions by
coverage; optional `target_identity_ids` requires every selected dataset to contain each
target entity. Up to four distinct targets can be supplied in addition to the primary. These
filters apply before counts and view selection. The returned `dataset_count` counts matching
datasets, while `primary_definition_count` counts qualifying primary roles on them.
`view: "auto"` returns `aggregated` when the filtered dataset count is greater than
`dataset_threshold` (default 200), and `detailed` at or below it. Inspect the returned `view`.
The aggregated top-20 histogram counts other logical entities across all matching datasets,
including selected non-primary targets. It can help choose target IDs for a narrower call. It has no
dataset or definition records. Request `view: "detailed"` to inspect whole-dataset pages of
qualifying primary definitions and all definitions of the selected targets. `limit` counts
datasets per page, not definitions. Both views support table and records formats.

If a detailed result has a non-null `next_cursor`, repeat the same `identity_id`,
`entity_universe`, `target_identity_ids`, `limit`, `dataset_threshold`, and `response_format`
with that cursor until `next_cursor` is null. The `view` may be `auto` or `detailed` during
continuation. `truncated` can remain true on the final page, so use `next_cursor` to detect
completion. A shared dataset is a candidate bridge; membership alone does not establish
row-level value co-occurrence or business meaning. Inspect its definitions and relationship
claims before selecting graph evidence for an AKG.

For `get_edges`, inspect the returned `view` before reading relationships. An `aggregated`
response gives exact `fan_out_count` and a top-20 `histogram` of logical entities across the
filtered connected datasets; it has no `datasets` or `edge_fields` and supplies no edge evidence.
Choose target entity IDs from the histogram or another lookup, then repeat the source
`node_id`, `identity_id`, and `from_dataset_columns` with the complete desired
`target_identity_ids` list. Each target must occur on the connected dataset, but need not occur
on the source or in the histogram. Multiple target IDs are an AND filter. These targets refine
which datasets remain; they do not change which source definitions connect to them.

Request `view: "detailed"` for concrete relationships when needed. Read its grouped directed
edges and endpoint evidence for the AKG. If `next_cursor` is non-null, repeat the original
parameters with that opaque cursor and continue until `next_cursor` is null. Keep the same
filters, `limit`, `fan_out_threshold`, `detail`, `fields`, and `response_format` on every page;
`view` may be `auto` or `detailed`. A detailed page's `truncated` can remain true on the last
page, so use `next_cursor` to decide when enumeration is complete. Each call is self-contained.
`get_entity_definitions` has its own primary and target scope; it does not apply the
`get_edges` source or target filters.

Cross-entity relationships are stated knowledge about how two logical entities relate in the
business, such as "An impression conditionally causes a click." `get_entity_relationships`
lists them at one logical entity, and `find_entity_relationship_paths` returns ranked stated
paths between two logical entities, each step carrying its descriptions. A stated path is one
way to plan a route before looking at datasets: each step can be resolved to datasets through
`get_entity_definitions` with the other logical entity as a target, and through the
relationships between those datasets. A cross-entity relationship carries no multiplicity or
match existence; those claims come from the realizing entity definitions and relationships, and
the definitions' effective descriptions distinguish roles such as a placement date and a ship
date. A step with no realizing dataset is stated knowledge the data does not hold. When no stated
path exists, dataset-level discovery remains available, and a stated path never filters
dataset-level results.

Keep two temporary files and refer to both when generating the AKG.

**File A — question and logical entities.** A JSON document:

```json
{
  "question": "How many loans are there per region?",
  "logical_entities": ["Account"]
}
```

**File B — traversal evidence.** A Markdown file with one API call per section. Each section
contains a Python literal with exactly two fields, `request` and `response`, whose values
are triple-quoted strings containing JSON:

````markdown
## graph.get_edges

```python
{
  "request": """
{"method": "graph.get_edges", "params": {"node_id": "sqlite:lending.loan"}}
""",
  "response": """
{"error": {"code": -32004, "message": "unknown dataset sqlite:lending.loan"}}
"""
}
```
````

The example illustrates an error response; successful responses keep the complete `result`.
Read each fenced Python literal as data with `ast.literal_eval`, never by importing or
executing it.

The proxy accumulates request/response pairs for `get_edges`, `expand_subgraph`, `find_paths`,
`find_entity_relationship_paths`, and `find_connecting_subgraph`, including service errors.
Object discovery and lookup calls (`search`, `get_dataset`, `get_entity_definitions`,
`get_entity_relationships`, and `get_relationship`) are printed but do not enter File B. Connection failures have no service response and are reported separately.

Reread both temporary files when generating the AKG. Use aggregated responses for discovery;
select concrete edges only from detailed traversal responses, with object lookups for additional
metadata as needed. Follow the
bundled [AKG format guide](references/akg-format.md) and
[AKG schema](references/akg.schema.json). Preserve graph facts and explicit unknowns; keep
analytical reasoning separate from them. Disconnected selections are valid when the question
needs separate facts or the graph lacks a required connection.

Write the AKG to the caller's output path, or to `$GRAPH_WORK/akg.json` when none is given,
and report its location. Keep its status `draft` unless a graph-aware finalizer has validated
it. Keep both temporary files available while reviewing the selection.
