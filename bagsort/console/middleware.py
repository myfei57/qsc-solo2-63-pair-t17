"""Error translation and panic recovery for the console."""

from __future__ import annotations

import logging
from typing import Callable

from bagsort.errors import (
    ConflictError,
    NotFoundError,
    OrderingError,
    QuotaError,
    StaleError,
    ValidationError,
)
from .http import RequestError, Response, error_response

LOGGER = logging.getLogger("bagsort.console")


def status_for(exc: Exception) -> int:
    """Map a domain failure onto the status the console should answer with."""

    if isinstance(exc, RequestError):
        return exc.status
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ValidationError):
        return 400
    if isinstance(exc, (ConflictError, OrderingError, StaleError, QuotaError)):
        return 409
    return 500


def guarded(call: Callable[[], Response]) -> Response:
    """Run a handler, converting domain and unexpected failures into responses."""

    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - the console reports every failure
        status = status_for(exc)
        if status >= 500:
            LOGGER.exception("unhandled console failure")
        return error_response(status, str(exc))
