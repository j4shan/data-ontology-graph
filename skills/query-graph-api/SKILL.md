---
name: query-graph-api
description: Resolve one analytical question into abstract knowledge graphs (AKGs) by querying the Data Ontology Graph service, then validate the result against the public AKG contract. Use when a question must be answered with the datasets and relationships of a published graph snapshot, including questions about disjoint facts or questions the data model cannot fully connect.
---

# Query the graph API

Produce one AKG document for one question. An AKG is a forest of one or more graph cuts: each
cut is a connected set of nodes and edges copied verbatim from the served snapshot. Disconnected
cuts are a valid answer. The question may ask for disjoint facts, or the graph may lack a needed
connection, which you record as a data gap. Field definitions are in
[references/akg-format.md](references/akg-format.md); the
[AKG schema](../../resources/schema/akg.schema.json) is the authority.

## 0. Connect

Call the service through `scripts/graph_call.py`, relative to this skill's directory. Set the
socket once:

```bash
export DOG_SOCKET=<socket path given by the caller>
python3 scripts/graph_call.py snapshot_info
```

Record `version` and `schema_fingerprint` for the document's `snapshot`. If the call fails, stop
and report the error; do not answer from memory.

Command form: `python3 scripts/graph_call.py <method> '<params JSON>'`. Output is a compact
projection; add `--full` only when a field you need is missing.

| Method | Params | Use |
| --- | --- | --- |
| `search` | `{"query": str, "kind"?: [str], "limit"?: int}` | Candidate datasets, columns, identities, entity definitions. |
| `get_dataset` | `{"node_id": str}` | Grain, columns with descriptions, entity definitions. |
| `get_identity` | `{"identity_id": str, "entity_universe"?: [str], "limit"?: int}` | Every dataset that realizes one logical identity. |
| `get_hops` | `{"node_id": str, "limit"?: int}` | Relationships touching one dataset: one `{edge_id, step}` entry per hop, where `step` reads `from[columns] -> to[columns] identity direction | reverse direction`. |
| `find_paths` | `{"from_node_id", "to_node_id", "max_hops", "limit"?}` | Ranked paths, one line each, fan-out-free first. `fan_out` counts steps that multiply rows (`1:many`, `many:many`); `unknown` counts steps with an unknown claim. Default `limit` is 10. Add `--detail` for each path's `{edge_id, step}` hops. |
| `get_relationship` | `{"edge_id": str, "from_node_id"?: str}` | One relationship; with `from_node_id`, `direction` moves away from that dataset. |
| `expand_subgraph` | `{"seed_node_ids": [..], "max_depth": 1}` | Neighbourhood listing. Use depth 1 only. |
| `cut` | `{"node_ids": [..], "edge_ids": [..]}` | Client-side: prints one cut in the contract's graph model, copied from the service. |

Send `node_id` and `edge_id` values exactly as responses print them, such as
`sqlite:lending.loan`. Never construct an ID from a name.

## 1. Decompose the question

Before any call, write these lists in your scratch notes:

- **Measures**: quantities or counts the question compares.
- **Groupings**: populations the answer is grouped by.
- **Filters and conditions**: status values, thresholds, "no X", "never X", "only one X".
- **Time**: the period the comparison runs across, and which event it dates.
- **Populations that must stay visible when unmatched**: "including … never shipped", "no
  receipt", "absent from". Each needs an `optional` side on the relationship that keeps it.
- **Readings**: when the question supports more than one reasonable interpretation, list each.
  Each reading becomes its own AKG; never merge readings into one.
- **Facts**: when the question asks for several facts that need not be related ("list X, and
  separately Y"), note each one. Unrelated facts become separate cuts.

## 2. Find candidate datasets

1. Search the business phrase from the question first (`production schedule`), then its head noun
   (`schedule`), then a shorter stem (`calibrat`). Add `kind` when you know the evidence type:
   `dataset` and `column` for measures and filters, `identity` and `entity_definition` for keys.
2. Read each group's `subject_rows` and `match_rows`, joined by `key`. Compare `matched_value`
   with the query to tell a whole-name match from a word inside a longer name, and use
   `match_field` to tell a name or synonym match from a description match. A match on a
   dataset's `node_id` or `qualified_name` is strong evidence. Row order is by match type, not
   relevance.
3. Multi-word queries match words in any order (`all_words`) or in sequence (`phrase`) only inside
   dataset names and identity names. Other fields, including columns, match a multi-word query
   only when they start with the phrase, so search columns by one word.
4. `entity_definition` and `identity` hits mean the concept is a key: call `get_identity` and take
   the dataset whose universe is `complete` as the population dataset. When none is `complete`,
   take the dataset whose grain is that identity and record a data gap: the population may be
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
2. Call `get_hops` once per anchor. Prefer a direct hop to a grouping dataset over a path.
3. Otherwise call `find_paths` with `max_hops` 4. Never use `max_hops` above 5.
4. Choose a path with these rules, in order:
   1. A `1:many` or `many:many` step away from the anchor multiplies anchor rows (fan-out). Reject
      it for a grouping dataset. Accept it only when the question counts or sums that child
      population, or compares two facts, and then aggregate the far side to the anchor's grain
      before combining: set `aggregate_before_join: true` on that traversal.
   2. Prefer the path whose columns carry the meaning the question asks for. Read column
      descriptions: the store of a sale line is the store on its sale, not the home store of the
      cashier. Prefer the anchor's own business process over chains through an actor attribute
      (employee, shift, user) unless the question groups by that actor.
   3. Reject role-playing columns whose description names a different role.
   4. Prefer fewer hops only after rules 1–3.
5. **Two or more anchors** (drill-across): connect each anchor separately to the shared grouping
   datasets. Do not chain anchor → dimension → anchor as one path. Record a `drill_across` entry
   with the anchors, the shared grouping columns, and the comparison (`coverage`, `difference`, or
   `co_occurrence`).
6. When `find_paths` is `truncated` with no acceptable path, call `get_hops` on the anchor and the
   grouping dataset and look for a common neighbour before raising `limit`.

## 5. Shape the forest

Group the selected datasets into cuts. A cut is the datasets joined by the edges you selected.

- Select edges explicitly: only the edges on the chosen paths and direct hops. Two datasets in the
  same cut do not bring along other edges between them.
- Unrelated facts from step 1 go in separate cuts.
- When the question needs a connection that the graph lacks, or that exists only through columns
  with a different meaning (step 4 rules 2–3), keep the datasets in separate cuts and record a data
  gap. Never add an edge only to join cuts.
- No dataset appears in two cuts of the same AKG.

## 6. Copy each cut

For each cut, run:

```bash
python3 scripts/graph_call.py cut '{"node_ids": [...], "edge_ids": [...]}'
```

Take `edge_ids` from the `edge_id` of `get_hops` entries or `find_paths --detail` hops. Write the
document as JSON, which is valid YAML, so each `cut` output goes into `cuts` unchanged as one
element. Never edit a node, edge, or identity value. The validator compares each value with the
snapshot, including explicit `unknown` claims.

## 7. Write the reasoning

Reasoning carries everything that is not a graph element. Refer to datasets by `node_id` and to
columns by `node_id` plus `column`:

- `anchors`: the anchor datasets.
- `attributes`: one entry per column the answer measures, counts, groups by, filters on, dates
  by, tests for absence, or outputs. `usage` is `measure`, `count`, `group`, `filter`, `time`,
  `absence` (anti-join), `join_only`, or `output`. Join keys need no entry unless the answer also
  uses them otherwise. Group by the column that defines the grouping, and list a separate label
  column as `output`. Put a stated filter value or threshold in `value`.
- `traversals`: one entry per selected edge, from the anchor side. `origin` and `target` are the
  edge's entity-definition references, with `node_id`, `identity_id`, and `dataset_columns`. Take
  both directions from the `step` of the `get_hops` or `find_paths --detail` entry you used.
- Unmatched populations: for each population that must stay visible, name the preserved dataset
  and the join it implies in that traversal's `note`, even when the preserved dataset is the
  traversal's target, as in "account LEFT JOIN loan keeps accounts with no loan".
- `unknown` match existence never proves that a join keeps or drops records. Choose the join that
  keeps the population the question needs, say so in the note, and record a data gap.
- `drill_across` from step 4.
- `data_gaps`: one entry per missing connection or concept, unresolved threshold ("high", "few"),
  missing time scope, implicit population (such as active employees), and `unknown` claim the
  answer depends on. Name the cuts involved by zero-based index, and the nodes involved.

## 8. Validate

```bash
data-ontology-graph-akg validate AKG_FILE --socket "$DOG_SOCKET"
```

If the command is not on `PATH`, run it from this skill's directory as
`uv run --project ../.. data-ontology-graph-akg validate AKG_FILE --socket "$DOG_SOCKET"`; the
repository root is two levels up. Fix every finding and
validate again. Finish only when it prints `valid against the contract and snapshot`.

Then check what the validator cannot:

- [ ] Every measure, grouping, filter, and time item from step 1 maps to an attribute.
- [ ] Every unmatched-population phrase maps to an `optional` side named in a traversal note, or
      to a data gap.
- [ ] Every separate cut is explained by a disjoint fact or a data gap.
- [ ] Each reading of the question is its own AKG, preferred reading first.

## Call budget

Aim for at most 30 service calls per question, not counting `cut`. Do not call `expand_subgraph`
with `max_depth` above 1. Do not call `get_hops` on a hub dimension (calendar day, location,
product) unless it is the anchor; its hop list is large and mostly unrelated facts.
