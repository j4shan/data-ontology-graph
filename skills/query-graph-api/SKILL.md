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
and `find_connecting_subgraph`, including service errors. Object discovery and lookup calls
(`search`, `get_dataset`, `get_identity`, and `get_relationship`) are printed but do not enter
File B. Connection failures have no service response and are reported separately.

Reread both temporary files when generating the AKG. Select relevant evidence from the
traversal responses and use object lookups for additional metadata as needed. Follow the
bundled [AKG format guide](references/akg-format.md) and
[AKG schema](references/akg.schema.json). Preserve graph facts and explicit unknowns; keep
analytical reasoning separate from them. Disconnected selections are valid when the question
needs separate facts or the graph lacks a required connection.

Write the AKG to the caller's output path, or to `$GRAPH_WORK/akg.json` when none is given,
and report its location. Keep its status `draft` unless a graph-aware finalizer has validated
it. Keep both temporary files available while reviewing the selection.
