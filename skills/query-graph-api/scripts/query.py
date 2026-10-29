#!/usr/bin/env python3
"""Proxy graph calls with question metadata and one Markdown section per traversal."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from graph_call import call, default_socket  # noqa: E402


TRAVERSAL_METHODS = {
    "graph.get_edges", "graph.expand_subgraph", "graph.find_paths",
    "graph.find_connecting_subgraph",
}


def load_context(path: Path, question: str | None) -> dict:
    if not path.exists():
        if not question or not question.strip():
            raise ValueError("--question is required when creating a context")
        return {"question": question, "logical_entities": []}
    context = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(context, dict) or set(context) != {"question", "logical_entities"}:
        raise ValueError("context must contain question and logical_entities")
    if not isinstance(context["question"], str) or not context["question"].strip():
        raise ValueError("context question must be a nonempty string")
    if question is not None and question != context["question"]:
        raise ValueError("use a separate context for a different question")
    entities = context["logical_entities"]
    if not isinstance(entities, list) or any(not isinstance(name, str) for name in entities):
        raise ValueError("logical_entities must be an array of names")
    return context


def triple_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"""', '\\"""')
    return '"""' + escaped + '"""'


def save_context(path: Path, context: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as output:
            temporary = Path(output.name)
            output.write(json.dumps(context, indent=2, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def append_traversal(path: Path, method: str, params: dict, response: dict) -> None:
    request = json.dumps({"method": method, "params": params}, indent=2, ensure_ascii=False)
    payload = json.dumps(response, indent=2, ensure_ascii=False)
    section = (f"## {method}\n\n```python\n{{\n"
               f'  "request": {triple_string(request)},\n'
               f'  "response": {triple_string(payload)}\n'
               "}\n```\n\n")
    with path.open("a", encoding="utf-8") as output:
        output.write(section)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method")
    parser.add_argument("params", nargs="?", default="{}")
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--question")
    parser.add_argument("--entity", action="append", default=[])
    parser.add_argument("--socket", type=Path)
    args = parser.parse_args(argv)
    path = args.context.expanduser().resolve()
    try:
        params = json.loads(args.params)
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
        context = load_context(path, args.question)
        for name in args.entity:
            if not name.strip():
                raise ValueError("--entity must be nonempty")
            if name not in context["logical_entities"]:
                context["logical_entities"].append(name)
        save_context(path, context)
        with path.with_suffix(".traversals.md").open("a", encoding="utf-8"):
            pass
    except (OSError, ValueError, SyntaxError) as error:
        print(json.dumps({"error": {"message": str(error)}}))
        return 2
    method = args.method if args.method.startswith("graph.") else "graph." + args.method
    socket_path = (args.socket or default_socket()).expanduser().resolve()
    try:
        answer = call(socket_path, method, params)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": {"message": str(error)}}))
        return 1
    response = {key: answer[key] for key in ("result", "error") if key in answer}
    if method in TRAVERSAL_METHODS:
        try:
            append_traversal(path.with_suffix(".traversals.md"), method, params, response)
        except OSError as error:
            print(json.dumps(response, ensure_ascii=False))
            print(f"could not save traversal context: {error}", file=sys.stderr)
            return 1
    print(json.dumps(response, indent=2, ensure_ascii=False))
    return 1 if "error" in response else 0


if __name__ == "__main__":
    raise SystemExit(main())
