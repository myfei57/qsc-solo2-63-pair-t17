"""WSGI application that dispatches console requests to the wired plant."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from . import handlers
from .http import (
    Handler,
    Request,
    RequestError,
    Response,
    Router,
    build_request,
    error_response,
)
from .middleware import guarded
from .routes import register_routes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bagsort.app import Plant

StartResponse = Callable[[str, list[tuple[str, str]]], object]


class Server:
    """The console: a router, a plant and the request lifecycle around them."""

    def __init__(self, plant: "Plant") -> None:
        self.plant = plant
        self.router = Router()
        register_routes(self.router, handlers)

    # -- in process entry point (tests, demo) ------------------------------

    def call(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | list[object] | None = None,
        query: dict[str, list[str]] | None = None,
    ) -> Response:
        handler, params, exists = self.router.match(method, path)
        if handler is None:
            status = 405 if exists else 404
            return error_response(status, "method not allowed" if exists else "not found")
        fields: dict[str, object] = {}
        items: tuple[object, ...] = ()
        if isinstance(payload, list):
            items = tuple(payload)
        elif payload:
            fields = payload
        request = Request(
            method=method.upper(),
            path=path,
            query=query or {},
            payload=fields,
            items=items,
            params=params,
        )
        return guarded(lambda: handler(self, request))

    # -- WSGI entry point --------------------------------------------------

    def __call__(self, environ: dict[str, object], start_response: StartResponse):
        started = time.perf_counter()
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/") or "/")
        handler, params, exists = self.router.match(method, path)
        if handler is None:
            response = error_response(
                405 if exists else 404, "method not allowed" if exists else "not found"
            )
        else:
            try:
                request = build_request(environ, params)
            except RequestError as exc:
                response = error_response(exc.status, exc.message)
            else:
                response = guarded(lambda: handler(self, request))
        self.plant.metrics.observe(path, response.status, time.perf_counter() - started)
        status, headers = response.wsgi()
        start_response(status, headers)
        return [response.body]
