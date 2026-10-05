"""Flight schedule revisions and the expiring schedule generation.

A revision bumps the generation. Anything that captured the previous generation
is then refused, so a deadline or recheck plan computed against an old schedule
cannot be applied to the new one.
"""

from __future__ import annotations

from dataclasses import dataclass

from bagsort.clock import Clock
from bagsort.errors import StaleError
from bagsort.model.entities import Flight
from bagsort.model.errors import unknown_flight
from bagsort.store.store import Store


@dataclass(frozen=True)
class Schedule:
    """A flight's cutoff time together with the generation that produced it."""

    flight_id: str
    cutoff_at: str
    generation: int

    def as_dict(self) -> dict[str, object]:
        return {
            "flight_id": self.flight_id,
            "cutoff_at": self.cutoff_at,
            "generation": self.generation,
        }


class ScheduleBoard:
    """Publishes and revises the schedule every downstream plan depends on."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def current(self, flight_id: str) -> Schedule:
        flight = self._flight(flight_id)
        return Schedule(
            flight_id=flight.id,
            cutoff_at=flight.cutoff_at,
            generation=flight.schedule_generation,
        )

    def revise(self, flight_id: str, cutoff_at: str) -> Schedule:
        """Publish a new cutoff and invalidate every older generation."""

        flight = self._flight(flight_id)
        updated = flight.evolved(
            cutoff_at=cutoff_at.strip(),
            schedule_generation=flight.schedule_generation + 1,
        )
        self._put(updated)
        return Schedule(
            flight_id=updated.id,
            cutoff_at=updated.cutoff_at,
            generation=updated.schedule_generation,
        )

    def ensure_current(self, flight_id: str, generation: int) -> Schedule:
        schedule = self.current(flight_id)
        if generation != schedule.generation:
            raise StaleError(
                f"schedule generation {generation} for {flight_id!r} is stale; "
                f"current is {schedule.generation}"
            )
        return schedule

    def _flight(self, flight_id: str) -> Flight:
        flight = self._store.state().flights.get(flight_id)
        if flight is None:
            raise unknown_flight(flight_id)
        return flight

    def _put(self, flight: Flight) -> None:
        with self._store.session() as session:
            session.state.flights[flight.id] = flight
            session.record("flight.put", {"flight": flight.as_dict()}, self._clock.now_iso())
