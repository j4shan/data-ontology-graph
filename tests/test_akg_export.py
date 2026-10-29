import json
from pathlib import Path

import pytest

from data_ontology_graph.akg.cli import main
from data_ontology_graph.akg.export import export_markdown


LENDING = Path(__file__).resolve().parent / "fixtures" / "lending"
FIXTURES = ["akg-single", "akg-disjoint", "akg-data-gap"]


def _payload(name: str) -> dict:
    return json.loads((LENDING / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", FIXTURES)
def test_export_matches_golden(name: str) -> None:
    assert export_markdown(_payload(name)) == (LENDING / f"{name}.md").read_text(encoding="utf-8")


def test_export_orients_each_directed_edge_from_the_dataset_that_holds_it() -> None:
    payload = _payload("akg-single")
    loan, account = payload["datasets"][0], payload["datasets"][1]
    group = loan.pop("edge_groups")[0]
    [edge] = group["entity_definitions"][0]["edges"]
    account["edge_groups"].insert(0, {"identity_id": "account_identity", "entity_definitions": [{
        "dataset_columns": ["account_id"],
        "edges": [[
            "sqlite:lending.account[account_id] -> sqlite:lending.loan[account_id]",
            edge[3], edge[4], edge[1], edge[2], edge[6], edge[5], edge[7],
        ]],
    }]})
    text = export_markdown(payload)
    assert "### account.account_id → loan.account_id" in text
    assert "- Each account row matches any number of loan rows; some match none." in text


def test_export_disambiguates_colliding_aliases() -> None:
    payload = _payload("akg-data-gap")
    payload["datasets"].append({"node_id": "sqlite:archive.region", "qualified_name": "archive.main.region",
                                "accessor": {"schema_id": "accessor.sqlite.v1"}})
    text = export_markdown(payload)
    assert "| lending.main.region |" in text and "| archive.main.region |" in text


def test_cli_export_refuses_a_document_with_errors(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "akg.json"
    broken.write_text(json.dumps({"status": "draft"}), encoding="utf-8")
    assert main(["export", str(broken)]) == 1
    assert main(["export", str(LENDING / "akg-single.json")]) == 0
    assert capsys.readouterr().out.endswith((LENDING / "akg-single.md").read_text(encoding="utf-8"))
