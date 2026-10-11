"""Read table-format graph responses as records in tests."""
from data_ontology_graph.service.tables import to_records


def paths(response):
    """Path hop records grouped by path rank."""
    grouped = []
    for hop in to_records(response.hops):
        if hop["path"] == len(grouped):
            grouped.append([])
        grouped[hop["path"]].append(hop)
    return grouped


def by_id(collection, key):
    return {record[key]: record for record in to_records(collection)}
