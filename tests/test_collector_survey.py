import re

import pytest

from ddl_collector.survey import (
    Decision,
    SurveyError,
    dump_decisions,
    load_decisions,
    parse_survey,
    render_decision_log,
    render_survey,
)


def _decisions() -> list[Decision]:
    return [
        Decision(
            decision_id="relationship.loan.account_id.account",
            topic="relationship",
            affected="edges[a -> b]",
            required=False,
            question="Same entity?",
            evidence=["S: declared foreign key"],
            proposal={
                "include": True,
                "entity_universe": "unknown",
                "a_to_b": {"multiplicity": "many:1", "match_existence": "always"},
                "b_to_a": {"multiplicity": "1:many", "match_existence": "optional"},
            },
        ),
        Decision(
            decision_id="grain.loan",
            topic="grain",
            affected="nodes[sqlite:demo.loan].grain",
            required=True,
            question="Which columns identify a loan?",
            proposal={
                "columns": ["loan_id"],
                "identity_id": "loan_identity",
                "identity_name": "Loan identity",
                "entity_universe": "unknown",
            },
        ),
    ]


def _fill(survey: str, decision_id: str, answer: str) -> str:
    pattern = re.compile(
        rf"(## {re.escape(decision_id)}\n.*?```answer\n)(.*?)(```)", re.DOTALL
    )
    filled, count = pattern.subn(lambda m: m.group(1) + answer + m.group(3), survey)
    assert count == 1
    return filled


def test_survey_lists_grain_before_relationships_with_all_required_fields():
    survey = render_survey("demo", 1, _decisions())

    assert survey.index("## grain.loan") < survey.index("## relationship.loan.account_id.account")
    for field in ("Affected", "Required", "**Question.**", "**Evidence.**", "**Proposal.**", "```answer"):
        assert field in survey


def test_unchanged_survey_round_trips_without_answers():
    decisions = _decisions()
    parsed = parse_survey(render_survey("demo", 1, decisions), decisions, 1)

    assert parsed == decisions


def test_answers_persist_across_rounds_and_leave_the_survey():
    decisions = _decisions()
    first = _fill(
        render_survey("demo", 1, decisions),
        "grain.loan",
        "status: answered\nvalue: {entity_universe: complete}\nrationale: owner confirmed\n",
    )
    round_one = parse_survey(first, decisions, 1)
    second_survey = render_survey("demo", 2, round_one)
    round_two = parse_survey(second_survey, round_one, 2)

    grain = next(d for d in round_two if d.decision_id == "grain.loan")
    assert (grain.status, grain.answered_round, grain.rationale) == ("answered", 1, "owner confirmed")
    assert grain.resolved()["entity_universe"] == "complete"
    assert "## grain.loan" not in second_survey
    assert "1 decision(s) need an answer" in second_survey


def test_decisions_round_trip_through_their_state_file():
    decisions = _decisions()

    assert load_decisions(dump_decisions(decisions)) == decisions


@pytest.mark.parametrize(
    ("decision_id", "answer", "message"),
    [
        ("grain.loan", "status: maybe\n", "status 'maybe'"),
        ("grain.loan", "status: answered\nvalue: {grain: x}\n", "not in the proposal"),
        ("grain.loan", "status: answered\nvalue: {entity_universe: most}\n", "entity_universe 'most'"),
        ("grain.loan", "status: answered\nvalue: {columns: loan_id}\n", "columns must be a list"),
        (
            "relationship.loan.account_id.account",
            "status: answered\nvalue: {a_to_b: {multiplicity: lots}}\n",
            "a_to_b.multiplicity 'lots'",
        ),
        ("relationship.loan.account_id.account", "status: answered\nvalue: {include: no-way}\n", "include must be"),
        ("grain.loan", "status: answered\nnote: hi\n", "only status, value, and rationale"),
        ("grain.loan", "status: [unclosed\n", "not valid YAML"),
    ],
)
def test_malformed_answers_are_rejected_with_the_decision_id(decision_id, answer, message):
    decisions = _decisions()
    survey = _fill(render_survey("demo", 1, decisions), decision_id, answer)

    with pytest.raises(SurveyError) as error:
        parse_survey(survey, decisions, 1)

    assert any(decision_id in problem and message in problem for problem in error.value.problems)


def test_unknown_decision_sections_are_rejected():
    decisions = _decisions()
    survey = render_survey("demo", 1, decisions) + "\n## grain.ghost\n\n```answer\nstatus: open\n```\n"

    with pytest.raises(SurveyError, match="grain.ghost: unknown decision ID"):
        parse_survey(survey, decisions, 1)


def test_decision_log_records_every_decision_and_labels_waivers():
    decisions = [
        decisions.model_copy(update={"status": "waived", "rationale": "not needed for the pilot"})
        if decisions.topic == "relationship"
        else decisions
        for decisions in _decisions()
    ]
    log = render_decision_log("demo", decisions)

    assert "2 decisions (open 1, waived 1)" in log
    assert "## grain.loan" in log and "## relationship.loan.account_id.account" in log
    assert "**Waiver.** not needed for the pilot" in log
