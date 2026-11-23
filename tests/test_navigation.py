"""Directed edges at a dataset over the lending catalog
(product graph-navigation; system design 2.3.2-2.3.3, 2.3.8, 2.3.10).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from data_ontology_graph.model.dataset import DefinitionKey
from data_ontology_graph.service.tables import to_records
from testkit.builders import same_dataset_service
from testkit.records import by_id, dataset_edges, decode
from testkit.records import edges as edge_records


def _definitions(response):
    """(logical entity ID, start columns, listed end node_ids, edge_count, truncated) per definition."""
    return [
        (group["identity_id"], definition["dataset_columns"],
         [decode(response.edge_fields, edge)["to_node_id"] for edge in definition["edges"]],
         definition["edge_count"], definition["truncated"])
        for group in response.edge_groups
        for definition in group["entity_definitions"]
    ]


def test_edges_are_grouped_by_entity_definition_and_limited_per_definition(lending_service) -> None:
    service = lending_service
    account = "sqlite:lending.account"
    complete = service.get_dataset_edges(account)
    assert complete.limit == 200 and complete.truncated is False
    # Groups follow logical entity ID, then columns; edges follow the end node_id.
    assert _definitions(complete) == [
        ("account_identity", ["account_id"],
         ["sqlite:lending.account_holder", "sqlite:lending.loan"], 2, False),
        ("region_identity", ["region_id"],
         ["sqlite:lending.customer", "sqlite:lending.region"], 2, False),
    ]
    assert {group["node_id"] for group in complete.edge_groups} == {account}

    # A limit of 1 still shows every entity definition.
    limited = service.get_dataset_edges(account, limit=1)
    assert _definitions(limited) == [
        ("account_identity", ["account_id"], ["sqlite:lending.account_holder"], 2, True),
        ("region_identity", ["region_id"], ["sqlite:lending.customer"], 2, True),
    ]
    assert limited.truncated is True
    # Only the targets of listed edges are returned.
    assert set(by_id(limited.datasets, "node_id")) == {
        account, "sqlite:lending.account_holder", "sqlite:lending.customer",
    }
    assert service.get_dataset_edges(account, limit=2).truncated is False
    with pytest.raises(ValidationError):
        service.get_dataset_edges(account, limit=0)
    with pytest.raises(ValidationError):
        service.get_dataset_edges(account, limit=1001)


def test_edges_filter_by_logical_entity_and_start_columns(lending_service) -> None:
    service = lending_service
    account = "sqlite:lending.account"
    region = service.get_dataset_edges(account, identity_id="region_identity")
    assert [definition[:2] for definition in _definitions(region)] == [
        ("region_identity", ["region_id"]),
    ]
    assert set(by_id(region.datasets, "node_id")) == {
        account, "sqlite:lending.customer", "sqlite:lending.region",
    }
    exact = service.get_dataset_edges(account, identity_id="region_identity",
                              from_dataset_columns=["region_id"])
    assert _definitions(exact) == _definitions(region)
    with pytest.raises(ValueError, match="no entity definition of 'loan_identity'"):
        service.get_dataset_edges(account, identity_id="loan_identity")
    with pytest.raises(ValueError, match="no entity definition"):
        service.get_dataset_edges(account, identity_id="region_identity",
                          from_dataset_columns=["account_id"])
    with pytest.raises(ValidationError, match="requires identity_id"):
        service.get_dataset_edges(account, from_dataset_columns=["region_id"])


def test_directed_edges_nest_in_their_datasets_and_every_target_is_returned(lending_service) -> None:
    service = lending_service
    account = "sqlite:lending.account"
    edges = service.get_dataset_edges(account, response_format="records").model_dump(mode="json")
    datasets = {record["node_id"]: record for record in edges["datasets"]}
    seed = datasets.pop(account)
    seed_edges = dataset_edges(seed, edges["edge_fields"])
    assert seed["distance"] == 0 and len(seed_edges) == seed["edge_count"] == 4
    # Neighbours are boundary datasets: they report their edge count and list no edges.
    assert all(
        "edge_groups" not in record and record["distance"] == 1 for record in datasets.values()
    )
    assert {edge["to_node_id"] for edge in seed_edges} == set(datasets)

    relationship = service.get_relationship(seed_edges[0]["edge_id"])
    assert set(by_id(relationship.datasets, "node_id")) == {
        relationship.endpoint_a["node_id"], relationship.endpoint_b["node_id"],
    }
    assert len(to_records(relationship.entity_definitions)) == 2


def test_a_same_dataset_relationship_gives_one_directed_edge_from_each_endpoint(tmp_path: Path) -> None:
    service = same_dataset_service(tmp_path)
    link = "net.device_link"
    memberships = service.index.memberships
    edge_id = memberships.edge_id(
        DefinitionKey("net.device_link", "device", ("device_a",)),
        DefinitionKey("net.device_link", "device", ("device_b",)),
    )
    own = [edge for edge in edge_records(service.get_dataset_edges(link)) if edge["edge_id"] == edge_id]
    assert [(edge["from_dataset_columns"], edge["to_dataset_columns"]) for edge in own] == [
        (["device_a"], ["device_b"]), (["device_b"], ["device_a"]),
    ]
    from_a, from_b = own
    assert (from_a["match_existence"], from_a["reverse_match_existence"]) == ("unknown", "optional")
    assert (from_b["match_existence"], from_b["reverse_match_existence"]) == ("optional", "unknown")
    assert (from_a["from_description"], from_a["to_description"]) == (
        "source device", "target device",
    )

    # One logical entity, two entity definitions: each keeps its own list under a limit of 1.
    [group] = service.get_dataset_edges(link, limit=1).edge_groups
    assert group["identity_id"] == "device"
    assert [(d["dataset_columns"], d["edge_count"], len(d["edges"]))
            for d in group["entity_definitions"]] == [(["device_a"], 2, 1), (["device_b"], 2, 1)]

    with pytest.raises(ValueError, match="name from_dataset_columns"):
        service.get_relationship(edge_id, link)
    detail = service.get_relationship(edge_id, link, from_dataset_columns=["device_b"])
    directed = decode(detail.edge_fields, detail.edge)
    assert directed["from_dataset_columns"] == ["device_b"]
    assert directed["match_existence"] == "optional"


def test_default_bounds_do_not_depend_on_detail(lending_service) -> None:
    service = lending_service
    seeds = ["sqlite:lending.account"]
    levels = ("essential", "standard", "full")
    assert [service.get_dataset_edges(seeds[0], detail=level).limit for level in levels] == [200] * 3


def test_traversal_reports_unknown_claims_relative_to_direction(example_service) -> None:
    service = example_service
    [listed] = edge_records(service.get_dataset_edges("dataset_a"))
    edge_id = listed["edge_id"]

    relationship = service.get_relationship(edge_id)
    assert relationship.unknown_fields == ["a_to_b.match_existence"]
    assert relationship.from_node_id is None and relationship.edge is None
    assert relationship.edge_fields is None

    from_a = service.get_relationship(edge_id, "dataset_a")
    assert from_a.from_node_id == "dataset_a"
    assert from_a.from_dataset_columns == ["c1", "c2", "c3"]
    directed_a = decode(from_a.edge_fields, from_a.edge)
    assert directed_a["edge"] == "dataset_a[c1,c2,c3] -> dataset_b[d1,d2]"
    assert directed_a["match_existence"] == relationship.a_to_b["match_existence"] == "unknown"
    assert directed_a["reverse_match_existence"] == relationship.b_to_a["match_existence"]
    assert from_a.unknown_fields == relationship.unknown_fields

    from_b = service.get_relationship(edge_id, "dataset_b")
    directed_b = decode(from_b.edge_fields, from_b.edge)
    assert directed_b["multiplicity"] == relationship.b_to_a["multiplicity"]
    assert directed_b["reverse_match_existence"] == "unknown"

    with pytest.raises(ValueError, match="is not an endpoint"):
        service.get_relationship(edge_id, "dataset_missing")

    assert listed["match_existence"] == "unknown"
    [edge_from_b] = edge_records(service.get_dataset_edges("dataset_b"))
    assert edge_from_b["reverse_match_existence"] == "unknown"