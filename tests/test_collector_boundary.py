import ast
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1] / "src" / "data_ontology_graph"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package_parts = path.relative_to(PACKAGE.parent).with_suffix("").parts[:-1]
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            names.append(module)
            names.extend(f"{module}.{alias.name}" for alias in node.names)
    return names


def _core_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_core_modules_never_import_the_collector(path):
    offending = [
        name
        for name in _imports(path)
        if name == "ddl_collector" or name.startswith("ddl_collector.")
    ]

    assert offending == []


def test_relative_imports_are_resolved_by_the_scan(tmp_path):
    module = PACKAGE / "builder" / "__init__.py"
    names = _imports(module)

    assert "data_ontology_graph.builder.intermediary" in names
