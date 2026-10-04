import json
import re
from pathlib import Path

import pytest
import yaml

from data_ontology_graph.builder.intermediary import load_intermediary_yaml
from ddl_collector.cli import main


def _run(capsys, *args: str) -> tuple[int, dict]:
    code = main(list(args))
    captured = capsys.readouterr()
    output = captured.out or captured.err
    return code, json.loads(output)


def _extract(capsys, critic_root: Path, scratch: Path) -> dict:
    code, summary = _run(
        capsys,
        "extract",
        "--critic-root",
        str(critic_root),
        "--catalog",
        "minibank",
        "--scratch",
        str(scratch),
        "--source-root",
        "/srv/sources",
    )
    assert code == 0, summary
    return summary


def _answer_all(scratch: Path, status: str = "answered") -> None:
    survey = scratch / "survey.md"
    text = re.sub(
        r"```answer\n.*?```",
        f"```answer\nstatus: {status}\nvalue: {{}}\nrationale: reviewed in test\n```",
        survey.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    survey.write_text(text, encoding="utf-8")


def _finalize(capsys, critic_root: Path, scratch: Path) -> None:
    _extract(capsys, critic_root, scratch)
    _answer_all(scratch)
    code, summary = _run(capsys, "apply", "--scratch", str(scratch))
    assert code == 0, summary
    assert summary["unresolved"] == 0


def test_extract_writes_a_valid_draft_and_an_open_survey(capsys, critic_root, tmp_path):
    scratch = tmp_path / "scratch" / "s1"
    summary = _extract(capsys, critic_root, scratch)

    assert summary["valid"] is True
    assert (summary["nodes"], summary["edges"], summary["unresolved"]) == (4, 3, 7)
    for name in ("session.yaml", "evidence.json", "decisions.yaml", "survey.md", "report.json"):
        assert (scratch / name).is_file()
    assert (scratch / "draft" / "directory-manifest.yaml").is_file()


def test_publish_refuses_while_decisions_are_open(capsys, critic_root, tmp_path):
    scratch = tmp_path / "scratch" / "s1"
    _extract(capsys, critic_root, scratch)

    code, refusal = _run(capsys, "publish", "--scratch", str(scratch), "--catalog-root", str(tmp_path / "out"))

    assert code == 1
    assert refusal["error"] == "publish_refused"
    assert any("unresolved decisions" in reason for reason in refusal["reasons"])
    assert not (tmp_path / "out" / "minibank").exists()


def test_publish_writes_the_four_part_catalog(capsys, critic_root, tmp_path):
    scratch = tmp_path / "scratch" / "s1"
    out = tmp_path / "out"
    _finalize(capsys, critic_root, scratch)

    code, result = _run(capsys, "publish", "--scratch", str(scratch), "--catalog-root", str(out))

    assert code == 0, result
    target = out / "minibank"
    assert sorted(path.name for path in target.iterdir()) == [
        "decisions.md",
        "directory-manifest.yaml",
        "provenance.yaml",
        "yaml",
    ]
    definition = load_intermediary_yaml(target / "yaml")
    assert len(definition.nodes) == 4 and len(definition.edges) == 3
    provenance = yaml.safe_load((target / "provenance.yaml").read_text(encoding="utf-8"))
    session = yaml.safe_load((scratch / "session.yaml").read_text(encoding="utf-8"))
    assert provenance["schema_version"] == "3"
    assert provenance["source"]["files"] == session["source_files"]
    assert provenance["source"]["source_root"] == "/srv/sources"
    assert provenance["review"] == {"rounds": 1, "decisions": {"answered": 7}}
    assert provenance["counts"] == {"identities": 3, "nodes": 4, "edges": 3}
    assert "## grain.branch" in (target / "decisions.md").read_text(encoding="utf-8")
    assert not [path for path in out.iterdir() if path.name.startswith(".")]


def test_republish_replaces_the_previous_catalog(capsys, critic_root, tmp_path):
    scratch = tmp_path / "scratch" / "s1"
    out = tmp_path / "out"
    _finalize(capsys, critic_root, scratch)
    (out / "minibank" / "yaml").mkdir(parents=True)
    stale = out / "minibank" / "yaml" / "stale.yaml"
    stale.write_text("schema_version: '3'\n", encoding="utf-8")

    code, _ = _run(capsys, "publish", "--scratch", str(scratch), "--catalog-root", str(out))

    assert code == 0
    assert not stale.exists()
    load_intermediary_yaml(out / "minibank" / "yaml")
    assert sorted(path.name for path in out.iterdir()) == ["minibank"]


def test_publish_refuses_when_sources_changed_after_extraction(capsys, critic_root, tmp_path):
    scratch = tmp_path / "scratch" / "s1"
    _finalize(capsys, critic_root, scratch)
    csv_file = critic_root / "resources/data/dev_databases/minibank/database_description/branch.csv"
    csv_file.write_text(csv_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    code, refusal = _run(capsys, "publish", "--scratch", str(scratch), "--catalog-root", str(tmp_path / "out"))

    assert code == 1
    assert any("source verification failed" in reason for reason in refusal["reasons"])


def test_malformed_survey_is_rejected_without_changing_decisions(capsys, critic_root, tmp_path):
    scratch = tmp_path / "scratch" / "s1"
    _extract(capsys, critic_root, scratch)
    before = (scratch / "decisions.yaml").read_text(encoding="utf-8")
    _answer_all(scratch, status="perhaps")

    code, rejection = _run(capsys, "apply", "--scratch", str(scratch))

    assert code == 2
    assert rejection["error"] == "survey_rejected"
    assert (scratch / "decisions.yaml").read_text(encoding="utf-8") == before


def test_commands_without_a_session_fail_cleanly(capsys, tmp_path):
    code, error = _run(capsys, "validate", "--scratch", str(tmp_path / "missing"))

    assert code == 2
    assert "run extract first" in error["message"]


@pytest.mark.parametrize("status", ["unknown", "waived"])
def test_unknown_or_waived_answers_publish_with_explicit_unknowns(capsys, critic_root, tmp_path, status):
    scratch = tmp_path / "scratch" / "s1"
    _extract(capsys, critic_root, scratch)
    _answer_all(scratch, status=status)
    code, summary = _run(capsys, "apply", "--scratch", str(scratch))

    # Every grain is unknown, so no identity exists and the intermediary cannot validate.
    assert code == 1
    assert summary["valid"] is False
