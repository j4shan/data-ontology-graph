"""Detail levels, added fields, dataset records, and directed-edge labels (system design 2.4)."""

import json

import pytest
from pydantic import ValidationError

from data_ontology_graph.service.views import definition_label
from testkit.records import decode

PG_EU = "pg-eu:crm.public.customer"


def test_detail_levels_and_added_fields_shape_every_dataset_and_directed_edge(lending_service) -> None:
    service = lending_service
    account = "sqlite:lending.account"

    essential = service.get_edges(account, detail="essential")
    assert essential.datasets.header == [
        "node_id", "qualified_name", "distance", "edge_count", "accessor.kind",
    ]
    # Positions only append with detail, and edge_id stays last.
    assert essential.edge_fields == ["edge", "multiplicity", "match_existence", "edge_id"]
    first = essential.edge_groups[0]["entity_definitions"][0]["edges"][0]
    assert first == [
        "sqlite:lending.account[account_id] -> sqlite:lending.account_holder[account_id]",
        "1:many", "always", "D1-D3",
    ]
    assert service.get_edges(account).edge_fields == [
        "edge", "multiplicity", "match_existence", "reverse_multiplicity",
        "reverse_match_existence", "from_description", "to_description", "edge_id",
    ]
    assert essential.columns is None and essential.entity_definitions is None

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
    assert added.entity_definitions.header == ["id", "node_id", "identity_id", "dataset_columns", "unique"]

    with pytest.raises(ValueError, match="unknown edge fields"):
        service.get_edges(account, fields={"edge": ["display_name"]})
    with pytest.raises(ValidationError):
        service.get_edges(account, fields={"relationship": ["edge_id"]})


def test_column_names_holding_a_delimiter_are_quoted() -> None:
    assert definition_label("bank.t", ["a,b", "c"]) == 'bank.t["a,b",c]'
    assert definition_label("bank.t", ["x->y", "[z]", 'q"']) == r'bank.t["x->y","[z]","q\""]'
    for columns in (["a,b", "c"], ["x->y"], ['q"', "r"]):
        label = f'{definition_label("s", ["k"])} -> {definition_label("t", columns)}'
        assert decode(["edge"], [label])["to_dataset_columns"] == columns


def test_node_ids_holding_a_delimiter_are_quoted() -> None:
    """A free-text node ID cannot break the label's parse (system design 2.4.1)."""
    assert definition_label("a[b]", ["id"]) == '"a[b]"[id]'
    assert definition_label("sqlite:lending.account", ["id"]) == "sqlite:lending.account[id]"
    for start, end in (("a[b]", "c"), ("x -> y", 'q"'), ("p,q", "r]")):
        label = f'{definition_label(start, ["k"])} -> {definition_label(end, ["m", "n"])}'
        edge = decode(["edge"], [label])
        assert (edge["from_node_id"], edge["to_node_id"]) == (start, end)
        assert (edge["from_dataset_columns"], edge["to_dataset_columns"]) == (["k"], ["m", "n"])


def test_every_response_presents_a_dataset_as_one_record(lending_service) -> None:
    service = lending_service
    account = "sqlite:lending.account"
    edge_id = min(edge.edge_id for edge in service.index.directed_edges[account])
    standard = ["node_id", "qualified_name", "accessor", "grain", "descriptor", "unknown_fields"]
    navigation = service.get_edges(account, response_format="records").datasets[0]
    identity = service.get_entity_definitions("region_identity", response_format="records").datasets[0]
    relationship = service.get_relationship(edge_id, response_format="records").datasets[0]
    assert list(navigation) == ["node_id", "qualified_name", "distance", "edge_count", "accessor",
                                "grain", "descriptor", "unknown_fields", "edge_groups"]
    assert list(identity) == list(relationship) == standard
    assert identity["descriptor"] == relationship["descriptor"] == {"description": identity["descriptor"]["description"]}
    # Every response carries the snapshot tag that IDs are local to (3.6.2).
    assert service.get_dataset(account).snapshot == service.get_relationship(edge_id).snapshot
    assert service.get_dataset(account).snapshot.version == service.snapshot_info().version
    full = service.get_dataset(account).model_dump(mode="json", exclude={"snapshot"})
    full_navigation = service.get_edges(account, response_format="records", detail="full").datasets[0]
    assert full == {key: value for key, value in full_navigation.items()
                    if key not in ("distance", "edge_count", "edge_groups")}
    assert service.get_entity_definitions("region_identity").datasets.header == [
        "node_id", "qualified_name", "accessor.kind", "accessor.endpoint", "accessor.labels",
        "grain", "descriptor.description", "unknown_fields",
    ]
    # The display name is a full-detail descriptor field.
    assert full["descriptor"]["display_name"] == "account"
    assert "display_name" not in json.dumps(navigation) + json.dumps(identity)


def test_detail_levels_add_accessor_fields(open_accessor_service) -> None:
    service = open_accessor_service
    accessor_fields = {
        detail: [
            name for name in service.get_edges(PG_EU, detail=detail).datasets.header
            if name.startswith("accessor.")
        ]
        for detail in ("essential", "standard", "full")
    }
    assert accessor_fields == {
        "essential": ["accessor.kind"],
        "standard": ["accessor.kind", "accessor.endpoint", "accessor.labels"],
        "full": ["accessor.kind", "accessor.endpoint", "accessor.labels", "accessor.properties"],
    }
    added = service.get_edges(
        PG_EU, detail="essential", fields={"dataset": ["accessor.properties"]}
    )
    assert "accessor.properties" in added.datasets.header
