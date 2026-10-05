"""Model level error constructors.

They wrap :mod:`bagsort.errors` so callers can raise with a single import and
the API layer can map them to HTTP status codes by class.
"""

from __future__ import annotations

from bagsort.errors import NotFoundError, ValidationError


def empty_field(name: str) -> ValidationError:
    return ValidationError(f"field {name} must not be empty")


def unknown_flight(flight_id: str) -> NotFoundError:
    return NotFoundError(f"flight {flight_id!r} is not registered")


def unknown_bag(bag_id: str) -> NotFoundError:
    return NotFoundError(f"bag {bag_id!r} is not registered")
