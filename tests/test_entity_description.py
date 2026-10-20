from pathlib import Path

import pytest
import yaml

from data_ontology_graph.akg.projection import project_dataset
from data_ontology_graph.builder import build_snapshot_from_yaml
from data_ontology_graph.model.dataset import effective_description
from data_ontology_graph.service.read import GraphReadService


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


def _region_definition(records: list[dict]) -> dict:
    return next(
        record for record in records
        if record["node_id"] == "sqlite:lending.account"
        and record["identity_id"] == "region_identity"
    )


def test_service_records_carry_the_column_description_by_default(tmp_path: Path) -> None:
    service = _service(tmp_path)
    hops = service.get_hops("sqlite:lending.region", response_format="records")
    definition = _region_definition(hops.entity_definitions)
    assert definition["description"] == ""
    assert definition["effective_description"] == "region of the opening branch"
    assert definition["description_source"] == "column"


def test_an_authored_description_wins_everywhere(tmp_path: Path) -> None:
    service = _service(tmp_path, "the region of the branch where the account was opened")
    detail = [
        {"node_id": "sqlite:lending.account", **record}
        for record in service.get_dataset("sqlite:lending.account").entity_definitions
    ]
    hops = service.get_hops("sqlite:lending.region", response_format="records")
    identity = service.get_identity("region_identity", response_format="records")
    for records in (detail, hops.entity_definitions, identity.entity_definitions):
        definition = _region_definition(records)
        assert definition["effective_description"].startswith("the region of the branch")
        assert definition["description_source"] == "entity"


def test_akg_projection_copies_the_effective_description(tmp_path: Path) -> None:
    service = _service(tmp_path)
    node = service.get_dataset("sqlite:lending.account").model_dump(mode="json")
    definitions = project_dataset(node, "standard")["entity_definitions"]
    assert {
        "identity_id": "region_identity",
        "dataset_columns": ["region_id"],
        "entity_universe": "unknown",
        "description": "region of the opening branch",
        "description_source": "column",
    } in definitions
