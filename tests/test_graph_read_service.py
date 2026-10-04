from pathlib import Path

import pytest
from pydantic import ValidationError

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.service.contracts import SearchRequest, SubgraphRequest
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.search import is_placeholder, normalize_term


ROOT = Path(__file__).resolve().parents[1]
LENDING = ROOT / "tests" / "fixtures" / "lending" / "catalog.yaml"


def _service() -> GraphReadService:
    snapshot, _, _ = build_snapshot_from_yaml(LENDING)
    return GraphReadService(snapshot)


def test_normalize_term_is_mechanical_and_deterministic() -> None:
    assert normalize_term("  Client_ID  ") == "client id"
    assert normalize_term("AccountHolder") == "account holder"
    assert normalize_term("CLIENT-ID") == "client id"


def test_search_returns_exact_alias_and_prefix_candidates() -> None:
    service = _service()

    client = service.search(SearchRequest(query="CLIENT"))
    assert client.normalized_query == "client"
    customer = next(
        hit
        for hit in client.hits
        if hit.subject.key == "sqlite:lending.customer"
    )
    assert customer.match_kind == "exact"
    assert customer.matched_field == "synonym"

    prefix = service.search(SearchRequest(query="cli"))
    assert any(hit.subject.key == "sqlite:lending.customer" for hit in prefix.hits)
    assert all(hit.match_kind == "prefix" for hit in prefix.hits)


def test_search_deduplicates_subjects_and_limits_results() -> None:
    service = _service()
    response = service.search(SearchRequest(query="account", limit=2))

    keys = [(hit.subject.kind, hit.subject.key) for hit in response.hits]
    assert len(keys) == len(set(keys))
    assert len(response.hits) == 2
    assert response.truncated is True


def test_identity_and_dataset_lookup_expose_target_model() -> None:
    service = _service()
    identity = service.get_identity("customer_identity")
    assert identity.definitions
    assert {item["node_id"] for item in identity.definitions} >= {
        "sqlite:lending.customer",
        "sqlite:lending.account_holder",
    }

    dataset = service.get_dataset("sqlite:lending.account")
    assert dataset.descriptor["display_name"] == "account"
    assert dataset.accessor["schema_id"] == "accessor.sqlite.v1"
    assert dataset.accessor["properties"]["schema"] == "main"
    assert dataset.accessor["properties"]["object"] == "account"
    assert dataset.entity_definitions


def test_hops_expose_directional_target_properties_without_sql() -> None:
    service = _service()
    hops = service.get_hops("sqlite:lending.account")
    assert hops
    payload = hops[0].model_dump(mode="json")
    assert payload["direction"]["multiplicity"] in {
        "1:1",
        "1:many",
        "many:1",
        "many:many",
        "unknown",
    }
    assert payload["direction"]["match_existence"] in {
        "always",
        "optional",
        "unknown",
    }
    assert "sql_on" not in str(payload)
    assert "recommended_join" not in str(payload)


def test_multi_seed_bfs_is_bounded_and_deduplicated() -> None:
    service = _service()
    response = service.expand_subgraph(
        SubgraphRequest(
            seed_node_ids=["sqlite:lending.customer", "sqlite:lending.loan"],
            max_depth=2,
        )
    )
    nodes = [item["dataset"]["node_id"] for item in response.nodes]
    assert len(nodes) == len(set(nodes))
    assert "sqlite:lending.account_holder" in nodes
    assert "sqlite:lending.account" in nodes
    assert all(item["distance"] <= 2 for item in response.nodes)
    edge_ids = [edge.edge_id for edge in response.edges]
    assert len(edge_ids) == len(set(edge_ids))


def test_bfs_enforces_node_and_edge_result_limits() -> None:
    service = _service()
    response = service.expand_subgraph(
        SubgraphRequest(
            seed_node_ids=["sqlite:lending.customer"],
            max_depth=4,
            max_nodes=3,
            max_edges=1,
        )
    )

    assert len(response.nodes) == 3
    assert len(response.edges) <= 1
    assert response.truncated is True
    returned_nodes = {item["dataset"]["node_id"] for item in response.nodes}
    assert all(
        edge.endpoint_a["node_id"] in returned_nodes
        and edge.endpoint_b["node_id"] in returned_nodes
        for edge in response.edges
    )


def test_bfs_rejects_a_node_limit_smaller_than_the_seed_set() -> None:
    with pytest.raises(ValidationError, match="max_nodes must be at least"):
        SubgraphRequest(
            seed_node_ids=["sqlite:lending.customer", "sqlite:lending.loan"],
            max_nodes=1,
        )


def test_paths_preserve_alternatives_without_sql_fragments() -> None:
    service = _service()
    response = service.find_paths(
        "sqlite:lending.customer",
        "sqlite:lending.region",
        max_hops=4,
    )
    assert len(response.paths) >= 2
    assert response.paths[0]["length"] <= response.paths[1]["length"]
    assert "sql_on" not in str(response.model_dump(mode="json"))

    limited = service.find_paths(
        "sqlite:lending.customer",
        "sqlite:lending.region",
        max_hops=4,
        limit=1,
    )
    assert len(limited.paths) == 1
    assert limited.truncated is True


EXAMPLE = ROOT / "resources" / "schema" / "examples" / "intermediary-valid.yaml"


def _example_service() -> GraphReadService:
    snapshot, _, _ = build_snapshot_from_yaml(EXAMPLE)
    return GraphReadService(snapshot)


def test_placeholder_matching_uses_the_whole_normalized_value() -> None:
    for value in ["Unknown", " unknown. ", "N/A", "#N/A", "n.a.", "NaN", "NULL", "None", "TBD",
                  "To be determined", "Missing value", "no description available", "(null)"]:
        assert is_placeholder(value), value
    for value in ["", "unknown sender flag", "not null", "location of branch", "value",
                  "pending"]:
        assert not is_placeholder(value), value


def test_search_skips_placeholder_descriptions_and_unknown_claims() -> None:
    service = _example_service()
    for query in ["unknown", "n a"]:
        assert service.search(SearchRequest(query=query)).hits == []

    identity = next(
        hit.subject
        for hit in service.search(SearchRequest(query="customer_identity")).hits
        if hit.subject.kind == "identity"
    )
    assert identity.unknown_fields == []
    dataset = next(
        hit.subject
        for hit in service.search(SearchRequest(query="dataset_b")).hits
        if hit.subject.kind == "dataset"
    )
    assert dataset.unknown_fields == ["grain"]
    assert service.get_dataset("dataset_a").columns[2]["description"] == "N/A"


def test_search_reports_unknown_claims_on_catalog_definitions() -> None:
    service = _service()

    hits = service.search(SearchRequest(query="account_id", limit=1000)).hits
    definition = next(
        hit.subject
        for hit in hits
        if hit.subject.kind == "entity_definition"
        and hit.subject.node_id == "sqlite:lending.account"
        and hit.subject.identity_id == "account_identity"
    )
    assert definition.unknown_fields == ["entity_universe"]


def test_detail_responses_expose_unknown_claims() -> None:
    service = _example_service()

    identity = service.get_identity("customer_identity")
    assert identity.description == "Unknown"
    assert [item["unknown_fields"] for item in identity.definitions] == [[], []]

    dataset = service.get_dataset("dataset_b")
    assert dataset.grain == "unknown"
    assert dataset.unknown_fields == ["grain"]
    assert dataset.entity_definitions[0]["entity_universe"] == "complete"

    known = service.get_dataset("dataset_a")
    assert known.unknown_fields == []
    assert "unknown_fields" not in known.columns[2]


def test_traversal_reports_unknown_fields_relative_to_direction() -> None:
    service = _example_service()
    edge_id = "dataset_a:customer_identity:c1+c2+c3__dataset_b:customer_identity:d1+d2"

    relationship = service.get_relationship(edge_id)
    assert relationship.unknown_fields == ["b_to_a.match_existence"]

    [from_a] = service.get_hops("dataset_a")
    assert from_a.unknown_fields == ["reverse_direction.match_existence"]
    [from_b] = service.get_hops("dataset_b")
    assert from_b.unknown_fields == ["direction.match_existence"]

    [path] = service.find_paths("dataset_b", "dataset_a").paths
    assert path["hops"][0]["unknown_fields"] == ["direction.match_existence"]
    [reverse_path] = service.find_paths("dataset_a", "dataset_b").paths
    assert reverse_path["hops"][0]["unknown_fields"] == []
