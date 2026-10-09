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


def _group(response, kind):
    return next(group for group in response.groups if group.kind == kind)


def _subjects(group):
    return [dict(zip(group.subject_row_header, row)) for row in group.subject_rows]


def _matches(response):
    return [
        {"kind": group.kind, **dict(zip(group.match_row_header, row))}
        for group in response.groups
        for row in group.match_rows
    ]


def test_normalize_term_is_mechanical_and_deterministic() -> None:
    assert normalize_term("  Client_ID  ") == "client id"
    assert normalize_term("AccountHolder") == "account holder"
    assert normalize_term("CLIENT-ID") == "client id"


def test_search_returns_exact_alias_and_prefix_candidates() -> None:
    service = _service()

    client = service.search(SearchRequest(query="CLIENT"))
    assert client.normalized_query == "client"
    customer = [
        match for match in _matches(client) if match["key"] == "sqlite:lending.customer"
    ]
    assert {"match_type": "exact", "match_field": "synonym"}.items() <= customer[0].items()

    prefix = service.search(SearchRequest(query="cli"))
    assert any(match["key"] == "sqlite:lending.customer" for match in _matches(prefix))
    assert all(match["match_type"] == "prefix" for match in _matches(prefix))


def test_search_reports_every_matching_value_once() -> None:
    response = _service().search(SearchRequest(query="account", kind=["dataset"]))
    rows = [
        (match["match_type"], match["match_field"], match["matched_value"])
        for match in _matches(response)
        if match["key"] == "sqlite:lending.account"
    ]

    assert rows[:3] == [
        ("exact", "node_id", "sqlite:lending.account"),
        ("exact", "display_name", "account"),
        ("exact", "synonym", "deposit account"),
    ]
    assert ("exact", "qualified_name", "lending.main.account") in rows
    assert len(rows) == len(set(rows))
    holder = [
        match
        for match in _matches(response)
        if match["key"] == "sqlite:lending.account_holder"
        and match["match_field"] == "display_name"
    ]
    assert [(match["match_type"], match["matched_term"]) for match in holder] == [
        ("exact", "account")
    ]


def test_search_rows_follow_their_headers() -> None:
    response = _service().search(SearchRequest(query="account", limit=1000))

    assert [group.subject_row_header for group in response.groups] == [
        ["key", "node_id", "column_name"],
        ["key", "display_name", "unknown_fields"],
        [
            "key",
            "entity_expression",
            "node_id",
            "identity_id",
            "dataset_columns",
            "unknown_fields",
        ],
        ["key", "name"],
    ]
    for group in response.groups:
        assert group.match_row_header == [
            "key",
            "match_type",
            "match_field",
            "matched_term",
            "matched_value",
        ]
        keys = [row[0] for row in group.subject_rows]
        assert len(keys) == len(set(keys))
        assert {row[0] for row in group.match_rows} == set(keys)
        assert all(len(row) == len(group.subject_row_header) for row in group.subject_rows)
        assert all(len(row) == len(group.match_row_header) for row in group.match_rows)
    identity = _subjects(_group(response, "identity"))
    assert {"key": "account_identity", "name": "Account identity"} in identity


def test_search_limits_each_kind_separately() -> None:
    response = _service().search(SearchRequest(query="account", limit=2))

    assert all(len(group.subject_rows) <= 2 for group in response.groups)
    assert _group(response, "column").truncated is True
    assert _group(response, "dataset").subject_rows
    assert _group(response, "identity").subject_rows
    assert response.truncated is True


def test_search_returns_only_requested_kinds() -> None:
    service = _service()
    response = service.search(
        SearchRequest(query="account", kind=["identity", "dataset"], limit=1000)
    )

    assert [group.kind for group in response.groups] == ["dataset", "identity"]
    assert all(group.subject_rows for group in response.groups)

    with pytest.raises(ValidationError, match="at least 1 item"):
        SearchRequest(query="account", kind=[])
    with pytest.raises(ValidationError, match="Input should be"):
        SearchRequest.model_validate({"query": "account", "kind": ["relationship"]})


def test_search_orders_subjects_by_best_match_then_label() -> None:
    response = _service().search(SearchRequest(query="acc", limit=1000))
    exact = _service().search(SearchRequest(query="account", limit=1000))

    for result in (response, exact):
        ranks = {"exact": 0, "prefix": 1, "phrase": 2, "all_words": 3}
        for group in result.groups:
            best: dict[str, int] = {}
            for row in group.match_rows:
                best[row[0]] = min(best.get(row[0], 4), ranks[row[1]])
            labels = {row[0]: row[1] or row[0] for row in group.subject_rows}
            if group.kind == "column":
                labels = {row[0]: row[2] for row in group.subject_rows}
            sort_keys = [
                (best[key], normalize_term(labels[key]), key)
                for key in (row[0] for row in group.subject_rows)
            ]
            assert sort_keys == sorted(sort_keys)


def test_search_matches_name_fragments_word_by_word() -> None:
    snapshot, _, _ = build_snapshot_from_yaml(LENDING)
    snapshot.logical_identities[0].name = "Master Production Schedule"
    snapshot.nodes[0].descriptor.display_name = "Master Production Schedule"
    service = GraphReadService(snapshot)

    response = service.search(SearchRequest(query="production sched", limit=1000))
    assert [
        (match["kind"], match["key"], match["match_type"], match["match_field"])
        for match in _matches(response)
    ] == [
        ("dataset", "sqlite:lending.account", "phrase", "display_name"),
        ("identity", "account_identity", "phrase", "name"),
    ]
    assert _matches(response)[1]["matched_term"] == "production schedule"
    assert _matches(response)[1]["matched_value"] == "Master Production Schedule"


def test_search_matches_qualified_name_fragments() -> None:
    service = _service()

    phrase = service.search(SearchRequest(query="main.account_hol", kind=["dataset"]))
    assert [
        (match["key"], match["match_type"], match["match_field"], match["matched_term"])
        for match in _matches(phrase)
    ] == [
        (
            "sqlite:lending.account_holder",
            "phrase",
            "qualified_name",
            "main account holder",
        )
    ]

    scattered = service.search(SearchRequest(query="holder lending", kind=["dataset"]))
    assert [
        (match["key"], match["match_type"], match["match_field"], match["matched_term"])
        for match in _matches(scattered)
    ] == [
        ("sqlite:lending.account_holder", "all_words", "qualified_name", "holder lending")
    ]


def test_search_word_matches_only_within_one_name_value() -> None:
    service = _service()

    # Both words occur in one column description, which is not a word-match field.
    assert _matches(service.search(SearchRequest(query="repays loan"))) == []
    # The words occur in different values of the same dataset.
    assert _matches(service.search(SearchRequest(query="deposit lending"))) == []


def test_search_ranks_an_identity_by_its_best_match() -> None:
    snapshot, _, _ = build_snapshot_from_yaml(LENDING)
    snapshot.logical_identities[0].name = "Master Production Schedule"
    snapshot.logical_identities[0].synonyms = ["production schedule"]
    response = GraphReadService(snapshot).search(
        SearchRequest(query="production schedule", kind=["identity"], limit=1000)
    )

    assert [
        (match["match_type"], match["match_field"]) for match in _matches(response)
    ] == [("exact", "synonym"), ("phrase", "name")]


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
        assert _matches(service.search(SearchRequest(query=query))) == []

    identities = _subjects(
        _group(service.search(SearchRequest(query="customer_identity")), "identity")
    )
    assert [subject["key"] for subject in identities] == ["customer_identity"]
    dataset = next(
        subject
        for subject in _subjects(
            _group(service.search(SearchRequest(query="dataset_b")), "dataset")
        )
        if subject["key"] == "dataset_b"
    )
    assert dataset["unknown_fields"] == ["grain"]
    assert service.get_dataset("dataset_a").columns[2]["description"] == "N/A"


def test_search_reports_unknown_claims_on_catalog_definitions() -> None:
    service = _service()

    response = service.search(
        SearchRequest(query="account_id", kind=["entity_definition"], limit=1000)
    )
    definition = next(
        subject
        for subject in _subjects(_group(response, "entity_definition"))
        if subject["node_id"] == "sqlite:lending.account"
        and subject["identity_id"] == "account_identity"
    )
    assert definition["unknown_fields"] == ["entity_universe"]


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
    assert relationship.from_node_id is None
    assert relationship.direction is None
    assert relationship.reverse_direction is None

    from_a = service.get_relationship(edge_id, "dataset_a")
    assert from_a.from_node_id == "dataset_a"
    assert from_a.direction == relationship.a_to_b
    assert from_a.reverse_direction == relationship.b_to_a
    assert from_a.unknown_fields == ["reverse_direction.match_existence"]

    from_b = service.get_relationship(edge_id, "dataset_b")
    assert from_b.direction == relationship.b_to_a
    assert from_b.reverse_direction == relationship.a_to_b
    assert from_b.unknown_fields == ["direction.match_existence"]

    with pytest.raises(ValueError, match="is not an endpoint"):
        service.get_relationship(edge_id, "dataset_missing")

    [hop_from_a] = service.get_hops("dataset_a")
    assert hop_from_a.unknown_fields == ["reverse_direction.match_existence"]
    [hop_from_b] = service.get_hops("dataset_b")
    assert hop_from_b.unknown_fields == ["direction.match_existence"]

    [path] = service.find_paths("dataset_b", "dataset_a").paths
    [hop] = path["hops"]
    assert hop["direction"] == relationship.b_to_a
    assert hop["reverse_direction"] == relationship.a_to_b
    assert hop["unknown_fields"] == ["direction.match_existence"]
    [reverse_path] = service.find_paths("dataset_a", "dataset_b").paths
    [reverse_hop] = reverse_path["hops"]
    assert reverse_hop["direction"] == relationship.a_to_b
    assert reverse_hop["reverse_direction"] == relationship.b_to_a
    assert reverse_hop["unknown_fields"] == ["reverse_direction.match_existence"]
