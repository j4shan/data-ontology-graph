"""Read graph responses as records in tests."""
import json

from data_ontology_graph.service.tables import to_records


def definition(side):
    """``(node_id, columns)`` from ``node_id[col,...]``, unquoting quoted column names."""
    node_id, _, inner = side.partition("[")
    inner = inner[:-1]
    columns, index = [], 0
    while index < len(inner):
        if inner[index] == '"':
            name, end = json.JSONDecoder().raw_decode(inner, index)
        else:
            end = inner.find(",", index)
            end = len(inner) if end < 0 else end
            name = inner[index:end]
        columns.append(name)
        index = end + 1
    return node_id, columns


def decode(fields, array, identity_id=None):
    """A directed-edge array as a record keyed by ``fields``, with its two entity definitions."""
    record = dict(zip(fields, array))
    start, end = record["edge"].split(" -> ")
    (from_node_id, from_columns), (to_node_id, to_columns) = definition(start), definition(end)
    record.update(from_node_id=from_node_id, from_dataset_columns=from_columns,
                  to_node_id=to_node_id, to_dataset_columns=to_columns)
    if identity_id is not None:
        record["identity_id"] = identity_id
    return record


def _dump(response):
    return response if isinstance(response, dict) else response.model_dump(mode="json")


def paths(response):
    """Path directed-edge records grouped by path rank."""
    data = _dump(response)
    return [[decode(data["edge_fields"], edge) for edge in path] for path in data["paths"]]


def by_id(collection, key):
    return {record[key]: record for record in to_records(collection)}


def _flatten(fields, groups):
    return [
        decode(fields, edge, group["identity_id"])
        for group in groups
        for definition in group["entity_definitions"]
        for edge in definition["edges"]
    ]


def edges(response):
    """Directed-edge records of a table-format navigation response."""
    data = _dump(response)
    return _flatten(data["edge_fields"], data.get("edge_groups") or [])


def dataset_edges(record, fields):
    """Directed-edge records of one records-format dataset."""
    return _flatten(fields, record.get("edge_groups", ()))
