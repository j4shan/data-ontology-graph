from __future__ import annotations

from typing import Any, Callable
from threading import Event

from pydantic import BaseModel, ValidationError

from data_ontology_graph.service.contracts import (
    ConnectingSubgraphRequest,
    DatasetRequest,
    HopsRequest,
    IdentityRequest,
    PathsRequest,
    RelationshipRequest,
    SearchRequest,
    SubgraphRequest,
)
from data_ontology_graph.service.read import GraphReadService


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
RESOURCE_NOT_FOUND = -32004


class JsonRpcDispatcher:
    def __init__(self, service: GraphReadService) -> None:
        self.service = service
        self._methods: dict[str, Callable[[dict[str, Any]], Any]] = {
            "graph.snapshot_info": self._snapshot_info,
            "graph.search": self._search,
            "graph.get_identity": self._get_identity,
            "graph.get_dataset": self._get_dataset,
            "graph.get_relationship": self._get_relationship,
            "graph.get_hops": self._get_hops,
            "graph.expand_subgraph": self._expand_subgraph,
            "graph.find_paths": self._find_paths,
            "graph.find_connecting_subgraph": self._find_connecting_subgraph,
        }

    def dispatch(self, message: object, cancel_event: Event | None = None) -> dict[str, Any]:
        if not isinstance(message, dict):
            return error_response(None, INVALID_REQUEST, "Invalid Request")
        if "id" not in message:
            return error_response(None, INVALID_REQUEST, "Request id is required")
        request_id = message.get("id")
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return error_response(request_id, INVALID_REQUEST, "Invalid Request")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return error_response(request_id, INVALID_PARAMS, "Invalid params")

        method = self._methods.get(message["method"])
        if method is None:
            return error_response(request_id, METHOD_NOT_FOUND, "Method not found")

        try:
            if method == self._find_paths:
                result = _json_value(method(params, cancel_event))
            else:
                result = _json_value(method(params))
        except ValidationError as error:
            response = error_response(
                request_id,
                INVALID_PARAMS,
                "Invalid params",
                error.errors(include_url=False, include_context=False),
            )
        except KeyError as error:
            response = error_response(
                request_id,
                RESOURCE_NOT_FOUND,
                str(error).strip("'"),
            )
        except ValueError as error:
            response = error_response(request_id, INVALID_PARAMS, str(error))
        except Exception:
            response = error_response(request_id, INTERNAL_ERROR, "Internal error")
        else:
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}

        return response

    def _snapshot_info(self, params: dict[str, Any]) -> Any:
        _require_empty(params)
        return self.service.snapshot_info()

    def _search(self, params: dict[str, Any]) -> Any:
        return self.service.search(SearchRequest.model_validate(params))

    def _get_identity(self, params: dict[str, Any]) -> Any:
        request = IdentityRequest.model_validate(params)
        return self.service.get_identity(
            request.identity_id, request.entity_universe, request.limit,
        )

    def _get_dataset(self, params: dict[str, Any]) -> Any:
        request = DatasetRequest.model_validate(params)
        return self.service.get_dataset(request.node_id)

    def _get_relationship(self, params: dict[str, Any]) -> Any:
        request = RelationshipRequest.model_validate(params)
        return self.service.get_relationship(request.edge_id, request.from_node_id)

    def _get_hops(self, params: dict[str, Any]) -> Any:
        request = HopsRequest.model_validate(params)
        return self.service.get_hops(request.node_id, request.limit)

    def _expand_subgraph(self, params: dict[str, Any]) -> Any:
        return self.service.expand_subgraph(SubgraphRequest.model_validate(params))

    def _find_paths(self, params: dict[str, Any], cancel_event: Event | None = None) -> Any:
        request = PathsRequest.model_validate(params)
        return self.service.find_paths(
            request.from_node_id,
            request.to_node_id,
            max_hops=request.max_hops,
            limit=request.limit,
            allowed_multiplicities=request.allowed_multiplicities,
            cancel_event=cancel_event,
        )

    def _find_connecting_subgraph(self, params: dict[str, Any]) -> Any:
        return self.service.find_connecting_subgraph(
            ConnectingSubgraphRequest.model_validate(params),
        )


def error_response(
    request_id: object,
    code: int,
    message: str,
    data: object | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _require_empty(params: dict[str, Any]) -> None:
    if params:
        raise ValueError("graph.snapshot_info accepts no parameters")
