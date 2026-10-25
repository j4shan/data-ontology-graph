---
name: query-graph-api
description: Build an abstract knowledge graph (AKG) for one analytical objective by querying the Data Ontology Graph service and recording the selected datasets, directed edges, and reasoning in a local AKG file through bundled tools, then finalize it against the graph. Use when a question must be answered with the datasets and relationships of a published graph snapshot, including questions about disjoint facts or questions the data model cannot fully connect.
---

# Query the graph API

Build one AKG file for one objective. An AKG is the subset of graph datasets the objective
needs, keyed by `node_id`, each holding the directed edges you traverse from it, with your
reasoning recorded beside them.
Disconnected components are a valid answer: the objective may need disjoint facts, or the graph
may lack a needed connection, which you record as a data gap. You never type graph facts into
the file: `scripts/akg.py` copies them from the service. Field definitions are in
[references/akg-format.md](references/akg-format.md); the
[AKG schema](../../resources/schema/akg.schema.json) is the authority.

This skill needs the local graph service, set up on this machine, and a writable working
directory. The service runs only on demand; step 0 starts it.

## 0. Connect

Run the scripts from this skill's directory. Start the service and set the AKG file once. Put the
file in a writable directory the caller names, never inside this skill; the default is
`./akg.json`.

```bash
python3 scripts/service.py start
export AKG_FILE=<writable path given by the caller, default ./akg.json>
```

`start` prints one JSON line. `running` or `started` means the service answers; go on. Any
other `state` (`not_set_up`, `not_ready`, `blocked`) comes with a `message`: relay it to the user
and stop; do not answer from memory. Every script finds the service by itself; set `DOG_SOCKET`
only when the caller gives a different socket. `python3 scripts/service.py stop` stops the
service when the caller asks for it.

Discovery command form: `python3 scripts/graph_call.py <method> '<params JSON>'`. Output is a
compact projection; add `--full` only when a field you need is missing. In `--full` output, each
directed edge is an array whose positions the response's `edge_fields` names, starting with
`"start[columns] -> end[columns]"` and ending with `edge_id`.

| Method | Params | Use |
| --- | --- | --- |
| `snapshot_info` | none | The served snapshot; a connection check. |
| `search` | `{"query": str, "kind"?: [str], "limit"?: int}` | Candidate datasets, columns, logical entities, entity definitions. |
| `get_dataset` | `{"node_id": str}` | Grain, columns with descriptions, entity definitions. |
| `get_identity` | `{"identity_id": str, "entity_universe"?: [str], "limit"?: int}` | Every dataset that realizes one logical entity. |
| `get_edges` | `{"node_id": str, "limit"?: int, "identity_id"?: str, "from_dataset_columns"?: [str]}` | One dataset's edges. `groups` has one line per entity definition on the dataset, `node[columns] logical-entity-ID listed/total`, marked `truncated` when its list was cut; `limit` (default 200, at most 1000) caps each entity definition's list, so every join column stays visible. `identity_id`, optionally with `from_dataset_columns`, lists only those entity definitions. `edges` has one `{edge_id, step}` entry per listed directed edge leaving it, where `step` reads `from[columns] "description" -> to[columns] "description" logical-entity-ID claims | reverse claims`. Claims always move away from the `from` dataset. Each endpoint's description says what its columns identify, which tells apart relationships that join the same datasets in different roles. A dataset with two columns of one logical entity, such as a link table, lists one directed edge from each column. |
| `find_paths` | `{"from_node_id", "to_node_id", "max_edges"?, "limit"?}` | The `limit` shortest routes (default 6, `max_edges` default 4), one line each, fan-out-free first. A route may pass through a dataset twice on different columns, such as an employee's manager's department. `fan_out` counts directed edges that multiply rows (`1:many`, `many:many`); `unknown` counts directed edges with an unknown claim. Add `--detail` for each route's `{edge_id, step}` directed edges. |
| `get_relationship` | `{"edge_id": str, "from_node_id"?: str, "from_dataset_columns"?: [str]}` | One relationship; with `from_node_id`, `edge` is the directed edge leaving that dataset. Name `from_dataset_columns` when both endpoints lie on that dataset. |
| `expand_subgraph` | `{"seed_node_ids": [..], "max_depth": 1}` | Neighbourhood listing: each dataset with its edge count, and the seeds' `groups` and directed edges, as in `get_edges`. Use depth 1 only. |

Navigation methods (`get_edges`, `find_paths`, `expand_subgraph`) also take `detail`:
`essential` for wide, light exploration; `standard`, the default, adds descriptions and reverse
claims; `full` adds columns and entity definitions for validation. `fields` adds named fields to a
level, such as `{"edge": ["annotation"]}`. Detail levels never change limits.

Send `node_id` and `edge_id` values exactly as responses print them, such as
`sqlite:shop.fact_sale`. Never construct an ID from a name.

File command form: `python3 scripts/akg.py <command> "$AKG_FILE" ...`. Each command prints one
JSON line; an `error` means the file is unchanged. A `PATCH` argument is JSON text, `-` to read
it from standard input, or `@path` to read it from a file, which avoids shell quoting.

| Command | Use |
| --- | --- |
| `init FILE --question Q [--objective O]` | Create the draft. Once per objective. |
| `add-dataset FILE NODE_ID... [--detail essential\|standard\|full] [--columns c1,c2]` | Copy datasets from the service. Repeat with more columns or detail to fill in missing fields; present fields never change. |
| `add-edge FILE NODE_ID EDGE_ID... [--from-columns c1,c2] [--no-endpoints]` | Copy directed edges leaving `NODE_ID` into that dataset, adding both end datasets and their join columns. Name `--from-columns` when both ends lie on `NODE_ID`. |
| `remove FILE KEY... [--cascade]` | Drop a dataset (`node_id`) or every directed edge of a relationship (`edge_id`). Refuses while something refers to it unless `--cascade`. |
| `exists FILE KEY...` | Check whether datasets or edges are in the file. |
| `show FILE [--full]` | Read the current file: one line per dataset, then its directed edges. |
| `annotate FILE KEY PATCH [--from NODE_ID] [--from-columns c1,c2]` | Merge-patch a dataset's or directed edge's `usage`. `null` deletes a field. For an `edge_id` held by more than one directed edge, name the one with `--from`. |
| `migrate FILE` | Convert a file written with the earlier `relationships` map. Other commands refuse such a file. |
| `gap FILE ID PATCH`, `comparison FILE ID PATCH` | Merge-patch a data gap or comparison; `null` as the patch deletes it. |

## 1. Decompose the question

Before any call, write these lists in your scratch notes:

- **Measures**: quantities or counts the question compares.
- **Groupings**: populations the answer is grouped by.
- **Filters and conditions**: status values, thresholds, "no X", "never X", "only one X".
- **Time**: the period the comparison runs across, and which event it dates.
- **Populations that must stay visible when unmatched**: "including … never shipped", "no
  receipt", "absent from". Each needs an `optional` side on the relationship that keeps it,
  recorded as `keep` in step 6.
- **Readings**: when the question supports more than one reasonable interpretation, list each.
  Each materially different reading is its own objective and its own AKG file; never merge
  readings into one.
- **Facts**: when the question asks for several facts that need not be related ("list X, and
  separately Y"), note each one. Unrelated facts become separate components of one file.

## 2. Find candidate datasets

1. Search the business phrase from the question first (`production schedule`), then its head noun
   (`schedule`), then a shorter stem (`calibrat`). Add `kind` when you know the evidence type:
   `dataset` and `column` for measures and filters, `identity` and `entity_definition` for keys.
2. Each group lists `hits`, one line per subject in the form
   `subject <- match_type:match_field='matched_value'; ...`. Compare `matched_value` with the
   query to tell a whole-name match from a word inside a longer name, and use `match_field` to
   tell a name or synonym match from a description match. A match on a dataset's `node_id` or
   `qualified_name` is strong evidence. Hit order is by match type, not relevance.
3. Multi-word queries match words in any order (`all_words`) or in sequence (`phrase`) only inside
   dataset names and logical-entity names. Other fields, including columns, match a multi-word query
   only when they start with the phrase, so search columns by one word.
4. `entity_definition` and `identity` hits mean the concept is a key: call `get_identity` and take
   the dataset whose universe is `complete` as the population dataset. When none is `complete`,
   take the dataset whose grain is that logical entity and record a data gap: the population may be
   incomplete.
5. When a group reports `truncated: true`, repeat with a larger `limit` (up to 200) or with `kind`
   set to that group before concluding a dataset is absent.

## 3. Confirm each candidate

Call `get_dataset` on every candidate you intend to keep. Keep a dataset only if one of these holds:

- its grain is the event or population a measure counts;
- it holds a column needed as a measure, grouping, filter, or time;
- it is a required intermediate on a selected path (step 4).

Never cite a column that is not in that dataset's `columns`.

## 4. Choose anchors and connect them

1. **Anchor** = the dataset whose grain carries a measure. Measures from different events give one
   anchor per event.
2. Call `get_edges` once per anchor. Prefer a single directed edge to a grouping dataset over a path.
3. Otherwise call `find_paths` with `max_edges` 4. Never use `max_edges` above 5.
4. Choose a path with these rules, in order:
   1. A `1:many` or `many:many` step away from the anchor multiplies anchor rows (fan-out). Reject
      it for a grouping dataset. Accept it only when the question counts or sums that child
      population, or compares two facts, and then aggregate the far side to the anchor's grain
      before combining: set `aggregate_before_join` on that relationship in step 6.
   2. Prefer the path whose columns carry the meaning the question asks for. Read column
      descriptions: the store of a sale line is the store on its sale, not the home store of the
      cashier. Prefer the anchor's own business process over chains through an actor attribute
      (employee, shift, user) unless the question groups by that actor.
   3. Reject role-playing columns whose description names a different role.
   4. Prefer fewer directed edges only after rules 1–3.
5. **Two or more anchors** (drill-across): connect each anchor separately to the shared grouping
   datasets. Do not chain anchor → dimension → anchor as one path. Record a comparison in step 6
   with the anchors, the shared grouping columns, and the comparison type (`coverage`,
   `difference`, or `co_occurrence`).
6. When `find_paths` is `truncated` with no acceptable path, call `get_edges` on the anchor and the
   grouping dataset and look for a common neighbour before raising `limit`.

## 5. Record the selection

Start the file once the anchors from step 4 are confirmed, then add each element as you decide
on it rather than at the end:

```bash
python3 scripts/akg.py init "$AKG_FILE" --question "<question verbatim>" --objective "<reading you adopted>"
python3 scripts/akg.py add-dataset "$AKG_FILE" <anchor node_id> --columns <measure>,<filter>
python3 scripts/akg.py add-edge "$AKG_FILE" <anchor node_id> <edge_id>
python3 scripts/akg.py add-edge "$AKG_FILE" <next node_id> <edge_id>
python3 scripts/akg.py add-dataset "$AKG_FILE" <grouping node_id> --columns <grouping column>
```

- Take `edge_id` values from `get_edges` entries or `find_paths --detail` directed edges, and
  add each from the dataset the step leaves, starting on the anchor side. The directed edge's
  claims then read in traversal order. Add only the directed edges on the chosen paths and
  single directed edges. Two datasets in the file do not bring along other edges between them.
- Add every column you will name in step 6 with `--columns`. `essential` detail is the default;
  use `standard` only when a reviewer needs the full column list or entity definitions.
- Unrelated facts from step 1 stay in the same file as separate components.
- When the objective needs a connection the graph lacks, or one that exists only through columns
  with a different meaning (step 4 rules 2–3), leave the datasets unconnected and record a gap in
  step 6. Never add an edge only to connect components.
- When you change your mind, `remove` the element; it refuses while reasoning still refers to it.
- Use `show` to re-read the file instead of keeping it in your context.

A question with two materially different readings is two objectives: build one file per
reading, preferred reading first, and never merge them. Unless the caller names the files, add
a suffix to `AKG_FILE` for each further reading, such as `akg.reading-2.json`. A path that
step 4 rejects is not a reading; record the rejection in a note or gap instead.

## 6. Write the reasoning

Reasoning goes only into `usage`, gaps, and comparisons, never into graph fields.

- **Roles**: `annotate` each anchor with `{"role": "anchor"}`; other datasets may take
  `grouping`, `filter`, or `bridge`.
- **Columns**: one entry per column the answer measures, counts, groups by, filters on, dates
  by, tests for absence, or outputs, as `{"columns": {"<column>": {"as": "<use>"}}}` where
  `<use>` is `measure`, `count`, `group`, `filter`, `time`, `absence` (anti-join), `join_only`,
  or `output`. Join keys need no entry unless the answer also uses them otherwise. Group by the
  column that defines the grouping, and list a separate label column as `output`. Put a stated
  filter value or threshold in `"value"`.
- **Direction**: the dataset that holds a directed edge is where traversal starts, so step 5
  already oriented it. Never edit the claims; to traverse the other way, `remove` the edge and
  `add-edge` it from the other end.
- **Unmatched populations**: for each population that must stay visible, `annotate` every
  directed edge along its path that could drop its rows, not only the first, with
  `{"keep": ["<node_id>"]}`, and say which join that implies in `"note"`, as in "account LEFT
  JOIN loan keeps accounts with no loan". The edge stays in the anchor-side dataset even when the
  kept dataset is its end.
- **Fan-out**: set `{"aggregate_before_join": true}` where step 4 rule 1 requires it.
- `unknown` match existence never proves that a join keeps or drops records. Choose the
  preserved side the objective needs, say so in the note, and record a gap.
- **Drill-across**: `comparison FILE <id> '{"anchors": [...], "shared_columns": [{"node_id": ..., "column": ...}], "comparison": "coverage|difference|co_occurrence"}'`.
- **Gaps**: `gap FILE <id> '{"description": ..., "datasets": [...]}'`, naming directed edges as
  `"edges": [{"node_id": ..., "edge_id": ...}]`, for each missing
  connection or concept, unresolved threshold ("high", "few"), missing time scope, implicit
  population (such as active employees), and `unknown` claim the answer depends on.

## 7. Finalize

```bash
data-ontology-graph-akg finalize "$AKG_FILE"
```

If the command is not on `PATH`, run it from this skill's directory as
`uv run --project ../.. data-ontology-graph-akg finalize "$AKG_FILE"`;
the repository root is two levels up. `data-ontology-graph-akg check` reports the same findings
without changing the file. Fix every `error` with the tools, never by hand-editing graph fields,
and finalize again. Finish only when it prints `final`; any later `akg.py` write returns the file
to `draft`.

Then check what the checker cannot:

- [ ] Every measure, grouping, filter, and time item from step 1 maps to a column usage.
- [ ] Every unmatched-population phrase maps to a `keep` with a note, or to a gap.
- [ ] Every separate component is explained by a disjoint fact or a gap.
- [ ] Each reading of the question has its own file, preferred reading first.

## Call budget

Aim for at most 30 `graph_call.py` calls per objective, not counting `akg.py` commands. Do not call
`expand_subgraph` with `max_depth` above 1. Do not call `get_edges` on a hub dimension (calendar day, location,
product) unless it is the anchor; its list of directed edges is large and mostly unrelated facts.
