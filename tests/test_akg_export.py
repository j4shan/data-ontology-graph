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
    loan, account = (payload["datasets"][f"sqlite:lending.{name}"] for name in ("loan", "account"))
    edge = loan.pop("edges")[0]
    account["edges"].insert(0, edge | {
        "to_node_id": "sqlite:lending.loan",
        "multiplicity": edge["reverse_multiplicity"],
        "match_existence": edge["reverse_match_existence"],
        "reverse_multiplicity": edge["multiplicity"],
        "reverse_match_existence": edge["match_existence"],
    })
    text = export_markdown(payload)
    assert "### account.account_id → loan.account_id" in text
    assert "- Each account row matches any number of loan rows; some match none." in text


def test_export_disambiguates_colliding_aliases() -> None:
    payload = _payload("akg-data-gap")
    payload["datasets"]["sqlite:archive.region"] = {"name": "archive.main.region", "source": "sqlite"}
    text = export_markdown(payload)
    assert "| lending.main.region |" in text and "| archive.main.region |" in text


def test_cli_export_refuses_a_document_with_errors(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "akg.json"
    broken.write_text(json.dumps({"status": "draft"}), encoding="utf-8")
    assert main(["export", str(broken)]) == 1
    assert main(["export", str(LENDING / "akg-single.json")]) == 0
    assert capsys.readouterr().out.endswith((LENDING / "akg-single.md").read_text(encoding="utf-8"))
