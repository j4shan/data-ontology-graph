"""Open dataset accessors (product/graph-model.md 2.6-2.8; system design 3.2.1-3.2.2)."""

import copy

import pytest
import yaml
from pydantic import ValidationError

from data_ontology_graph.builder import build_snapshot_from_definition, build_snapshot_from_yaml
from data_ontology_graph.model.dataset import ACCESSOR_SOFT_LIMIT, DatasetAccessor
from data_ontology_graph.model.intermediary import IntermediaryDefinition
from data_ontology_graph.model.snapshot import GraphSnapshot
from testkit import OPEN_ACCESSOR as OPEN


PG_EU = "pg-eu:crm.public.customer"
PG_US = "pg-us:crm.public.customer"
S3 = "s3-us:web.clickstream"


def _payload() -> dict:
    return yaml.safe_load(OPEN.read_text(encoding="utf-8"))


def _node(payload: dict, node_id: str) -> dict:
    return next(node for node in payload["nodes"] if node["node_id"] == node_id)


@pytest.mark.parametrize(
    "accessor",
    [
        {"kind": "kafka", "endpoint": "kafka://broker-1.apac.acme.internal:9093"},
        {"kind": "postgresql", "endpoint": "https://acme.atlassian.net/wiki/x",
         "labels": {"connection": "crm-eu"}},
        {"kind": "mongodb", "endpoint": "mongodb+srv://apac-app.x7k2q.mongodb.net",
         "properties": {"database": "app", "filter": {"doc_type": ["profile", "login"]},
                        "sample_rows": 100, "sharded": True}},
    ],
)
def test_accessor_takes_any_kind_and_endpoint_with_optional_labels_and_properties(
    accessor: dict,
) -> None:
    assert DatasetAccessor.model_validate(accessor).model_dump(exclude_defaults=True) == accessor


@pytest.mark.parametrize(
    ("accessor", "message"),
    [
        ({"endpoint": "x"}, "kind"),
        ({"kind": "k"}, "endpoint"),
        ({"kind": "   ", "endpoint": "x"}, "pattern"),
        ({"kind": "k", "endpoint": ""}, "pattern"),
        ({"kind": "k", "endpoint": "x", "labels": {"region": 1}}, "valid string"),
        ({"kind": "k", "endpoint": "x", "labels": {"": "emea"}}, "at least 1 character"),
        ({"kind": "k", "endpoint": "x", "properties": {}}, "at least 1 item"),
        ({"kind": "k", "endpoint": "x", "schema_id": "accessor.sqlite.v1"}, "Extra inputs"),
    ],
)
def test_accessor_rejects_missing_or_blank_required_fields_and_empty_optional_fields(
    accessor: dict, message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        DatasetAccessor.model_validate(accessor)


def test_open_accessor_catalog_builds_every_provider_without_warnings() -> None:
    snapshot, report = build_snapshot_from_yaml(OPEN)
    assert report.node_count == 10 and report.warnings == []
    kinds = {node.accessor.kind for node in snapshot.nodes}
    assert kinds == {
        "databricks", "snowflake", "mongodb", "postgresql", "s3", "adls-gen2", "kafka",
        "sharepoint list",
    }


@pytest.mark.parametrize(("length", "warned"), [(ACCESSOR_SOFT_LIMIT, False),
                                                (ACCESSOR_SOFT_LIMIT + 1, True)])
def test_soft_limit_warns_and_never_rejects(length: int, warned: bool) -> None:
    payload = _payload()
    # `{"endpoint":"…","kind":"k"}` adds 26 characters around the endpoint.
    _node(payload, S3)["accessor"] = {"kind": "k", "endpoint": "e" * (length - 26)}
    snapshot, report = build_snapshot_from_definition(
        IntermediaryDefinition.model_validate(payload)
    )
    assert len(snapshot.nodes_by_id[S3].accessor.canonical_json()) == length
    expected = [
        f"nodes[{S3}].accessor: {length} characters exceeds the 256-character soft limit"
    ]
    assert report.warnings == (expected if warned else [])


def test_equal_accessors_are_rejected_even_when_labels_differ() -> None:
    payload = _payload()
    duplicate = copy.deepcopy(_node(payload, PG_US)["accessor"])
    duplicate["labels"] = {"connection": "crm-eu"}
    _node(payload, PG_EU)["accessor"] = duplicate
    with pytest.raises(ValidationError, match="same accessor kind, endpoint, and properties"):
        IntermediaryDefinition.model_validate(payload)

    snapshot, _ = build_snapshot_from_yaml(OPEN)
    data = snapshot.model_dump(mode="json")
    nodes = {node["node_id"]: node for node in data["nodes"]}
    nodes[PG_EU]["accessor"] = nodes[PG_US]["accessor"]
    with pytest.raises(ValidationError, match="same accessor"):
        GraphSnapshot.model_validate(data)


def test_datasets_may_share_an_endpoint_when_properties_differ() -> None:
    nodes = build_snapshot_from_yaml(OPEN)[0].nodes_by_id
    profiles = nodes["mongo-apac:app.customer_profiles"].accessor
    logins = nodes["mongo-apac:app.customer_logins"].accessor
    assert profiles.endpoint == logins.endpoint and profiles.properties != logins.properties


def test_dataset_record_returns_the_accessor_as_written(open_accessor_service) -> None:
    service = open_accessor_service
    assert service.get_dataset(PG_EU).accessor == {
        "kind": "postgresql",
        "endpoint": "https://acme.atlassian.net/wiki/spaces/DATA/pages/48213/EU+CRM+database+access",
        "labels": {"connection": "crm-eu"},
        "properties": {"database": "crm", "schema": "public", "table": "customer"},
    }
    assert service.get_dataset(S3).accessor == {
        "kind": "s3", "endpoint": "s3://acme-raw-us/web/clickstream/", "labels": {},
        "properties": None,
    }
