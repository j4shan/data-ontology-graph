import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "query-graph-api"
SCRIPTS = sorted((SKILL / "scripts").glob("*.py"))
BUNDLED = {script.stem for script in SCRIPTS}


def test_bundled_scripts_import_only_the_standard_library_and_each_other() -> None:
    assert {script.name for script in SCRIPTS} == {"graph_call.py", "query.py", "service.py"}
    for script in SCRIPTS:
        tree = ast.parse(script.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        }
        assert imported - {"__future__"} - BUNDLED <= set(sys.stdlib_module_names), script.name


def test_the_skill_names_no_project_code() -> None:
    for path in SKILL.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".py", ".yaml"}:
            text = path.read_text(encoding="utf-8")
            assert "data_ontology_graph" not in text and "../.." not in text, path
