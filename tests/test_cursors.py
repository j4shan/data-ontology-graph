"""Paging cursors of the three paged methods (system design 2.3.3, 2.3.5, 2.3.12).

One set of helpers in ``service/read.py`` makes and checks every cursor: a cursor binds the
snapshot content, the API version, the method, and every request parameter except ``cursor``
and ``view``. These tests run each case against every paged method through the dispatcher.
"""
import base64
import json
from dataclasses import dataclass, field
from typing import Callable

import pytest

from data_ontology_graph.rpc.protocol import INVALID_PARAMS
from data_ontology_graph.service.read import GraphReadService
from testkit import STATED, service_of, snapshot_of
from testkit.builders import EMPLOYEE, SEED, TENANT, WAREHOUSE, fanout_service, with_roles
from testkit.rpc import dispatch


def _stated_without_last_relationship() -> GraphReadService:
    snapshot = snapshot_of(STATED)
    payload = snapshot.model_dump()
    payload["entity_relationships"] = payload["entity_relationships"][:-1]
    return GraphReadService(type(snapshot).model_validate(payload))


@dataclass
class Paged:
    method: str
    service: Callable[[], GraphReadService]
    """A catalog whose first page of ``first`` has a continuation."""
    other_snapshot: Callable[[], GraphReadService]
    """A catalog with different content, which must reject the continuation."""
    first: dict
    """The first-page request; continuations repeat it with ``cursor`` and without ``view``."""
    bound: list[dict]
    """Parameter changes that each make the continuation a different request."""
    reordered: dict | None = None
    """The same filters in another order with duplicates, which a continuation accepts."""
    other_method: tuple[str, dict] | None = None
    """A request of another method or subject that must reject the continuation."""
    aggregated: bool = field(default=True)
    """Whether the method has an aggregated view, which cannot carry a cursor."""

    def continuation(self) -> dict:
        return {key: value for key, value in self.first.items() if key != "view"}


PAGED = [
    Paged(
        method="graph.get_edges",
        service=lambda: fanout_service(30),
        other_snapshot=lambda: fanout_service(31),
        first={"node_id": SEED, "identity_id": TENANT, "view": "detailed", "limit": 1,
               "target_identity_ids": [WAREHOUSE, EMPLOYEE]},
        bound=[{"limit": 3}, {"target_identity_ids": [EMPLOYEE]}, {"detail": "full"},
               {"response_format": "records"}, {"fan_out_threshold": 1},
               {"fields": {"dataset": ["columns"]}}],
        reordered={"target_identity_ids": [EMPLOYEE, WAREHOUSE, EMPLOYEE]},
        other_method=("graph.get_entity_definitions", {"identity_id": TENANT, "limit": 1}),
    ),
    Paged(
        method="graph.get_entity_definitions",
        service=lambda: with_roles(30),
        other_snapshot=lambda: with_roles(31),
        first={"identity_id": TENANT, "view": "detailed", "limit": 1,
               "target_identity_ids": [EMPLOYEE, WAREHOUSE],
               "entity_universe": ["partial", "complete"]},
        bound=[{"limit": 2}, {"target_identity_ids": [EMPLOYEE]},
               {"entity_universe": ["complete"]}, {"dataset_threshold": 1},
               {"response_format": "records"}, {"identity_id": EMPLOYEE}],
        reordered={"target_identity_ids": [WAREHOUSE, EMPLOYEE, EMPLOYEE],
                   "entity_universe": ["complete", "partial", "complete"]},
        other_method=("graph.get_edges", {"node_id": SEED, "limit": 1}),
    ),
    Paged(
        method="graph.get_entity_relationships",
        service=lambda: service_of(STATED),
        other_snapshot=_stated_without_last_relationship,
        first={"identity_id": "hashed_id_identity", "limit": 1},
        bound=[{"limit": 2}, {"identity_id": "impression_identity"}],
        aggregated=False,
    ),
]
IDS = [paged.method.removeprefix("graph.") for paged in PAGED]


def _first_cursor(paged: Paged, service: GraphReadService) -> str:
    result = dispatch(service, paged.method, paged.first)["result"]
    assert result["next_cursor"], paged.method
    return result["next_cursor"]


def _error(service: GraphReadService, method: str, params: dict) -> str:
    response = dispatch(service, method, params)
    assert response.get("error", {}).get("code") == INVALID_PARAMS, response
    # Contract validation reports its reason in `data`; service checks in `message`.
    return response["error"]["message"] + json.dumps(response["error"].get("data"))


@pytest.mark.parametrize("paged", PAGED, ids=IDS)
@pytest.mark.parametrize("cursor", ["!bad", "bm90LWpzb24", "e30", "W10", "bnVsbA", "x" * 4097])
def test_malformed_cursors_are_invalid_params(paged: Paged, cursor: str) -> None:
    _error(paged.service(), paged.method, paged.continuation() | {"cursor": cursor})


@pytest.mark.parametrize("paged", PAGED, ids=IDS)
@pytest.mark.parametrize("offset", [True, -1, 0, "2", 100])
def test_edited_offsets_are_rejected(paged: Paged, offset) -> None:
    service = paged.service()
    cursor = _first_cursor(paged, service)
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    edited = base64.urlsafe_b64encode(json.dumps(payload | {"offset": offset}).encode()).decode()
    assert any(word in _error(service, paged.method, paged.continuation() | {"cursor": edited})
               for word in ("offset", "outside"))


@pytest.mark.parametrize("paged", PAGED, ids=IDS)
def test_a_cursor_continues_only_its_own_request(paged: Paged) -> None:
    service = paged.service()
    cursor = _first_cursor(paged, service)
    continued = dispatch(service, paged.method, paged.continuation() | {"cursor": cursor})
    assert continued["result"]["next_cursor"] != cursor
    for change in paged.bound:
        message = _error(service, paged.method, paged.continuation() | change | {"cursor": cursor})
        assert "does not match" in message, change
    if paged.other_method:
        method, params = paged.other_method
        assert "does not match" in _error(service, method, params | {"cursor": cursor})
    if paged.aggregated:
        aggregated = paged.continuation() | {"cursor": cursor, "view": "aggregated"}
        assert "cursor requires" in _error(service, paged.method, aggregated)


@pytest.mark.parametrize("paged", [p for p in PAGED if p.reordered], ids=[i for p, i in zip(PAGED, IDS) if p.reordered])
def test_reordered_and_repeated_filters_continue_the_same_request(paged: Paged) -> None:
    service = paged.service()
    cursor = _first_cursor(paged, service)
    response = dispatch(service, paged.method, paged.continuation() | paged.reordered | {"cursor": cursor})
    assert "result" in response, response


@pytest.mark.parametrize("paged", PAGED, ids=IDS)
def test_a_cursor_belongs_to_one_snapshot_and_api_version(paged: Paged, monkeypatch) -> None:
    # One service throughout: the stated catalog's snapshot version is its build second, so a
    # second build could change the fingerprint and report a different snapshot instead.
    service = paged.service()
    cursor = _first_cursor(paged, service)
    message = _error(paged.other_snapshot(), paged.method, paged.continuation() | {"cursor": cursor})
    assert "different snapshot" in message

    import data_ontology_graph.service.read as read

    monkeypatch.setattr(read, "API_VERSION", "future")
    assert "does not match" in _error(service, paged.method, paged.continuation() | {"cursor": cursor})
