"""Route table integrity and router behaviour."""

from __future__ import annotations

from bagsort.console import handlers
from bagsort.console.http import Router
from bagsort.console.routes import route_table
from bagsort.console.server import Server


def test_route_table_has_no_duplicate_method_and_path():
    keys = [(route.method, route.path) for route in route_table()]
    assert len(keys) == len(set(keys))


def test_every_route_points_at_a_real_handler():
    for route in route_table():
        assert callable(getattr(handlers, route.handler)), route.handler


def test_every_note_is_present():
    assert all(route.note.strip() for route in route_table())
    assert all(route.as_dict()["method"] == route.method for route in route_table())


def test_literal_paths_are_matched_before_parameters(server: Server):
    handler, params, exists = server.router.match("GET", "/api/flights/open")
    assert handler.__name__ == "handle_open_flights"
    assert params == {} and exists is True

    handler, params, _ = server.router.match("GET", "/api/assignments/by-chute")
    assert handler.__name__ == "handle_assignments_by_chute"
    assert params == {}


def test_router_captures_path_parameters():
    router = Router()
    router.add("GET", "/api/flights/{id}/bags", lambda server, request: None)
    handler, params, exists = router.match("GET", "/api/flights/T1-1/bags")
    assert handler is not None and exists is True
    assert params == {"id": "T1-1"}


def test_router_distinguishes_missing_from_wrong_method():
    router = Router()
    router.add("GET", "/api/health", lambda server, request: None)
    assert router.match("GET", "/api/health")[0] is not None
    assert router.match("POST", "/api/health")[2] is True
    assert router.match("GET", "/api/nope")[2] is False


def test_catalog_lists_every_route(server: Server):
    response = server.call("GET", "/api/catalog")
    assert response.status == 200
    rows = __import__("json").loads(response.body)
    assert len(rows) == len(route_table())
