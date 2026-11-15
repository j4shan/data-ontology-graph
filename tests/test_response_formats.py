"""Table and records formats carry the same content (system design 2.4).

A table is ``{"header": [...], "rows": [[...]]}``; the records format writes the same values as
one object per row. Navigation responses nest a dataset's directed edges in the dataset record,
while the table format lists them as top-level ``edge_groups`` tagged with the ``node_id``.
"""
import pytest

from data_ontology_graph.service.tables import to_records, to_table
from testkit import service_of
from testkit.builders import EMPLOYEE, SEED, TENANT, WAREHOUSE, fanout_service, with_roles
from testkit.rpc import dispatch

ACCOUNT, CUSTOMER, REGION = "sqlite:lending.account", "sqlite:lending.customer", "sqlite:lending.region"
NESTED = ("edge_groups", "columns", "entity_definitions")
LOAN_ACCOUNT = (
    "D1-D8"
)

CASES = {
    "get_edges-aggregated": (fanout_service, "graph.get_edges", {"node_id": SEED, "identity_id": TENANT}),
    "get_edges-detailed": (service_of, "graph.get_edges", {"node_id": ACCOUNT, "detail": "full"}),
    "expand_subgraph": (service_of, "graph.expand_subgraph", {"seed_node_ids": [ACCOUNT], "max_depth": 2}),
    "find_paths": (service_of, "graph.find_paths", {"from_node_id": CUSTOMER, "to_node_id": REGION}),
    "find_connecting_subgraph": (service_of, "graph.find_connecting_subgraph",
                                 {"node_ids": [ACCOUNT, CUSTOMER]}),
    "get_entity_definitions-aggregated": (with_roles, "graph.get_entity_definitions",
                                          {"identity_id": TENANT, "view": "aggregated",
                                           "target_identity_ids": [EMPLOYEE, WAREHOUSE]}),
    "get_entity_definitions-detailed": (with_roles, "graph.get_entity_definitions",
                                        {"identity_id": TENANT, "view": "detailed", "limit": 100,
                                         "target_identity_ids": [EMPLOYEE, WAREHOUSE]}),
    "get_relationship": (service_of, "graph.get_relationship",
                         {"edge_id": LOAN_ACCOUNT, "from_node_id": ACCOUNT}),
}


def _is_table(value) -> bool:
    return isinstance(value, dict) and set(value) == {"header", "rows"}


def _nested(records: dict, key: str) -> list[dict]:
    """A collection the records format nests in each dataset, tagged with the dataset's node_id."""
    return [{"node_id": record["node_id"], **item}
            for record in records["datasets"] for item in record.get(key) or ()]


@pytest.mark.parametrize("case", CASES)
def test_table_and_records_formats_carry_the_same_content(case: str) -> None:
    build, method, params = CASES[case]
    service = build()
    table = dispatch(service, method, params | {"response_format": "table"})["result"]
    records = dispatch(service, method, params | {"response_format": "records"})["result"]

    # Only the collections that records nest in their datasets leave the top level.
    assert set(records) <= set(table) and set(table) - set(records) <= set(NESTED)
    assert any(_is_table(value) for value in table.values()), "the case compares no table"
    for key, value in table.items():
        if key == "datasets" and _is_table(value):
            assert to_records(value) == [
                {k: v for k, v in record.items() if k not in NESTED} for record in records[key]
            ]
        elif key in records:
            assert (to_records(value) if _is_table(value) else value) == records[key], key
        elif value is not None:
            assert (to_records(value) if _is_table(value) else value) == _nested(records, key), key


def test_tables_reject_records_their_header_does_not_cover() -> None:
    with pytest.raises(ValueError, match="does not cover"):
        to_table([{"edge_id": "e", "extra": 1}], ["edge_id"])
    table = to_table([{"a": {"b": 1, "c": [2]}, "d": None}], ["a.b", "a.c", "d"])
    assert table.rows == [[1, [2], None]]
    assert to_records(table) == [{"a": {"b": 1, "c": [2]}, "d": None}]
