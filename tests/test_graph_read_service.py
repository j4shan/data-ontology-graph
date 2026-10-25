from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.service.contracts import (
    ConnectingSubgraphRequest,
    PathsRequest,
    SearchRequest,
    SubgraphRequest,
)
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.search import is_placeholder, normalize_term
from data_ontology_graph.service.tables import to_records, to_table
from data_ontology_graph.service.views import definition_label
from graph_records import by_id, dataset_edges, decode, edges as edge_records, paths


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
        ["key", "qualified_name", "unknown_fields"],
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


def _definitions(response):
    """(logical entity ID, start columns, listed end node_ids, edge_count, truncated) per definition."""
    return [
        (group["identity_id"], definition["dataset_columns"],
         [decode(response.edge_fields, edge)["to_node_id"] for edge in definition["edges"]],
         definition["edge_count"], definition["truncated"])
        for group in response.edge_groups
        for definition in group["entity_definitions"]
    ]


def test_edges_are_grouped_by_entity_definition_and_limited_per_definition() -> None:
    service = _service()
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


def test_edges_filter_by_logical_entity_and_start_columns() -> None:
    service = _service()
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


def test_directed_edges_expose_outgoing_claims_without_sql() -> None:
    service = _service()
    edges = edge_records(service.get_edges("sqlite:lending.account"))
    assert edges
    payload = edges[0]
    assert payload["from_node_id"] == "sqlite:lending.account"
    assert payload["multiplicity"] in {"1:1", "1:many", "many:1", "many:many", "unknown"}
    assert payload["match_existence"] in {"always", "optional", "unknown"}
    assert "direction" not in payload
    assert "sql_on" not in str(payload)
    assert "recommended_join" not in str(payload)


def test_multi_seed_bfs_is_bounded_and_deduplicated() -> None:
    service = _service()
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


def test_bfs_enforces_node_and_edge_result_limits() -> None:
    service = _service()
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


def test_bfs_rejects_a_node_limit_smaller_than_the_seed_set() -> None:
    with pytest.raises(ValueError, match="max_nodes must be at least"):
        _service().expand_subgraph(SubgraphRequest(
            seed_node_ids=["sqlite:lending.customer", "sqlite:lending.loan"],
            max_nodes=1,
        ))


def test_paths_preserve_alternatives_without_sql_fragments() -> None:
    service = _service()
    request = {"from_node_id": "sqlite:lending.customer", "to_node_id": "sqlite:lending.region"}
    response = service.find_paths(PathsRequest(**request, max_edges=4))
    assert response.path_count >= 2
    first, second = paths(response)[:2]
    assert len(first) <= len(second)
    assert "sql_on" not in str(response.model_dump(mode="json"))

    limited = service.find_paths(PathsRequest(**request, max_edges=4, limit=1))
    assert limited.path_count == 1
    assert limited.truncated is True


def test_directed_edges_nest_in_their_datasets_and_every_target_is_returned() -> None:
    service = _service()
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

    routes = service.find_paths(PathsRequest(
        from_node_id="sqlite:lending.customer", to_node_id="sqlite:lending.region",
        response_format="records",
    )).model_dump(mode="json")
    node_ids = [record["node_id"] for record in routes["datasets"]]
    assert node_ids == sorted(set(node_ids))
    assert all("edge_groups" not in record for record in routes["datasets"])
    assert {
        edge["to_node_id"] for route in paths(routes) for edge in route
    } | {"sqlite:lending.customer"} == set(node_ids)

    relationship = service.get_relationship(seed_edges[0]["edge_id"])
    assert set(by_id(relationship.datasets, "node_id")) == {
        relationship.endpoint_a["node_id"], relationship.endpoint_b["node_id"],
    }
    assert len(to_records(relationship.entity_definitions)) == 2


def _same_dataset_service(tmp_path: Path) -> GraphReadService:
    """A link table holding two device definitions, beside the device dataset."""
    accessor = lambda name: {"schema_id": "accessor.sqlite.v1", "properties": {
        "host": "h", "database_path": "/d.db", "schema": "main", "object": name}}
    device = lambda columns, **claims: {
        "identity_id": "device", "dataset_columns": columns, **claims}
    payload = {
        "schema_version": "4",
        "logical_identities": {"device": {"name": "Device"}},
        "nodes": [
            {"node_id": "net.device", "descriptor": {"qualified_name": "net.main.device",
                                                     "display_name": "device"},
             "accessor": accessor("device"),
             "grain": {"components": [{"identity_id": "device", "dataset_columns": ["device_id"]}]},
             "columns": [{"name": "device_id"}],
             "entity_definitions": [device(["device_id"], entity_universe="complete",
                                           unique=True, total=True, conforms=True)]},
            {"node_id": "net.device_link", "descriptor": {"qualified_name": "net.main.device_link",
                                                          "display_name": "device_link"},
             "accessor": accessor("device_link"), "grain": "unknown",
             "columns": [{"name": "device_a", "description": "source device"},
                         {"name": "device_b", "description": "target device"}],
             "entity_definitions": [
                 device(["device_a"], entity_universe="partial", unique=False, total=True,
                        conforms=True),
                 device(["device_b"], entity_universe="partial", unique=False, total=False,
                        conforms=True),
             ]},
        ],
    }
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return GraphReadService(build_snapshot_from_yaml(path)[0])


def test_a_same_dataset_relationship_gives_one_directed_edge_from_each_endpoint(tmp_path: Path) -> None:
    service = _same_dataset_service(tmp_path)
    link = "net.device_link"
    edge_id = "net.device_link:device:device_a__net.device_link:device:device_b"
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

    [route_a, route_b] = paths(service.find_paths(PathsRequest(
        from_node_id=link, to_node_id=link, max_edges=1,
    )))
    assert [(edge["from_dataset_columns"], edge["to_dataset_columns"]) for edge in route_a + route_b] == [
        (["device_a"], ["device_b"]), (["device_b"], ["device_a"]),
    ]


def test_detail_levels_and_added_fields_shape_every_dataset_and_directed_edge() -> None:
    service = _service()
    account = "sqlite:lending.account"

    essential = service.get_edges(account, detail="essential")
    assert essential.datasets.header == [
        "node_id", "qualified_name", "distance", "edge_count", "accessor.schema_id",
    ]
    # Positions only append with detail, and edge_id stays last.
    assert essential.edge_fields == ["edge", "multiplicity", "match_existence", "edge_id"]
    first = essential.edge_groups[0]["entity_definitions"][0]["edges"][0]
    assert first == [
        "sqlite:lending.account[account_id] -> sqlite:lending.account_holder[account_id]",
        "1:many", "always",
        "sqlite:lending.account:account_identity:account_id__"
        "sqlite:lending.account_holder:account_identity:account_id",
    ]
    assert service.get_edges(account).edge_fields == [
        "edge", "multiplicity", "match_existence", "reverse_multiplicity",
        "reverse_match_existence", "from_description", "to_description", "edge_id",
    ]
    assert essential.columns is None and essential.entity_definitions is None
    assert "display_name" not in str(essential.model_dump(mode="json"))

    full = service.get_edges(account, detail="full")
    assert "accessor.properties" in full.datasets.header and full.edge_fields[-2:] == [
        "annotation", "edge_id",
    ]
    assert full.columns is not None and full.entity_definitions is not None

    added = service.get_edges(
        account, detail="essential",
        fields={"edge": ["reverse_multiplicity"], "entity_definition": ["unique"]},
    )
    assert added.fields == {"edge": ["reverse_multiplicity"], "entity_definition": ["unique"]}
    assert added.edge_fields == ["edge", "multiplicity", "match_existence",
                                 "reverse_multiplicity", "edge_id"]
    assert added.entity_definitions.header == ["node_id", "identity_id", "dataset_columns", "unique"]

    with pytest.raises(ValueError, match="unknown edge fields"):
        service.get_edges(account, fields={"edge": ["display_name"]})
    with pytest.raises(ValidationError):
        service.get_edges(account, fields={"relationship": ["edge_id"]})


def test_default_bounds_do_not_depend_on_detail() -> None:
    service = _service()
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


def test_table_and_records_formats_carry_the_same_content() -> None:
    service = _service()
    account, region = "sqlite:lending.account", "sqlite:lending.customer"
    edge_id = service.index.adjacency[account][0].edge_id
    navigation = [
        lambda f: service.get_edges(account, response_format=f, detail="full"),
        lambda f: service.expand_subgraph(
            SubgraphRequest(seed_node_ids=[account], max_depth=2, response_format=f)),
        lambda f: service.find_connecting_subgraph(
            ConnectingSubgraphRequest(node_ids=[account, region], response_format=f)),
    ]
    for call in navigation:
        table = call("table").model_dump(mode="json")
        records = call("records").model_dump(mode="json")
        nested = ("edge_groups", "columns", "entity_definitions")
        assert to_records(table["datasets"]) == [
            {k: v for k, v in record.items() if k not in nested} for record in records["datasets"]
        ]
        assert table["edge_groups"] == [
            {"node_id": record["node_id"], **group}
            for record in records["datasets"] for group in record.get("edge_groups", ())
        ]
        assert {k: v for k, v in table.items() if k not in ("datasets", *nested)} == {
            k: v for k, v in records.items() if k not in ("datasets", *nested)
        }

    table = service.find_paths(PathsRequest(from_node_id=region, to_node_id="sqlite:lending.region"))
    records = service.find_paths(PathsRequest(
        from_node_id=region, to_node_id="sqlite:lending.region", response_format="records",
    ))
    assert table.routes == records.routes and table.edge_fields == records.edge_fields

    for call in (
        lambda f: service.get_identity("region_identity", response_format=f),
        lambda f: service.get_relationship(edge_id, account, response_format=f),
    ):
        table = call("table").model_dump(mode="json")
        records = call("records").model_dump(mode="json")
        tables = [key for key, value in table.items()
                  if isinstance(value, dict) and set(value) == {"header", "rows"}]
        for key in tables:
            assert to_records(table[key]) == records[key]


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
        SearchRequest(query="region_id", kind=["entity_definition"], limit=1000)
    )
    definition = next(
        subject
        for subject in _subjects(_group(response, "entity_definition"))
        if subject["node_id"] == "sqlite:lending.account"
        and subject["identity_id"] == "region_identity"
    )
    assert definition["unknown_fields"] == ["conforms"]


def test_detail_responses_expose_unknown_claims() -> None:
    service = _example_service()

    identity = service.get_identity("customer_identity")
    assert identity.description == "Unknown"
    assert [item["unknown_fields"] for item in to_records(identity.entity_definitions)] == [
        ["total"],
        [],
    ]

    dataset = service.get_dataset("dataset_b")
    assert dataset.grain == "unknown"
    assert dataset.unknown_fields == ["grain"]
    assert dataset.entity_definitions[0]["entity_universe"] == "complete"

    known = service.get_dataset("dataset_a")
    assert known.unknown_fields == []
    assert "unknown_fields" not in known.columns[2]


def test_traversal_reports_unknown_claims_relative_to_direction() -> None:
    service = _example_service()
    edge_id = "dataset_a:customer_identity:c1+c2+c3__dataset_b:customer_identity:d1+d2"

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


def test_column_names_holding_a_delimiter_are_quoted() -> None:
    assert definition_label("bank.t", ["a,b", "c"]) == 'bank.t["a,b",c]'
    assert definition_label("bank.t", ["x->y", "[z]", 'q"']) == r'bank.t["x->y","[z]","q\""]'
    for columns in (["a,b", "c"], ["x->y"], ['q"', "r"]):
        label = f'{definition_label("s", ["k"])} -> {definition_label("t", columns)}'
        assert decode(["edge"], [label])["to_dataset_columns"] == columns


def test_identity_and_relationship_lookups_name_datasets_by_qualified_name() -> None:
    service = _service()
    identity = service.get_identity("region_identity")
    assert "descriptor.display_name" not in identity.datasets.header
    assert "descriptor.qualified_name" in identity.datasets.header
    edge_id = service.index.adjacency["sqlite:lending.account"][0].edge_id
    relationship = service.get_relationship(edge_id, response_format="records")
    assert all("display_name" not in record["descriptor"] for record in relationship.datasets)
    # Dataset lookup remains the one full descriptor.
    assert service.get_dataset("sqlite:lending.account").descriptor["display_name"] == "account"


def test_subgraph_expansion_caps_listed_directed_edges_with_limit() -> None:
    with pytest.raises(ValidationError):
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], limit=1001)
    with pytest.raises(ValidationError):
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], max_edges=10)
    response = _service().expand_subgraph(
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], limit=2)
    )
    # Each of the seed's two entity definitions lists 2 of its 2 directed edges.
    assert response.limit == 2 and len(edge_records(response)) == 4 and not response.truncated
    response = _service().expand_subgraph(
        SubgraphRequest(seed_node_ids=["sqlite:lending.account"], limit=1)
    )
    assert len(edge_records(response)) == 2 and response.truncated
