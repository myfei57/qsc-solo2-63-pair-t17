"""The flight book: registration, lifecycle and batch/carousel attributes."""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.errors import OrderingError
from bagsort.model.entities import Flight
from bagsort.model.enums import FlightState
from bagsort.model.errors import unknown_flight
from bagsort.model.validate import is_open_state, validate_flight
from bagsort.store.store import Store


class FlightBook:
    """Owns the state machine of every flight batch."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def register(self, flight: Flight) -> Flight:
        validate_flight(flight)
        with self._store.session() as session:
            session.state.flights[flight.id] = flight
            session.record("flight.put", {"flight": flight.as_dict()}, self._clock.now_iso())
        return flight

    def get(self, flight_id: str) -> Flight:
        flight = self._store.state().flights.get(flight_id)
        if flight is None:
            raise unknown_flight(flight_id)
        return flight

    def list(self) -> list[Flight]:
        flights = self._store.state().flights
        return [flights[key] for key in sorted(flights)]

    def find_by_code(self, code: str) -> Flight | None:
        wanted = (code or "").strip().upper()
        for flight in self.list():
            if flight.code.upper() == wanted:
                return flight
        return None

    def open_flights(self) -> list[Flight]:
        return [flight for flight in self.list() if is_open_state(flight.state)]

    def is_open(self, flight_id: str) -> bool:
        return is_open_state(self.get(flight_id).state)

    def list_bags_for(self, flight_id: str) -> list:
        bags = self._store.state().bags
        return [
            bags[key]
            for key in sorted(bags)
            if bags[key].flight_id == flight_id
        ]

    def open(self, flight_id: str) -> Flight:
        return self._transition(flight_id, FlightState.OPEN)

    def board(self, flight_id: str) -> Flight:
        return self._transition(flight_id, FlightState.BOARDING)

    def cutoff(self, flight_id: str) -> Flight:
        return self._transition(flight_id, FlightState.CUTOFF)

    def mark_closed(self, flight_id: str) -> Flight:
        flight = self.get(flight_id)
        updated = flight.evolved(state=FlightState.CLOSED, closed_at=self._clock.now_iso())
        self._put(updated)
        return updated

    def require_open(self, flight_id: str) -> Flight:
        flight = self.get(flight_id)
        if not is_open_state(flight.state):
            raise OrderingError(f"flight {flight_id!r} is not accepting baggage")
        return flight

    def set_cutoff(self, flight_id: str, cutoff_at: str) -> Flight:
        flight = self.get(flight_id)
        updated = flight.evolved(cutoff_at=cutoff_at.strip())
        self._put(updated)
        return updated

    def deadline(self, flight_id: str) -> str:
        return self.get(flight_id).cutoff_at

    def set_carousel(self, flight_id: str, carousel: str) -> Flight:
        flight = self.get(flight_id)
        updated = flight.evolved(carousel=carousel.strip())
        self._put(updated)
        return updated

    def set_batch(self, flight_id: str, batch: int) -> Flight:
        if batch < 0:
            raise OrderingError("batch number must not be negative")
        flight = self.get(flight_id)
        updated = flight.evolved(batch=batch)
        self._put(updated)
        return updated

    def batch(self, flight_id: str) -> int:
        return self.get(flight_id).batch

    def remove(self, flight_id: str) -> None:
        """Retire a flight (tombstone); bags mapped to it lose their mapping."""

        self.get(flight_id)
        with self._store.session() as session:
            session.state.flights.pop(flight_id, None)
            session.state.mappings = {
                bag_id: mapped
                for bag_id, mapped in session.state.mappings.items()
                if mapped != flight_id
            }
            session.record("flight.remove", {"flight_id": flight_id}, self._clock.now_iso())

    def _transition(self, flight_id: str, state: FlightState) -> Flight:
        flight = self.get(flight_id)
        updated = flight.evolved(state=state)
        self._put(updated)
        return updated

    def _put(self, flight: Flight) -> None:
        with self._store.session() as session:
            session.state.flights[flight.id] = flight
            session.record("flight.put", {"flight": flight.as_dict()}, self._clock.now_iso())
