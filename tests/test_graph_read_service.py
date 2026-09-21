from pathlib import Path

import pytest
from pydantic import ValidationError

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.service.contracts import SearchRequest, SubgraphRequest
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.search import normalize_term


ROOT = Path(__file__).resolve().parents[1]
FINANCIAL = ROOT / "resources" / "data" / "dev_overlays" / "financial" / "catalog.yaml"


def _service() -> GraphReadService:
    snapshot, _, _ = build_snapshot_from_yaml(FINANCIAL)
    return GraphReadService(snapshot)


def test_normalize_term_is_mechanical_and_deterministic() -> None:
    assert normalize_term("  Client_ID  ") == "client id"
    assert normalize_term("AccountHolder") == "account holder"
    assert normalize_term("CLIENT-ID") == "client id"


def test_search_returns_exact_alias_and_prefix_candidates() -> None:
    service = _service()

    customer = service.search(SearchRequest(query="CUSTOMER"))
    assert customer.normalized_query == "customer"
    client = next(
        hit
        for hit in customer.hits
        if hit.subject.key == "sql_db:financial.client"
    )
    assert client.match_kind == "exact"
    assert client.matched_field == "synonym"

    prefix = service.search(SearchRequest(query="cust"))
    assert any(hit.subject.key == "sql_db:financial.client" for hit in prefix.hits)
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
    identity = service.get_identity("client_identity")
    assert identity.definitions
    assert {item["node_id"] for item in identity.definitions} >= {
        "sql_db:financial.client",
        "sql_db:financial.disp",
    }

    dataset = service.get_dataset("sql_db:financial.account")
    assert dataset.descriptor["display_name"] == "account"
    assert dataset.accessor["schema_id"] == "accessor.sqlite.v1"
    assert dataset.accessor["properties"]["format"] == "sqlite"
    assert dataset.entity_definitions


def test_hops_expose_directional_target_properties_without_sql() -> None:
    service = _service()
    hops = service.get_hops("sql_db:financial.account")
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
            seed_node_ids=["sql_db:financial.client", "sql_db:financial.loan"],
            max_depth=2,
        )
    )
    nodes = [item["dataset"]["node_id"] for item in response.nodes]
    assert len(nodes) == len(set(nodes))
    assert "sql_db:financial.disp" in nodes
    assert "sql_db:financial.account" in nodes
    assert all(item["distance"] <= 2 for item in response.nodes)
    edge_ids = [edge.edge_id for edge in response.edges]
    assert len(edge_ids) == len(set(edge_ids))


def test_bfs_enforces_node_and_edge_result_limits() -> None:
    service = _service()
    response = service.expand_subgraph(
        SubgraphRequest(
            seed_node_ids=["sql_db:financial.client"],
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
            seed_node_ids=["sql_db:financial.client", "sql_db:financial.loan"],
            max_nodes=1,
        )


def test_paths_preserve_alternatives_without_sql_fragments() -> None:
    service = _service()
    response = service.find_paths(
        "sql_db:financial.client",
        "sql_db:financial.district",
        max_hops=4,
    )
    assert len(response.paths) >= 2
    assert response.paths[0]["length"] <= response.paths[1]["length"]
    assert "sql_on" not in str(response.model_dump(mode="json"))

    limited = service.find_paths(
        "sql_db:financial.client",
        "sql_db:financial.district",
        max_hops=4,
        limit=1,
    )
    assert len(limited.paths) == 1
    assert limited.truncated is True
