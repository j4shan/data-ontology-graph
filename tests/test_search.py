"""Lexical search over datasets, columns, entity definitions, logical entities, and cross-entity
relationships (product object-search; system design 2.2).
"""

import pytest
from pydantic import ValidationError

from data_ontology_graph.service.contracts import SearchRequest
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.search import is_placeholder, normalize_term
from testkit import STATED, snapshot_of

PG_EU = "pg-eu:crm.public.customer"


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


def test_search_returns_exact_alias_and_prefix_candidates(lending_service) -> None:
    service = lending_service

    client = service.search(SearchRequest(query="CLIENT"))
    assert client.normalized_query == "client"
    customer = [
        match for match in _matches(client) if match["key"] == "sqlite:lending.customer"
    ]
    assert {"match_type": "exact", "match_field": "synonym"}.items() <= customer[0].items()

    prefix = service.search(SearchRequest(query="cli"))
    assert any(match["key"] == "sqlite:lending.customer" for match in _matches(prefix))
    assert all(match["match_type"] == "prefix" for match in _matches(prefix))


def test_search_reports_every_matching_value_once(lending_service) -> None:
    response = lending_service.search(SearchRequest(query="account", kind=["dataset"]))
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


def test_search_rows_follow_their_headers(lending_service) -> None:
    response = lending_service.search(SearchRequest(query="account", limit=1000))

    assert [group.subject_row_header for group in response.groups] == [
        ["key", "node_id", "column_name"],
        ["key", "qualified_name", "unknown_fields"],
        [
            "key",
            "entity_expression",
            "node_id",
            "identity_id",
            "dataset_columns",
            "unknown_fields",
        ],
        ["key", "endpoints"],
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


def test_search_limits_each_kind_separately(lending_service) -> None:
    response = lending_service.search(SearchRequest(query="account", limit=2))

    assert all(len(group.subject_rows) <= 2 for group in response.groups)
    assert _group(response, "column").truncated is True
    assert _group(response, "dataset").subject_rows
    assert _group(response, "identity").subject_rows
    assert response.truncated is True


def test_search_returns_only_requested_kinds(lending_service) -> None:
    service = lending_service
    response = service.search(
        SearchRequest(query="account", kind=["identity", "dataset"], limit=1000)
    )

    assert [group.kind for group in response.groups] == ["dataset", "identity"]
    assert all(group.subject_rows for group in response.groups)

    with pytest.raises(ValidationError, match="at least 1 item"):
        SearchRequest(query="account", kind=[])
    with pytest.raises(ValidationError, match="Input should be"):
        SearchRequest.model_validate({"query": "account", "kind": ["relationship"]})


def test_search_orders_subjects_by_best_match_then_label(lending_service) -> None:
    response = lending_service.search(SearchRequest(query="acc", limit=1000))
    exact = lending_service.search(SearchRequest(query="account", limit=1000))

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


def test_search_matches_name_fragments_word_by_word(lending_snapshot) -> None:
    snapshot = lending_snapshot
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


def test_search_matches_qualified_name_fragments(lending_service) -> None:
    service = lending_service

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


def test_search_word_matches_only_within_one_name_value(lending_service) -> None:
    service = lending_service

    # Both words occur in one column description, which is not a word-match field.
    assert _matches(service.search(SearchRequest(query="repays loan"))) == []
    # The words occur in different values of the same dataset.
    assert _matches(service.search(SearchRequest(query="deposit lending"))) == []


def test_search_ranks_an_identity_by_its_best_match(lending_snapshot) -> None:
    snapshot = lending_snapshot
    snapshot.logical_identities[0].name = "Master Production Schedule"
    snapshot.logical_identities[0].synonyms = ["production schedule"]
    response = GraphReadService(snapshot).search(
        SearchRequest(query="production schedule", kind=["identity"], limit=1000)
    )

    assert [
        (match["match_type"], match["match_field"]) for match in _matches(response)
    ] == [("exact", "synonym"), ("phrase", "name")]


def test_placeholder_matching_uses_the_whole_normalized_value() -> None:
    for value in ["Unknown", " unknown. ", "N/A", "#N/A", "n.a.", "NaN", "NULL", "None", "TBD",
                  "To be determined", "Missing value", "no description available", "(null)"]:
        assert is_placeholder(value), value
    for value in ["", "unknown sender flag", "not null", "location of branch", "value",
                  "pending"]:
        assert not is_placeholder(value), value


def test_search_skips_placeholder_descriptions_and_unknown_claims(example_service) -> None:
    service = example_service
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


def test_search_reports_unknown_claims_on_catalog_definitions(lending_service) -> None:
    service = lending_service

    response = service.search(
        SearchRequest(query="region_id", kind=["entity_definition"], limit=1000)
    )
    definition = next(
        subject
        for subject in _subjects(_group(response, "entity_definition"))
        if subject["node_id"] == "sqlite:lending.account"
        and subject["identity_id"] == "region_identity"
    )
    assert definition["unknown_fields"] == ["conforms"]


@pytest.mark.parametrize(
    ("query", "node_id", "value"),
    [
        ("crm-eu", PG_EU, "crm-eu"),
        ("snowflake", "sf-amer:SALES.CORE.ORDERS", "snowflake"),
        ("chinacloudapi", "adls-cn:supply.shipments",
         "abfss://supply@acmecnsupply.dfs.core.chinacloudapi.cn/shipments/"),
        ("login", "mongo-apac:app.customer_logins", "login"),
    ],
)
def test_search_matches_accessor_kind_endpoint_labels_and_nested_properties(open_accessor_service, 
    query: str, node_id: str, value: str,
) -> None:
    response = open_accessor_service.search(SearchRequest(query=query, kind=["dataset"]))
    matches = [
        dict(zip(group.match_row_header, row))
        for group in response.groups
        for row in group.match_rows
    ]
    assert any(
        match["key"] == node_id and match["match_field"] == "accessor"
        and match["matched_value"] == value
        for match in matches
    )


def test_search_matches_cross_entity_relationship_descriptions(stated_service) -> None:
    response = stated_service.search(SearchRequest(query="shipped", kind=["entity_relationship"]))
    (group,) = response.groups
    assert group.kind == "entity_relationship"
    assert group.subject_row_header == ["key", "endpoints"]
    key = '["calendar_day_identity","order_identity"]'
    assert group.subject_rows == [[key, ["calendar_day_identity", "order_identity"]]]
    assert group.match_rows == [[
        key, "exact", "description", "shipped",
        "An order is shipped on one calendar day once it ships.",
    ]]


def test_search_without_kind_includes_cross_entity_relationships_in_group_order(stated_service) -> None:
    response = stated_service.search(SearchRequest(query="click"))
    assert [group.kind for group in response.groups] == [
        "column", "dataset", "entity_definition", "entity_relationship", "identity",
    ]


def test_search_keys_stay_distinct_when_logical_entity_ids_contain_delimiters() -> None:
    from data_ontology_graph.model.intermediary import LogicalIdentity
    from data_ontology_graph.model.snapshot import GraphSnapshot

    snapshot = snapshot_of(STATED)
    identities = [LogicalIdentity(identity_id=value, name=value) for value in ("a", "a|b", "b|c", "c")]
    colliding = GraphSnapshot(
        version=snapshot.version,
        logical_identities=[*snapshot.logical_identities, *identities],
        nodes=snapshot.nodes,
        entity_relationships=[
            {"endpoints": ["a", "b|c"], "descriptions": ["alpha link"]},
            {"endpoints": ["a|b", "c"], "descriptions": ["alpha other"]},
        ],
    )
    (group,) = GraphReadService(colliding).search(SearchRequest(query="alpha", kind=["entity_relationship"])).groups
    keys = [row[0] for row in group.subject_rows]
    assert keys == ['["a","b|c"]', '["a|b","c"]']
    assert {row[0]: row[4] for row in group.match_rows} == {
        '["a","b|c"]': "alpha link", '["a|b","c"]': "alpha other",
    }
