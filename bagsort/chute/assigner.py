"""Chute assignment with a generation counter.

Re-assigning a flight to a different chute bumps the generation. A caller that
captured the old generation is refused, which is how a stale in-memory routing
cache is prevented from sending bags to a chute that has already been closed.
"""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.errors import StaleError, ValidationError
from bagsort.model.entities import ChuteAssignment
from bagsort.model.errors import unknown_flight
from bagsort.store.store import Store


class ChuteAssigner:
    """Assigns each flight's bags to a chute, versioned by generation."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def assign(self, flight_id: str, chute_id: str) -> ChuteAssignment:
        if flight_id not in self._store.state().flights:
            raise unknown_flight(flight_id)
        identifier = (chute_id or "").strip()
        if not identifier:
            raise ValidationError("chute id must not be empty")
        previous = self._store.state().assignments.get(flight_id)
        generation = (previous.generation + 1) if previous else 1
        assignment = ChuteAssignment(
            flight_id=flight_id,
            chute_id=identifier,
            generation=generation,
            updated_at=self._clock.now_iso(),
        )
        with self._store.session() as session:
            session.state.assignments[flight_id] = assignment
            session.record("chute.assign", assignment.as_dict(), self._clock.now_iso())
        return assignment

    def reassign(self, flight_id: str, chute_id: str) -> ChuteAssignment:
        return self.assign(flight_id, chute_id)

    def current(self, flight_id: str) -> ChuteAssignment | None:
        return self._store.state().assignments.get(flight_id)

    def require(self, flight_id: str) -> ChuteAssignment:
        assignment = self.current(flight_id)
        if assignment is None:
            raise ValidationError(f"flight {flight_id!r} has no chute assignment")
        return assignment

    def ensure_current(self, flight_id: str, generation: int) -> ChuteAssignment:
        assignment = self.require(flight_id)
        if assignment.generation != generation:
            raise StaleError(
                f"chute assignment generation {generation} for {flight_id!r} is stale; "
                f"current is {assignment.generation}"
            )
        return assignment

    def by_chute(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for flight_id, assignment in self._store.state().assignments.items():
            grouped.setdefault(assignment.chute_id, []).append(flight_id)
        return {chute: sorted(flights) for chute, flights in sorted(grouped.items())}

    def count(self) -> int:
        return len(self._store.state().assignments)
