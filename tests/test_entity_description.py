from pathlib import Path

import pytest
import yaml

from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.dataset import effective_description
from data_ontology_graph.service.read import GraphReadService
from graph_records import dataset_edges


LENDING = Path(__file__).resolve().parent / "fixtures" / "lending" / "catalog.yaml"
COLUMNS = {"region_id": "region of the opening branch", "plant_id": "", "item_id": "the item"}


@pytest.mark.parametrize(
    ("description", "columns", "expressions", "expected"),
    [
        ("opening-branch region", ["region_id"], ["[region_id]"], ("opening-branch region", "entity")),
        ("", ["region_id"], ["[region_id]"], ("region of the opening branch", "column")),
        ("", ["region_id"], [], ("region of the opening branch", "column")),
        ("", ["region_id"], ["region_id", '"region_id"', "`region_id`"], ("region of the opening branch", "column")),
        ("", ["region_id"], ["upper([region_id])"], None),
        ("", ["item_id", "plant_id"], ["[item_id]", "[plant_id]"], None),
        ("", ["plant_id"], ["[plant_id]"], None),
        ("planning slot", ["item_id", "plant_id"], [], ("planning slot", "entity")),
    ],
    ids=[
        "own description wins",
        "single raw column",
        "no expression is raw",
        "wrapped references are raw",
        "transformed column",
        "composite key",
        "empty column description",
        "composite key with own description",
    ],
)
def test_effective_description_rule(description, columns, expressions, expected) -> None:
    assert effective_description(description, columns, expressions, COLUMNS) == expected


def _service(tmp_path: Path, description: str | None = None) -> GraphReadService:
    payload = yaml.safe_load(LENDING.read_text(encoding="utf-8"))
    if description is not None:
        account = next(node for node in payload["nodes"] if node["node_id"] == "sqlite:lending.account")
        region = next(
            definition for definition in account["entity_definitions"]
            if definition["identity_id"] == "region_identity"
        )
        region["description"] = description
    source = tmp_path / "catalog.yaml"
    source.write_text(yaml.safe_dump(payload), encoding="utf-8")
    snapshot, _, _ = build_snapshot_from_yaml(source)
    return GraphReadService(snapshot)


def _full_definitions(response) -> list[dict]:
    """Entity definitions nested in a records-format navigation response, with their node_id."""
    return [
        {"node_id": dataset["node_id"], **definition}
        for dataset in response.datasets for definition in dataset["entity_definitions"]
    ]


def _region_edge(response) -> dict:
    [region] = [d for d in response.datasets if d["node_id"] == "sqlite:lending.region"]
    return next(edge for edge in dataset_edges(region, response.edge_fields) if edge["to_node_id"] == "sqlite:lending.account")


def _region_definition(records: list[dict]) -> dict:
    return next(
        record for record in records
        if record["node_id"] == "sqlite:lending.account"
        and record["identity_id"] == "region_identity"
    )


def test_service_records_carry_the_column_description_by_default(tmp_path: Path) -> None:
    service = _service(tmp_path)
    edges = service.get_edges("sqlite:lending.region", response_format="records", detail="full")
    definition = _region_definition(_full_definitions(edges))
    assert definition["description"] == ""
    assert definition["effective_description"] == "region of the opening branch"
    assert definition["description_source"] == "column"
    assert _region_edge(edges)["to_description"] == "region of the opening branch"


def test_an_authored_description_wins_everywhere(tmp_path: Path) -> None:
    service = _service(tmp_path, "the region of the branch where the account was opened")
    detail = [
        {"node_id": "sqlite:lending.account", **record}
        for record in service.get_dataset("sqlite:lending.account").entity_definitions
    ]
    edges = service.get_edges("sqlite:lending.region", response_format="records", detail="full")
    identity = service.get_identity("region_identity", response_format="records")
    assert _region_edge(edges)["to_description"].startswith("the region of the branch")
    for records in (detail, _full_definitions(edges), identity.entity_definitions):
        definition = _region_definition(records)
        assert definition["effective_description"].startswith("the region of the branch")
        assert definition["description_source"] == "entity"
