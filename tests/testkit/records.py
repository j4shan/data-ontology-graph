"""Read graph responses as records in tests."""

from data_ontology_graph.service.tables import to_records
from data_ontology_graph.service.views import split_edge_label


def first_relationship(snapshot):
    """The relationship of the first two entity definitions of the first related logical entity."""
    index = snapshot.memberships
    keys = next(keys for _, keys in sorted(index.by_identity.items()) if len(keys) > 1)
    return index.pair(keys[0], keys[1])


def decode(fields, array, identity_id=None):
    """A directed-edge array as a record keyed by ``fields``, with its two entity definitions."""
    record = dict(zip(fields, array))
    (from_node_id, from_columns), (to_node_id, to_columns) = split_edge_label(record["edge"])
    record.update(from_node_id=from_node_id, from_dataset_columns=from_columns,
                  to_node_id=to_node_id, to_dataset_columns=to_columns)
    if identity_id is not None:
        record["identity_id"] = identity_id
    return record


def _dump(response):
    return response if isinstance(response, dict) else response.model_dump(mode="json")


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
