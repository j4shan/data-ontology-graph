from pathlib import Path

import pytest
from pydantic import ValidationError

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.service.contracts import (
    ConnectingSubgraphRequest,
    SearchRequest,
    SubgraphRequest,
)
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.search import is_placeholder, normalize_term
from data_ontology_graph.service.tables import to_records, to_table
from graph_records import by_id, paths


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
    definitions = to_records(identity.entity_definitions)
    assert definitions
    assert set(by_id(identity.datasets, "node_id")) == {item["node_id"] for item in definitions}
    assert {item["node_id"] for item in definitions} >= {
        "sqlite:lending.customer",
        "sqlite:lending.account_holder",
    }

    dataset = service.get_dataset("sqlite:lending.account")
    assert dataset.descriptor["display_name"] == "account"
    assert dataset.accessor["schema_id"] == "accessor.sqlite.v1"
    assert dataset.accessor["properties"]["schema"] == "main"
    assert dataset.accessor["properties"]["object"] == "account"
    assert dataset.entity_definitions


def test_hops_are_ordered_by_edge_id_and_bounded_by_limit() -> None:
    service = _service()
    complete = service.get_hops("sqlite:lending.account")
    edge_ids = [hop["edge_id"] for hop in to_records(complete.hops)]
    assert len(edge_ids) == 3
    assert edge_ids == sorted(edge_ids)
    assert complete.truncated is False

    limited = service.get_hops("sqlite:lending.account", limit=2)
    assert [hop["edge_id"] for hop in to_records(limited.hops)] == edge_ids[:2]
    assert limited.truncated is True
    assert service.get_hops("sqlite:lending.account", limit=3).truncated is False
    with pytest.raises(ValidationError):
        service.get_hops("sqlite:lending.account", limit=0)


def test_identity_definitions_filter_by_universe_and_respect_limit() -> None:
    service = _service()
    region = service.get_identity("region_identity")
    assert [item["node_id"] for item in to_records(region.entity_definitions)] == [
        "sqlite:lending.account", "sqlite:lending.customer", "sqlite:lending.region",
    ]
    assert region.truncated is False

    limited = service.get_identity("region_identity", limit=2)
    assert [item["node_id"] for item in to_records(limited.entity_definitions)] == [
        "sqlite:lending.account", "sqlite:lending.customer",
    ]
    assert limited.truncated is True

    # The filter applies before the limit, so the complete realization is never cut.
    complete = service.get_identity("region_identity", entity_universe=["complete"], limit=1)
    assert [item["node_id"] for item in to_records(complete.entity_definitions)] == [
        "sqlite:lending.region",
    ]
    assert complete.truncated is False
    empty = service.get_identity("loan_identity", entity_universe=["complete"])
    assert to_records(empty.entity_definitions) == [] and to_records(empty.datasets) == []
    with pytest.raises(ValidationError):
        service.get_identity("region_identity", entity_universe=[])


def test_hops_expose_directional_target_properties_without_sql() -> None:
    service = _service()
    hops = to_records(service.get_hops("sqlite:lending.account").hops)
    assert hops
    payload = hops[0]
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
    nodes = [item["node_id"] for item in to_records(response.datasets)]
    assert len(nodes) == len(set(nodes))
    assert "sqlite:lending.account_holder" in nodes
    assert "sqlite:lending.account" in nodes
    assert all(item["distance"] <= 2 for item in to_records(response.datasets))
    assert {item["node_id"] for item in to_records(response.columns)} <= set(nodes)
    assert to_records(response.relationships)


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

    assert len(to_records(response.datasets)) == 3
    assert len(to_records(response.relationships)) <= 1
    assert response.truncated is True
    returned_nodes = set(by_id(response.datasets, "node_id"))
    assert all(
        edge["endpoint_a"]["node_id"] in returned_nodes
        and edge["endpoint_b"]["node_id"] in returned_nodes
        for edge in to_records(response.relationships)
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
    assert response.path_count >= 2
    first, second = paths(response)[:2]
    assert len(first) <= len(second)
    assert "sql_on" not in str(response.model_dump(mode="json"))

    limited = service.find_paths(
        "sqlite:lending.customer",
        "sqlite:lending.region",
        max_hops=4,
        limit=1,
    )
    assert limited.path_count == 1
    assert limited.truncated is True


def _assert_listed_once(service: GraphReadService, response) -> None:
    """Relationships and datasets appear once, keyed by ID, and every reference resolves."""
    hops = to_records(response.hops)
    relationships = to_records(response.relationships)
    datasets = to_records(response.datasets)
    definitions = to_records(response.entity_definitions)
    edge_ids = [record["edge_id"] for record in relationships]
    node_ids = [record["node_id"] for record in datasets]
    assert edge_ids == sorted(set(edge_ids)) and node_ids == sorted(set(node_ids))
    assert {hop["edge_id"] for hop in hops} == set(edge_ids)
    by_edge = dict(zip(edge_ids, relationships))
    for hop in hops:
        relationship = by_edge[hop["edge_id"]]
        ends = {relationship["endpoint_a"]["node_id"], relationship["endpoint_b"]["node_id"]}
        assert {hop["from_node_id"], hop["to_node_id"]} == ends
    endpoints = {
        (endpoint["node_id"], relationship["identity_id"], tuple(endpoint["dataset_columns"]))
        for relationship in relationships
        for endpoint in (relationship["endpoint_a"], relationship["endpoint_b"])
    }
    assert set(node_ids) == {node_id for node_id, _, _ in endpoints}
    assert {
        (item["node_id"], item["identity_id"], tuple(item["dataset_columns"]))
        for item in definitions
    } == endpoints
    for item in definitions:
        node_id = item.pop("node_id")
        assert item in service.get_dataset(node_id).entity_definitions


def test_navigation_responses_list_each_relationship_and_dataset_once() -> None:
    service = _service()
    response = service.find_paths("sqlite:lending.customer", "sqlite:lending.region", max_hops=4)
    assert response.path_count >= 2
    assert len(to_records(response.datasets)) < 2 * len(to_records(response.hops))
    _assert_listed_once(service, response)

    hops = service.get_hops("sqlite:lending.account")
    assert {hop["from_node_id"] for hop in to_records(hops.hops)} == {"sqlite:lending.account"}
    _assert_listed_once(service, hops)

    edge_id = to_records(hops.hops)[0]["edge_id"]
    relationship = service.get_relationship(edge_id)
    assert set(by_id(relationship.datasets, "node_id")) == {
        relationship.endpoint_a["node_id"], relationship.endpoint_b["node_id"],
    }
    assert len(to_records(relationship.entity_definitions)) == 2

    subgraph = service.expand_subgraph(
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], max_depth=1),
    )
    assert set(by_id(subgraph.relationships, "edge_id")) == set(by_id(hops.hops, "edge_id"))


def test_table_and_records_formats_carry_the_same_content() -> None:
    service = _service()
    account, region = "sqlite:lending.account", "sqlite:lending.customer"
    edge_id = service.index.adjacency[account][0].edge_id
    calls = [
        lambda f: service.get_identity("region_identity", response_format=f),
        lambda f: service.get_relationship(edge_id, account, response_format=f),
        lambda f: service.get_hops(account, response_format=f),
        lambda f: service.find_paths(region, "sqlite:lending.region", response_format=f),
        lambda f: service.expand_subgraph(
            SubgraphRequest(seed_node_ids=[account], max_depth=2, response_format=f)),
        lambda f: service.find_connecting_subgraph(
            ConnectingSubgraphRequest(node_ids=[account, region], response_format=f)),
    ]
    for call in calls:
        table = call("table").model_dump(mode="json")
        records = call("records").model_dump(mode="json")
        tables = [key for key, value in table.items()
                  if isinstance(value, dict) and set(value) == {"header", "rows"}]
        assert tables
        for key in tables:
            assert to_records(table[key]) == records[key]
            assert len(table[key]["header"]) <= 12
        assert {k: v for k, v in table.items() if k not in tables} == {
            k: v for k, v in records.items() if k not in tables
        }


def test_tables_reject_records_their_header_does_not_cover() -> None:
    with pytest.raises(ValueError, match="does not cover"):
        to_table([{"edge_id": "e", "extra": 1}], ["edge_id"])
    table = to_table([{"a": {"b": 1, "c": [2]}, "d": None}], ["a.b", "a.c", "d"])
    assert table.rows == [[1, [2], None]]
    assert to_records(table) == [{"a": {"b": 1, "c": [2]}, "d": None}]


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
    assert [item["unknown_fields"] for item in to_records(identity.entity_definitions)] == [[], []]

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

    [hop_from_a] = to_records(service.get_hops("dataset_a").hops)
    assert hop_from_a["unknown_fields"] == ["reverse_direction.match_existence"]
    [hop_from_b] = to_records(service.get_hops("dataset_b").hops)
    assert hop_from_b["unknown_fields"] == ["direction.match_existence"]

    [[hop]] = paths(service.find_paths("dataset_b", "dataset_a"))
    assert hop["direction"] == relationship.b_to_a
    assert hop["reverse_direction"] == relationship.a_to_b
    assert hop["unknown_fields"] == ["direction.match_existence"]
    [[reverse_hop]] = paths(service.find_paths("dataset_a", "dataset_b"))
    assert reverse_hop["direction"] == relationship.a_to_b
    assert reverse_hop["reverse_direction"] == relationship.b_to_a
    assert reverse_hop["unknown_fields"] == ["reverse_direction.match_existence"]
