from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_ontology_graph.akg.model import AkgDocument


def akg_json_schema() -> dict[str, Any]:
    """Return the self-contained AKG schema generated from the document model."""
    return AkgDocument.model_json_schema(by_alias=True)


def write_akg_json_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(akg_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
