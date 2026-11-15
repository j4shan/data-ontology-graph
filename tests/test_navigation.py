"""Directed edges, subgraph expansion, and path search over the lending catalog
(product graph-navigation; system design 2.3.3-2.3.9).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from data_ontology_graph.service.contracts import (
    PathsRequest,
    SubgraphRequest,
)
from data_ontology_graph.model.dataset import DefinitionKey
from data_ontology_graph.service.tables import to_records
from testkit.builders import same_dataset_service
from testkit.records import by_id, dataset_edges, decode, paths
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
    complete = service.get_edges(account)
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
    limited = service.get_edges(account, limit=1)
    assert _definitions(limited) == [
        ("account_identity", ["account_id"], ["sqlite:lending.account_holder"], 2, True),
        ("region_identity", ["region_id"], ["sqlite:lending.customer"], 2, True),
    ]
    assert limited.truncated is True
    # Only the targets of listed edges are returned.
    assert set(by_id(limited.datasets, "node_id")) == {
        account, "sqlite:lending.account_holder", "sqlite:lending.customer",
    }
    assert service.get_edges(account, limit=2).truncated is False
    with pytest.raises(ValidationError):
        service.get_edges(account, limit=0)
    with pytest.raises(ValidationError):
        service.get_edges(account, limit=1001)


def test_edges_filter_by_logical_entity_and_start_columns(lending_service) -> None:
    service = lending_service
    account = "sqlite:lending.account"
    region = service.get_edges(account, identity_id="region_identity")
    assert [definition[:2] for definition in _definitions(region)] == [
        ("region_identity", ["region_id"]),
    ]
    assert set(by_id(region.datasets, "node_id")) == {
        account, "sqlite:lending.customer", "sqlite:lending.region",
    }
    exact = service.get_edges(account, identity_id="region_identity",
                              from_dataset_columns=["region_id"])
    assert _definitions(exact) == _definitions(region)
    with pytest.raises(ValueError, match="no entity definition of 'loan_identity'"):
        service.get_edges(account, identity_id="loan_identity")
    with pytest.raises(ValueError, match="no entity definition"):
        service.get_edges(account, identity_id="region_identity",
                          from_dataset_columns=["account_id"])
    with pytest.raises(ValidationError, match="requires identity_id"):
        service.get_edges(account, from_dataset_columns=["region_id"])


def test_multi_seed_bfs_is_bounded_and_deduplicated(lending_service) -> None:
    service = lending_service
    response = service.expand_subgraph(
        SubgraphRequest(
            seed_node_ids=["sqlite:lending.customer", "sqlite:lending.loan"],
            max_depth=2,
            detail="full",
        )
    )
    nodes = [item["node_id"] for item in to_records(response.datasets)]
    assert len(nodes) == len(set(nodes))
    assert "sqlite:lending.account_holder" in nodes
    assert "sqlite:lending.account" in nodes
    assert all(item["distance"] <= 2 for item in to_records(response.datasets))
    assert {item["node_id"] for item in to_records(response.columns)} <= set(nodes)
    assert edge_records(response)


def test_bfs_enforces_node_and_edge_result_limits(lending_service) -> None:
    service = lending_service
    response = service.expand_subgraph(
        SubgraphRequest(
            seed_node_ids=["sqlite:lending.customer"],
            max_depth=4,
            max_nodes=3,
            limit=1,
        )
    )

    assert len(to_records(response.datasets)) == 3
    assert all(
        len(definition["edges"]) <= 1
        for group in response.edge_groups for definition in group["entity_definitions"]
    )
    assert response.truncated is True
    returned_nodes = set(by_id(response.datasets, "node_id"))
    assert all(
        edge["from_node_id"] in returned_nodes and edge["to_node_id"] in returned_nodes
        for edge in edge_records(response)
    )


def test_bfs_rejects_a_node_limit_smaller_than_the_seed_set(lending_service) -> None:
    with pytest.raises(ValueError, match="max_nodes must be at least"):
        lending_service.expand_subgraph(SubgraphRequest(
            seed_node_ids=["sqlite:lending.customer", "sqlite:lending.loan"],
            max_nodes=1,
        ))


def test_directed_edges_nest_in_their_datasets_and_every_target_is_returned(lending_service) -> None:
    service = lending_service
    account = "sqlite:lending.account"
    edges = service.get_edges(account, response_format="records").model_dump(mode="json")
    datasets = {record["node_id"]: record for record in edges["datasets"]}
    seed = datasets.pop(account)
    seed_edges = dataset_edges(seed, edges["edge_fields"])
    assert seed["distance"] == 0 and len(seed_edges) == seed["edge_count"] == 4
    # Neighbours are boundary datasets: they report their edge count and list no edges.
    assert all(
        "edge_groups" not in record and record["distance"] == 1 for record in datasets.values()
    )
    assert {edge["to_node_id"] for edge in seed_edges} == set(datasets)

    subgraph = service.expand_subgraph(SubgraphRequest(
        seed_node_ids=[account], max_depth=1, response_format="records",
    )).model_dump(mode="json")
    [subgraph_seed] = [d for d in subgraph["datasets"] if d["node_id"] == account]
    assert subgraph_seed["edge_groups"] == seed["edge_groups"]

    found = service.find_paths(PathsRequest(
        from_node_id="sqlite:lending.customer", to_node_id="sqlite:lending.region",
        response_format="records",
    )).model_dump(mode="json")
    node_ids = [record["node_id"] for record in found["datasets"]]
    assert node_ids == sorted(set(node_ids))
    assert all("edge_groups" not in record for record in found["datasets"])
    assert {
        edge["to_node_id"] for path in paths(found) for edge in path
    } | {"sqlite:lending.customer"} == set(node_ids)

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
    own = [edge for edge in edge_records(service.get_edges(link)) if edge["edge_id"] == edge_id]
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
    [group] = service.get_edges(link, limit=1).edge_groups
    assert group["identity_id"] == "device"
    assert [(d["dataset_columns"], d["edge_count"], len(d["edges"]))
            for d in group["entity_definitions"]] == [(["device_a"], 2, 1), (["device_b"], 2, 1)]

    with pytest.raises(ValueError, match="name from_dataset_columns"):
        service.get_relationship(edge_id, link)
    detail = service.get_relationship(edge_id, link, from_dataset_columns=["device_b"])
    directed = decode(detail.edge_fields, detail.edge)
    assert directed["from_dataset_columns"] == ["device_b"]
    assert directed["match_existence"] == "optional"

    [path_a, path_b] = paths(service.find_paths(PathsRequest(
        from_node_id=link, to_node_id=link, max_edges=1,
    )))
    assert [(edge["from_dataset_columns"], edge["to_dataset_columns"]) for edge in path_a + path_b] == [
        (["device_a"], ["device_b"]), (["device_b"], ["device_a"]),
    ]


def test_default_bounds_do_not_depend_on_detail(lending_service) -> None:
    service = lending_service
    seeds = ["sqlite:lending.account"]
    levels = ("essential", "standard", "full")
    assert [
        (response.max_nodes, response.limit)
        for response in (
            service.expand_subgraph(SubgraphRequest(seed_node_ids=seeds, detail=level))
            for level in levels
        )
    ] == [(1000, 200)] * 3
    assert [service.get_edges(seeds[0], detail=level).limit for level in levels] == [200] * 3
    assert {PathsRequest(from_node_id="a", to_node_id="b", detail=level).limit
            for level in levels} == {6}


def test_path_steps_name_their_logical_entity(lending_service) -> None:
    response = lending_service.find_paths(PathsRequest(
        from_node_id="sqlite:lending.loan", to_node_id="sqlite:lending.region", detail="essential",
    ))
    assert response.edge_fields == ["edge", "identity_id", "multiplicity", "match_existence", "edge_id"]
    assert [[step[1] for step in path] for path in response.paths] == [
        ["account_identity", "region_identity"],
        ["account_identity", "customer_identity", "region_identity"],
    ]
    # Inside an edge group the group names the logical entity, so the array does not.
    assert "identity_id" not in lending_service.get_edges("sqlite:lending.loan").edge_fields


def test_subgraph_expansion_caps_listed_directed_edges_with_limit(lending_service) -> None:
    with pytest.raises(ValidationError):
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], limit=1001)
    with pytest.raises(ValidationError):
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], max_edges=10)
    response = lending_service.expand_subgraph(
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], limit=2)
    )
    # Each of the seed's two entity definitions lists 2 of its 2 directed edges.
    assert response.limit == 2 and len(edge_records(response)) == 4 and not response.truncated
    response = lending_service.expand_subgraph(
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], limit=1)
    )
    assert len(edge_records(response)) == 2 and response.truncated


def test_traversal_reports_unknown_claims_relative_to_direction(example_service) -> None:
    service = example_service
    [listed] = edge_records(service.get_edges("dataset_a"))
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

    [edge_from_a] = edge_records(service.get_edges("dataset_a"))
    assert edge_from_a["match_existence"] == "unknown"
    [edge_from_b] = edge_records(service.get_edges("dataset_b"))
    assert edge_from_b["reverse_match_existence"] == "unknown"

    [[edge]] = paths(service.find_paths(PathsRequest(from_node_id="dataset_b", to_node_id="dataset_a")))
    assert edge["multiplicity"] == relationship.b_to_a["multiplicity"]
    assert edge["reverse_match_existence"] == "unknown"
    [[reverse_edge]] = paths(service.find_paths(PathsRequest(
        from_node_id="dataset_a", to_node_id="dataset_b",
    )))
    assert reverse_edge["match_existence"] == "unknown"
