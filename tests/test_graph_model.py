import pytest
from pydantic import ValidationError

from data_ontology_graph.model.dataset import ColumnMetadata, DatasetNode, DeclaredForeignKey
from data_ontology_graph.model.enums import Cardinality, DatasetLayer, Precedence, TableRole
from data_ontology_graph.model.relationship import (
    JoinEndpoint,
    cardinality_from,
    derived_cardinality,
    edge_id_for,
    entity_anchor,
    make_relationship,
    unique_side,
)
from data_ontology_graph.model.snapshot import GraphSnapshot, empty_sql_db_source, now_utc


def _columns(*names: str, nullable: bool = True) -> list[ColumnMetadata]:
    return [ColumnMetadata(name=name, is_nullable=nullable) for name in names]


def _node(
    table: str,
    columns: list[str],
    primary_key: list[str] | None = None,
    layer: DatasetLayer = DatasetLayer.PRIMARY,
    **kwargs,
) -> DatasetNode:
    return DatasetNode(
        node_id=f"sql_db:demo.{table}",
        table_name=table,
        data_source=empty_sql_db_source("demo", table),
        columns=_columns(*columns),
        primary_key=primary_key or [],
        dataset_layer=layer,
        **kwargs,
    )


def test_duplicate_column_names_rejected() -> None:
    with pytest.raises(ValidationError):
        _node("t", ["id", "id"], primary_key=["id"])


def test_primary_key_must_exist_on_primary() -> None:
    with pytest.raises(ValidationError):
        _node("t", ["name"], primary_key=["id"])


def test_foreign_key_columns_must_exist_on_primary() -> None:
    with pytest.raises(ValidationError):
        _node(
            "t",
            ["id"],
            primary_key=["id"],
            foreign_key_declarations=[
                DeclaredForeignKey(local_columns=["missing"], ref_table="other", ref_columns=["id"])
            ],
        )


def test_logical_entity_key_must_be_subset_of_primary_key() -> None:
    with pytest.raises(ValidationError):
        _node(
            "t",
            ["a", "b", "c"],
            primary_key=["a", "b"],
            logical_entity_key={"x": ["c"]},
        )


def test_empty_grain_component_discarded() -> None:
    node = DatasetNode(
        node_id="sql_db:demo.t",
        table_name="t",
        data_source=empty_sql_db_source("demo", "t"),
        columns=_columns("id"),
        primary_key=["id"],
        grain=[],
    )
    assert node.grain == []


def test_cardinality_rules() -> None:
    assert cardinality_from(True, True) == Cardinality.ONE_TO_ONE
    assert cardinality_from(False, True) == Cardinality.N_TO_ONE
    assert cardinality_from(True, False) == Cardinality.ONE_TO_N
    assert cardinality_from(False, False) == Cardinality.M_TO_N


def test_edge_id_stable_under_swap() -> None:
    campaign = JoinEndpoint(node_id="camp", columns=["CampaignId"], is_unique=True)
    event = JoinEndpoint(node_id="event", columns=["CampaignId"], is_unique=False)
    assert edge_id_for(campaign, event) == edge_id_for(event, campaign)
    left = make_relationship(event, campaign, Precedence.DECLARED)
    right = make_relationship(campaign, event, Precedence.DECLARED)
    assert left.edge_id == right.edge_id
    assert left.endpoint_a.node_id == right.endpoint_a.node_id


def test_derived_cardinality_depends_on_direction() -> None:
    campaign = _node("campaign", ["CampaignId"], primary_key=["CampaignId"])
    event = _node("event", ["id", "CampaignId"], primary_key=["id"])
    rel = make_relationship(
        JoinEndpoint(node_id=event.node_id, columns=["CampaignId"], is_unique=False),
        JoinEndpoint(node_id=campaign.node_id, columns=["CampaignId"], is_unique=True),
    )
    assert derived_cardinality(rel, event.node_id) == Cardinality.N_TO_ONE
    assert derived_cardinality(rel, campaign.node_id) == Cardinality.ONE_TO_N
    assert unique_side(rel) == campaign.node_id
    assert entity_anchor(rel, {campaign.node_id: campaign, event.node_id: event}) == campaign.node_id


def test_secondary_cannot_own_edges() -> None:
    primary = _node("campaign", ["CampaignId"], primary_key=["CampaignId"])
    replica = _node(
        "campaign_copy",
        ["CampaignId"],
        primary_key=["CampaignId"],
        layer=DatasetLayer.SECONDARY,
    )
    rel = make_relationship(
        JoinEndpoint(node_id=primary.node_id, columns=["CampaignId"], is_unique=True),
        JoinEndpoint(node_id=replica.node_id, columns=["CampaignId"], is_unique=True),
    )
    with pytest.raises(ValidationError):
        GraphSnapshot(
            built_at=now_utc(),
            nodes=[primary, replica],
            edges=[rel],
        )


def test_table_role_default_unknown() -> None:
    node = _node("t", ["id"], primary_key=["id"])
    assert node.table_role == TableRole.UNKNOWN
