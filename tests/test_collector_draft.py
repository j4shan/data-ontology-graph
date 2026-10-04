from pathlib import Path

import yaml

from ddl_collector.config import SourceRef, verify_sources
from ddl_collector.draft import (
    build_draft,
    propose_decisions,
    write_catalog_directory,
)
from ddl_collector.sources import SqliteSourceFamily
from ddl_collector.survey import Decision
from ddl_collector.validate import validate_catalog_directory


def _evidence(critic_root: Path):
    ref = SourceRef(catalog="minibank", critic_root=critic_root)
    return SqliteSourceFamily().collect(ref, verify_sources(ref))


def _answer(decisions: list[Decision], decision_id: str, **update) -> list[Decision]:
    return [
        decision.model_copy(update=update) if decision.decision_id == decision_id else decision
        for decision in decisions
    ]


def _by_id(decisions: list[Decision]) -> dict[str, Decision]:
    return {decision.decision_id: decision for decision in decisions}


def test_every_proposal_starts_open_with_stable_ids(critic_root):
    decisions = propose_decisions(_evidence(critic_root))

    assert sorted(_by_id(decisions)) == [
        "grain.account",
        "grain.account_note",
        "grain.branch",
        "grain.customer",
        "relationship.account.customer_id.customer",
        "relationship.account_note.account_id.account",
        "relationship.customer.branch_id.branch",
    ]
    assert {decision.status for decision in decisions} == {"open"}
    assert propose_decisions(_evidence(critic_root)) == decisions


def test_grain_proposal_comes_from_the_declared_primary_key(critic_root):
    decisions = _by_id(propose_decisions(_evidence(critic_root)))

    assert decisions["grain.branch"].proposal == {
        "columns": ["branch_id"],
        "identity_id": "branch_identity",
        "identity_name": "Branch identity",
        "entity_universe": "unknown",
    }
    assert decisions["grain.account_note"].proposal["columns"] == []
    assert decisions["grain.account_note"].proposal["identity_id"] is None


def test_relationship_claims_are_proposed_from_observed_coverage(critic_root):
    decisions = _by_id(propose_decisions(_evidence(critic_root)))

    customer_to_branch = decisions["relationship.customer.branch_id.branch"].proposal
    assert customer_to_branch["a_to_b"] == {"multiplicity": "many:1", "match_existence": "always"}
    assert customer_to_branch["b_to_a"] == {"multiplicity": "1:many", "match_existence": "optional"}
    account_to_customer = decisions["relationship.account.customer_id.customer"].proposal
    assert account_to_customer["a_to_b"]["match_existence"] == "optional"


def test_relationship_claims_are_unknown_without_profiling(critic_root):
    ref = SourceRef(catalog="minibank", critic_root=critic_root)
    evidence = SqliteSourceFamily(profile=False).collect(ref, verify_sources(ref))
    proposal = _by_id(propose_decisions(evidence))["relationship.customer.branch_id.branch"].proposal

    assert proposal["a_to_b"]["match_existence"] == "unknown"
    assert proposal["b_to_a"] == {"multiplicity": "unknown", "match_existence": "unknown"}


def test_draft_keeps_the_full_column_inventory_and_node_id_form(critic_root):
    evidence = _evidence(critic_root)
    draft = build_draft(evidence, propose_decisions(evidence))

    nodes = {node["node_id"]: node for node in draft.nodes}
    assert sorted(nodes) == [
        "sqlite:minibank.account",
        "sqlite:minibank.account_note",
        "sqlite:minibank.branch",
        "sqlite:minibank.customer",
    ]
    for table in evidence.tables:
        node = nodes[f"sqlite:minibank.{table.name}"]
        assert [column["name"] for column in node["columns"]] == table.column_names()
        assert node["descriptor"]["qualified_name"] == f"minibank.main.{table.name}"
    assert nodes["sqlite:minibank.account_note"]["grain"] == "unknown"


def test_edges_come_only_from_declared_foreign_keys(critic_root):
    evidence = _evidence(critic_root)
    draft = build_draft(evidence, propose_decisions(evidence))

    pairs = sorted(
        (edge["endpoint_a"]["node_id"], edge["endpoint_b"]["node_id"]) for edge in draft.edges
    )
    assert pairs == [
        ("sqlite:minibank.account", "sqlite:minibank.customer"),
        ("sqlite:minibank.account_note", "sqlite:minibank.account"),
        ("sqlite:minibank.customer", "sqlite:minibank.branch"),
    ]
    assert draft.findings == []


def test_draft_directory_validates_through_the_builder(critic_root, tmp_path):
    evidence = _evidence(critic_root)
    decisions = propose_decisions(evidence)
    write_catalog_directory(tmp_path / "catalog", build_draft(evidence, decisions))

    report = validate_catalog_directory(tmp_path / "catalog" / "yaml", decisions)

    assert report.valid, report.findings
    assert (report.node_count, report.edge_count, report.identity_count) == (4, 3, 3)
    assert len(report.unresolved) == 7
    manifest = yaml.safe_load((tmp_path / "catalog" / "directory-manifest.yaml").read_text())
    assert manifest["schema_version"] == "3"
    assert manifest["nodes"] == [
        "nodes-account.yaml",
        "nodes-account_note.yaml",
        "nodes-branch.yaml",
        "nodes-customer.yaml",
    ]


def test_excluded_relationship_drops_the_edge_and_its_definition(critic_root):
    evidence = _evidence(critic_root)
    decisions = _answer(
        propose_decisions(evidence),
        "relationship.customer.branch_id.branch",
        status="answered",
        value={"include": False},
    )
    draft = build_draft(evidence, decisions)

    customer = next(node for node in draft.nodes if node["node_id"] == "sqlite:minibank.customer")
    assert [d["identity_id"] for d in customer["entity_definitions"]] == ["customer_identity"]
    assert len(draft.edges) == 2


def test_unknown_parent_grain_turns_its_relationship_into_a_finding(critic_root):
    evidence = _evidence(critic_root)
    decisions = _answer(propose_decisions(evidence), "grain.branch", status="unknown")
    draft = build_draft(evidence, decisions)

    branch = next(node for node in draft.nodes if node["node_id"] == "sqlite:minibank.branch")
    assert branch["grain"] == "unknown"
    assert [(f.decision_id, f.rule) for f in draft.findings] == [
        ("relationship.customer.branch_id.branch", "unregistered_target_identity")
    ]


def test_owner_overrides_rename_identities_and_set_claims(critic_root):
    evidence = _evidence(critic_root)
    decisions = _answer(
        propose_decisions(evidence),
        "grain.branch",
        status="answered",
        value={"identity_id": "site_identity", "identity_name": "Site", "entity_universe": "complete"},
    )
    draft = build_draft(evidence, decisions)

    assert draft.logical_identities["site_identity"] == {"name": "Site", "description": ""}
    branch = next(node for node in draft.nodes if node["node_id"] == "sqlite:minibank.branch")
    assert branch["entity_definitions"][0]["entity_universe"] == "complete"
    customer_edge = next(
        edge for edge in draft.edges if edge["endpoint_b"]["node_id"] == "sqlite:minibank.branch"
    )
    assert customer_edge["endpoint_a"]["identity_id"] == "site_identity"
