"""Render an AKG document as read-only Markdown for human review.

The rendering is deterministic: the same document always yields the same text. It is never
parsed back; the JSON document stays the only source of truth.
"""

from __future__ import annotations

from typing import Any


ONE = ("1:1", "many:1")
MANY = ("1:many", "many:many")


def export_markdown(payload: dict[str, Any]) -> str:
    datasets: dict[str, Any] = payload["datasets"]
    edges = [(node_id, edge) for node_id, dataset in datasets.items()
             for edge in dataset.get("edges") or []]
    alias = _aliases(datasets, edges)
    lines = [f"# {payload['question']}", ""]
    if payload.get("objective"):
        lines += [f"**Objective:** {payload['objective']}", ""]
    status = f"**Status:** {payload['status']}"
    status += f" · **Components:** {_component_count(datasets, edges)}"
    snapshot = (payload.get("graph") or {}).get("snapshot")
    if snapshot:
        status += f" · **Snapshot:** {snapshot['version']} / {snapshot['schema_fingerprint']}"
    lines += [status, ""]

    lines += [
        "## Datasets",
        "",
        "| Alias | Dataset | Source | Grain | Role |",
        "| --- | --- | --- | --- | --- |",
    ]
    for node_id, dataset in datasets.items():
        grain = dataset.get("grain")
        grain_text = ", ".join(grain) if isinstance(grain, list) else (grain or "—")
        role = (dataset.get("usage") or {}).get("role") or "—"
        lines.append(
            f"| {alias[node_id]} | `{dataset['name']}` | {dataset['source']} | {grain_text} | {role} |"
        )
    lines.append("")

    column_rows = []
    for node_id, dataset in datasets.items():
        uses = (dataset.get("usage") or {}).get("columns") or {}
        for name in dict.fromkeys([*(dataset.get("columns") or {}), *uses]):
            facts = (dataset.get("columns") or {}).get(name) or {}
            use = uses.get(name) or {}
            usage = use.get("as", "—")
            if "value" in use and use["value"] is not None:
                usage += f" = {use['value']}"
            if use.get("note"):
                usage += f" ({use['note']})"
            column_rows.append(
                f"| {alias[node_id]}.{name} | {facts.get('description', '')} | {usage} |"
            )
    if column_rows:
        lines += ["### Columns", "", "| Column | Description | Usage |", "| --- | --- | --- |"]
        lines += column_rows + [""]

    notes = [
        f"- **{alias[node_id]}:** {dataset['usage']['note']}"
        for node_id, dataset in datasets.items()
        if (dataset.get("usage") or {}).get("note")
    ]
    stats = [
        f"- **{alias[node_id]}:** "
        + ", ".join(f"{key} = {value}" for key, value in dataset["stats"].items())
        for node_id, dataset in datasets.items()
        if dataset.get("stats")
    ]
    if notes:
        lines += ["### Dataset notes", "", *notes, ""]
    if stats:
        lines += ["### Statistics", "", *stats, ""]

    if edges:
        lines += ["## Directed edges", ""]
        for node_id, edge in edges:
            lines += _edge(node_id, edge, alias) + [""]

    comparisons = payload.get("comparisons") or {}
    if comparisons:
        lines += ["## Comparisons", ""]
        for key, comparison in comparisons.items():
            anchors = ", ".join(alias.get(node_id, node_id) for node_id in comparison["anchors"])
            shared = ", ".join(
                f"{alias.get(column['node_id'], column['node_id'])}.{column['column']}"
                for column in comparison["shared_columns"]
            )
            lines.append(f"- **{key}:** {comparison['comparison']} of {anchors} on {shared}")
        lines.append("")

    gaps = payload.get("gaps") or {}
    if gaps:
        lines += ["## Data gaps", ""]
        for key, gap in gaps.items():
            involved = [alias.get(node_id, node_id) for node_id in gap.get("datasets") or []]
            suffix = f" Involves: {', '.join(involved)}." if involved else ""
            lines.append(f"- **{key}:** {gap['description']}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _edge(node_id: str, edge: dict[str, Any], alias: dict[str, str]) -> list[str]:
    usage = edge.get("usage") or {}
    left, right = alias[node_id], alias[edge["to_node_id"]]
    lines = [
        f"### {_columns(left, edge['from_dataset_columns'])} → "
        f"{_columns(right, edge['to_dataset_columns'])}",
        "",
        f"- {_claim(left, right, edge['multiplicity'], edge['match_existence'])}",
        f"- {_claim(right, left, edge['reverse_multiplicity'], edge['reverse_match_existence'])}",
    ]
    if usage.get("keep"):
        kept = ", ".join(alias.get(kept, kept) for kept in usage["keep"])
        lines.append(f"- Keep unmatched rows of: {kept}")
    if usage.get("aggregate_before_join"):
        lines.append(f"- Aggregate {right} to the grain of {left} before combining.")
    if usage.get("note"):
        lines.append(f"- Note: {usage['note']}")
    if edge.get("stats"):
        stats = ", ".join(f"{key} = {value}" for key, value in edge["stats"].items())
        lines.append(f"- Statistics: {stats}")
    return lines


def _claim(origin: str, target: str, multiplicity: str, existence: str) -> str:
    if multiplicity in ONE:
        count = ("exactly one" if existence == "always" else "at most one") + f" {target} row"
    elif multiplicity in MANY:
        count = ("one or more" if existence == "always" else "any number of") + f" {target} rows"
    else:
        count = f"an unknown number of {target} rows"
    if existence == "always":
        return f"Every {origin} row matches {count}."
    if existence == "optional":
        return f"Each {origin} row matches {count}; some match none."
    return f"Each {origin} row matches {count}; whether every {origin} row matches is unknown."


def _columns(alias: str, columns: list[str]) -> str:
    return " + ".join(f"{alias}.{column}" for column in columns)


def _aliases(datasets: dict[str, Any], edges: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    node_ids = list(datasets)
    for _, edge in edges:
        if edge["to_node_id"] not in node_ids:
            node_ids.append(edge["to_node_id"])
    names = {
        node_id: datasets[node_id]["name"] if node_id in datasets else node_id
        for node_id in node_ids
    }
    short = {node_id: name.rsplit(".", 1)[-1] for node_id, name in names.items()}
    counts: dict[str, int] = {}
    for value in short.values():
        counts[value] = counts.get(value, 0) + 1
    return {
        node_id: short[node_id] if counts[short[node_id]] == 1 else names[node_id]
        for node_id in node_ids
    }


def _component_count(datasets: dict[str, Any], edges: list[tuple[str, dict[str, Any]]]) -> int:
    parent = {node_id: node_id for node_id in datasets}

    def root(node_id: str) -> str:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    for a, edge in edges:
        b = edge["to_node_id"]
        if b in parent:
            parent[root(a)] = root(b)
    return len({root(node_id) for node_id in parent})
