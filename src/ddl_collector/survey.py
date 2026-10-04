"""Owner decisions: the fillable Markdown survey and the durable decision log."""

from __future__ import annotations

import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ddl_collector.config import dump_yaml
from data_ontology_graph.model.enums import EntityUniverse, MatchExistence, Multiplicity


DecisionStatus = Literal["open", "answered", "unknown", "waived", "blocking"]
Topic = Literal["grain", "relationship"]
UNRESOLVED: frozenset[str] = frozenset({"open", "blocking"})

_ANSWER_STATUSES = ("answered", "unknown", "waived", "blocking", "open")
_SECTION = re.compile(r"^## (\S+)\s*$", re.MULTILINE)
_ANSWER_BLOCK = re.compile(r"```answer\n(.*?)```", re.DOTALL)


class Decision(BaseModel):
    """One stable owner decision with the agent's proposal and the owner's answer."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    topic: Topic
    affected: str
    required: bool
    question: str
    evidence: list[str] = Field(default_factory=list)
    proposal: dict[str, Any]
    status: DecisionStatus = "open"
    value: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    answered_round: int | None = None

    def resolved(self) -> dict[str, Any]:
        """The proposal with the owner's overrides applied."""
        merged = dict(self.proposal)
        merged.update(self.value)
        return merged


class SurveyError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def check_value(decision: Decision, value: dict[str, Any]) -> list[str]:
    """Return problems with an owner's override values for this decision's topic."""
    problems: list[str] = []
    unknown_keys = sorted(set(value) - set(decision.proposal))
    if unknown_keys:
        problems.append(
            f"{decision.decision_id}: value keys {unknown_keys} are not in the proposal "
            f"({sorted(decision.proposal)})"
        )
    universe = value.get("entity_universe")
    if universe is not None and universe not in {item.value for item in EntityUniverse}:
        problems.append(f"{decision.decision_id}: entity_universe {universe!r} is not allowed")
    if decision.topic == "grain":
        columns = value.get("columns")
        if columns is not None and (
            not isinstance(columns, list) or not all(isinstance(c, str) and c for c in columns)
        ):
            problems.append(f"{decision.decision_id}: columns must be a list of column names")
        for key in ("identity_id", "identity_name"):
            if key in value and value[key] is not None and not (
                isinstance(value[key], str) and value[key].strip()
            ):
                problems.append(f"{decision.decision_id}: {key} must be a non-empty string or null")
    else:
        if "include" in value and not isinstance(value["include"], bool):
            problems.append(f"{decision.decision_id}: include must be true or false")
        for direction in ("a_to_b", "b_to_a"):
            if direction not in value:
                continue
            claim = value[direction]
            if not isinstance(claim, dict) or set(claim) - {"multiplicity", "match_existence"}:
                problems.append(
                    f"{decision.decision_id}: {direction} takes multiplicity and match_existence"
                )
                continue
            if "multiplicity" in claim and claim["multiplicity"] not in {
                item.value for item in Multiplicity
            }:
                problems.append(
                    f"{decision.decision_id}: {direction}.multiplicity {claim['multiplicity']!r} "
                    "is not allowed"
                )
            if "match_existence" in claim and claim["match_existence"] not in {
                item.value for item in MatchExistence
            }:
                problems.append(
                    f"{decision.decision_id}: {direction}.match_existence "
                    f"{claim['match_existence']!r} is not allowed"
                )
    return problems


def render_survey(catalog: str, round_number: int, decisions: list[Decision]) -> str:
    """Render the still-unresolved decisions as a fillable Markdown survey."""
    pending = [decision for decision in decisions if decision.status in UNRESOLVED]
    lines = [
        f"# Preparation survey: {catalog}, round {round_number}",
        "",
        f"{len(pending)} decision(s) need an answer. Edit only the `answer` blocks, then run "
        "`ddl-collector apply`.",
        "",
        "- `status`: `answered`, `unknown`, `waived`, or `blocking`. Leave `open` to defer.",
        "- `value`: overrides of the proposal. `{}` accepts the proposal as written.",
        "- `rationale`: why, or where the answer comes from.",
        "",
        "Grain decisions come first, because relationship decisions depend on the identities "
        "they confirm.",
    ]
    for decision in sorted(pending, key=_survey_order):
        answer = {
            "status": decision.status,
            "value": decision.value,
            "rationale": decision.rationale,
        }
        lines += [
            "",
            f"## {decision.decision_id}",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Affected | `{decision.affected}` |",
            f"| Required | {'yes' if decision.required else 'no'} |",
            f"| Topic | {decision.topic} |",
            "",
            f"**Question.** {decision.question}",
            "",
            "**Evidence.**",
            "",
            *(f"- {item}" for item in decision.evidence or ["none"]),
            "",
            "**Proposal.**",
            "",
            "```yaml",
            dump_yaml(decision.proposal).rstrip(),
            "```",
            "",
            "```answer",
            dump_yaml(answer).rstrip(),
            "```",
        ]
    return "\n".join(lines) + "\n"


def parse_survey(text: str, decisions: list[Decision], round_number: int) -> list[Decision]:
    """Apply a filled survey to the decision list; raise SurveyError on any malformed answer."""
    by_id = {decision.decision_id: decision for decision in decisions}
    problems: list[str] = []
    answers: dict[str, dict[str, Any]] = {}
    parts = _SECTION.split(text)
    for decision_id, body in zip(parts[1::2], parts[2::2]):
        if decision_id not in by_id:
            problems.append(f"{decision_id}: unknown decision ID")
            continue
        blocks = _ANSWER_BLOCK.findall(body)
        if len(blocks) != 1:
            problems.append(f"{decision_id}: expected exactly one answer block")
            continue
        try:
            answer = yaml.safe_load(blocks[0]) or {}
        except yaml.YAMLError as error:
            problems.append(f"{decision_id}: answer is not valid YAML ({str(error).splitlines()[0]})")
            continue
        if not isinstance(answer, dict) or set(answer) - {"status", "value", "rationale"}:
            problems.append(f"{decision_id}: answer takes only status, value, and rationale")
            continue
        status = answer.get("status", "open")
        if status not in _ANSWER_STATUSES:
            problems.append(f"{decision_id}: status {status!r} is not one of {_ANSWER_STATUSES}")
            continue
        value = answer.get("value") or {}
        if not isinstance(value, dict):
            problems.append(f"{decision_id}: value must be a mapping")
            continue
        problems.extend(check_value(by_id[decision_id], value))
        answers[decision_id] = {
            "status": status,
            "value": value,
            "rationale": str(answer.get("rationale") or ""),
        }
    if problems:
        raise SurveyError(problems)

    updated: list[Decision] = []
    for decision in decisions:
        answer = answers.get(decision.decision_id)
        if answer is None:
            updated.append(decision)
            continue
        changed = (
            answer["status"] != decision.status
            or answer["value"] != decision.value
            or answer["rationale"] != decision.rationale
        )
        updated.append(
            decision.model_copy(
                update={
                    **answer,
                    "answered_round": (
                        round_number
                        if changed and answer["status"] not in UNRESOLVED
                        else decision.answered_round
                    ),
                }
            )
        )
    return updated


def render_decision_log(catalog: str, decisions: list[Decision]) -> str:
    """Render the durable decision log stored beside a finalized catalog."""
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.status] = counts.get(decision.status, 0) + 1
    summary = ", ".join(f"{status} {count}" for status, count in sorted(counts.items()))
    lines = [
        f"# Decision log: {catalog}",
        "",
        f"{len(decisions)} decisions ({summary}).",
    ]
    for decision in sorted(decisions, key=_survey_order):
        lines += [
            "",
            f"## {decision.decision_id}",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Status | {decision.status} |",
            f"| Affected | `{decision.affected}` |",
            f"| Required | {'yes' if decision.required else 'no'} |",
            f"| Answered in round | {decision.answered_round or '—'} |",
            "",
            f"**Question.** {decision.question}",
            "",
            "**Evidence.**",
            "",
            *(f"- {item}" for item in decision.evidence or ["none"]),
            "",
            "**Resolved value.**",
            "",
            "```yaml",
            dump_yaml(decision.resolved()).rstrip(),
            "```",
            "",
            f"**{'Waiver' if decision.status == 'waived' else 'Rationale'}.** "
            f"{decision.rationale or '—'}",
        ]
    return "\n".join(lines) + "\n"


def load_decisions(text: str) -> list[Decision]:
    return [Decision.model_validate(item) for item in yaml.safe_load(text) or []]


def dump_decisions(decisions: list[Decision]) -> str:
    return dump_yaml([decision.model_dump(mode="json") for decision in decisions])


def _survey_order(decision: Decision) -> tuple[int, str]:
    return (0 if decision.topic == "grain" else 1, decision.decision_id)
