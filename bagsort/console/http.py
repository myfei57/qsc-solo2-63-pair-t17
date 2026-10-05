"""Minimal WSGI toolkit: requests, responses, an exact/parameter router and JSON helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable
from urllib.parse import parse_qs

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from .server import Server

STATUS_TEXT = {
    200: "OK",
    201: "Created",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    500: "Internal Server Error",
}


class RequestError(Exception):
    """Raised by a handler to finish the request with a specific status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Response:
    """A rendered HTTP response."""

    status: int
    body: bytes
    content_type: str

    def wsgi(self) -> tuple[str, list[tuple[str, str]]]:
        reason = STATUS_TEXT.get(self.status, "Unknown")
        headers = [
            ("Content-Type", self.content_type),
            ("Content-Length", str(len(self.body))),
        ]
        return f"{self.status} {reason}", headers


def json_response(payload: object, status: int = 200) -> Response:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return Response(status=status, body=body, content_type="application/json; charset=utf-8")


def text_response(text: str, status: int = 200) -> Response:
    return Response(
        status=status, body=text.encode("utf-8"), content_type="text/plain; charset=utf-8"
    )


def csv_response(text: str, status: int = 200) -> Response:
    return Response(status=status, body=text.encode("utf-8"), content_type="text/csv; charset=utf-8")


def error_response(status: int, message: str) -> Response:
    return json_response({"error": message}, status=status)


def _to_int(name: str, value: object) -> int:
    if isinstance(value, bool):
        raise RequestError(400, f"field {name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise RequestError(400, f"field {name} must be an integer") from exc
    raise RequestError(400, f"field {name} must be an integer")


@dataclass(frozen=True)
class Request:
    """A parsed inbound request."""

    method: str
    path: str
    query: dict[str, list[str]]
    payload: dict[str, object] = field(default_factory=dict)
    items: tuple[object, ...] = ()
    params: dict[str, str] = field(default_factory=dict)

    def str_field(self, name: str, default: str = "") -> str:
        value = self.payload.get(name, default)
        if value is None:
            return default
        return value if isinstance(value, str) else str(value)

    def int_field(self, name: str, default: int = 0) -> int:
        return _to_int(name, self.payload.get(name, default))

    def bool_field(self, name: str, default: bool = False) -> bool:
        value = self.payload.get(name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, (int, float)):
            return value != 0
        raise RequestError(400, f"field {name} must be a boolean")

    def required(self, name: str) -> str:
        value = self.str_field(name)
        if not value.strip():
            raise RequestError(400, f"field {name} must not be empty")
        return value

    def query_str(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        if not values:
            return default
        return values[0]

    def query_int(self, name: str, default: int = 0) -> int:
        return _to_int(name, self.query_str(name, str(default)))

    def param(self, name: str) -> str:
        return self.params.get(name, "")

    def list_payload(self) -> list[object]:
        return list(self.items)


Handler = Callable[["Server", Request], Response]


class Router:
    """Method plus pattern router with ``{name}`` path parameters."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, tuple[str, ...], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        segments = tuple(part for part in pattern.strip("/").split("/") if part)
        self._routes.append((method.upper(), segments, handler))

    def match(self, method: str, path: str) -> tuple[Handler | None, dict[str, str], bool]:
        """Return the handler, captured parameters and whether the path exists at all."""

        wanted = [part for part in path.strip("/").split("/") if part]
        path_exists = False
        for route_method, segments, handler in self._routes:
            if len(segments) != len(wanted):
                continue
            params: dict[str, str] = {}
            matched = True
            for segment, actual in zip(segments, wanted):
                if segment.startswith("{") and segment.endswith("}"):
                    params[segment[1:-1]] = actual
                elif segment != actual:
                    matched = False
                    break
            if not matched:
                continue
            path_exists = True
            if route_method == method.upper():
                return handler, params, True
        return None, {}, path_exists

def build_request(environ: dict[str, object], params: dict[str, str]) -> Request:
    """Turn a WSGI environ into a parsed :class:`Request`."""

    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    path = str(environ.get("PATH_INFO", "/") or "/")
    query = parse_qs(str(environ.get("QUERY_STRING", "")))
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = 0
    stream = environ.get("wsgi.input")
    raw = stream.read(length) if length and hasattr(stream, "read") else b""
    payload: dict[str, object] = {}
    items: tuple[object, ...] = ()
    if raw:
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise RequestError(400, f"invalid JSON body: {exc}") from exc
        if isinstance(decoded, dict):
            payload = decoded
        elif isinstance(decoded, list):
            items = tuple(decoded)
        else:
            raise RequestError(400, "JSON body must be an object or an array")
    return Request(
        method=method,
        path=path,
        query=query,
        payload=payload,
        items=items,
        params=params,
    )
