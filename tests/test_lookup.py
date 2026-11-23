"""Snapshot information, dataset lookup, and entity-definition lookup (system design 2.3.1-2.3.5)."""

import re

import pytest
from pydantic import ValidationError

from data_ontology_graph.model import derivation
from data_ontology_graph.service.contracts import SearchRequest
from data_ontology_graph.service.read import GraphReadService
from data_ontology_graph.service.tables import to_records
from testkit.records import by_id


def test_service_initialization_and_membership_lookup_do_not_construct_pairs(lending_snapshot, monkeypatch) -> None:
    def unexpected_pair(*args, **kwargs):
        pytest.fail("service startup and membership inspection must not construct pairs")

    with monkeypatch.context() as guard:
        guard.setattr(derivation, "JoinRelationship", unexpected_pair)
        service = GraphReadService(lending_snapshot)
        assert service.snapshot_info().entity_definition_count == 10
        assert service.get_dataset("sqlite:lending.account").node_id == "sqlite:lending.account"
        assert service.get_entity_definitions("account_identity").entity_definitions
        assert service.search(SearchRequest(query="account", kind=["identity"])).groups
        assert len(service.index.directed_edges["sqlite:lending.account"]) == 4

    # Concrete pair objects are produced by relationship requests, with no retained pair cache.
    keys = service.index.memberships.by_identity["account_identity"]
    edge_id = service.index.memberships.edge_id(keys[0], keys[1])
    first = service.get_relationship(edge_id)
    assert first.edge_id == edge_id
    memberships = service.index.memberships
    assert memberships.relationship(edge_id) is not memberships.relationship(edge_id)
    # The index offers no way to list every relationship.
    assert not hasattr(memberships, "__iter__") and not hasattr(memberships, "__getitem__")


def test_snapshot_info_names_the_api_version_and_the_snapshot_build_second(lending_service) -> None:
    info = lending_service.snapshot_info().model_dump()
    assert set(info) == {"api_version", "version", "node_count", "entity_definition_count", "identity_count",
                         "entity_relationship_count"}
    assert info["api_version"] == "6"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", info["version"])


def test_identity_and_dataset_lookup_expose_target_model(lending_service) -> None:
    service = lending_service
    identity = service.get_entity_definitions("customer_identity")
    definitions = to_records(identity.entity_definitions)
    assert definitions
    assert set(by_id(identity.datasets, "node_id")) == {item["node_id"] for item in definitions}
    assert {item["node_id"] for item in definitions} >= {
        "sqlite:lending.customer",
        "sqlite:lending.account_holder",
    }

    dataset = service.get_dataset("sqlite:lending.account")
    assert dataset.qualified_name == "lending.main.account"
    assert dataset.accessor["kind"] == "sqlite"
    assert dataset.accessor["endpoint"] == "/srv/fixtures/lending.sqlite"
    assert dataset.accessor["labels"] == {}
    assert dataset.accessor["properties"]["schema"] == "main"
    assert dataset.accessor["properties"]["object"] == "account"
    assert dataset.entity_definitions


def test_identity_definitions_filter_by_universe_and_respect_limit(lending_service) -> None:
    service = lending_service
    region = service.get_entity_definitions("region_identity")
    assert [item["node_id"] for item in to_records(region.entity_definitions)] == [
        "sqlite:lending.account", "sqlite:lending.customer", "sqlite:lending.region",
    ]
    assert region.truncated is False

    limited = service.get_entity_definitions("region_identity", limit=2)
    assert [item["node_id"] for item in to_records(limited.entity_definitions)] == [
        "sqlite:lending.account", "sqlite:lending.customer",
    ]
    assert limited.truncated is True

    # The filter applies before the limit, so the complete realization is never cut.
    complete = service.get_entity_definitions("region_identity", entity_universe=["complete"], limit=1)
    assert [item["node_id"] for item in to_records(complete.entity_definitions)] == [
        "sqlite:lending.region",
    ]
    assert complete.truncated is False
    empty = service.get_entity_definitions("loan_identity", entity_universe=["complete"])
    assert to_records(empty.entity_definitions) == [] and to_records(empty.datasets) == []
    with pytest.raises(ValidationError):
        service.get_entity_definitions("region_identity", entity_universe=[])


def test_detail_responses_expose_unknown_claims(example_service) -> None:
    service = example_service

    identity = service.get_entity_definitions("customer_identity")
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
