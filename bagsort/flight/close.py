"""Flight cut-off: the in-transit queue drains before the flight is closed.

The order is the whole point. Closing first would strand bags that were already
on the induction belt, so the closer asks the injector to drain and only then
flags the flight closed.
"""

from __future__ import annotations

from typing import Protocol

from bagsort.model.entities import Flight


class Drainer(Protocol):
    """Anything that can empty a flight's not-yet-sorted queue."""

    def drain_in_transit(self, flight_id: str) -> int: ...


class Closer(Protocol):
    """The part of the flight book the closer needs."""

    def require_open(self, flight_id: str) -> Flight: ...

    def mark_closed(self, flight_id: str) -> Flight: ...


class FlightCloser:
    """Closes flights in the only order that does not lose baggage."""

    def __init__(self, book: Closer) -> None:
        self._book = book

    def close(self, flight_id: str, drainer: Drainer) -> Flight:
        self._book.require_open(flight_id)
        drainer.drain_in_transit(flight_id)
        return self._book.mark_closed(flight_id)
