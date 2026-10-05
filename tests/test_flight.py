"""Flight book: lifecycle, mapping, schedule and cut-off ordering."""

from __future__ import annotations

import pytest

from bagsort.errors import NotFoundError, OrderingError, StaleError, ValidationError
from bagsort.model.entities import Flight
from bagsort.model.enums import FlightState
from tests.support import check_in, register_flight


class RecordingDrainer:
    """A drainer that remembers what the flight state was when it was asked."""

    def __init__(self, plant):
        self._plant = plant
        self.calls: list[tuple[str, str]] = []

    def drain_in_transit(self, flight_id: str) -> int:
        state = self._plant.book.get(flight_id).state
        self.calls.append((flight_id, state.value))
        return 0


def test_register_and_get(plant):
    flight = plant.book.register(Flight(id="T1-ZZ", code="ZZ", carousel="T1-CRCR1"))
    assert plant.book.get("T1-ZZ") == flight
    assert [item.id for item in plant.book.list()] == ["T1-ZZ"]


def test_register_rejects_an_empty_code(plant):
    with pytest.raises(ValidationError):
        plant.book.register(Flight(id="T1-ZZ", code="   "))


def test_find_by_code_is_case_insensitive(plant):
    register_flight(plant, code="MU4321")
    assert plant.book.find_by_code("mu4321").id == "T1-MU4321"
    assert plant.book.find_by_code("nope") is None


def test_state_transitions_and_open_filter(plant, flight):
    assert plant.book.open_flights() == [plant.book.get(flight.id)]
    plant.book.board(flight.id)
    assert plant.book.get(flight.id).state is FlightState.BOARDING
    plant.book.cutoff(flight.id)
    assert plant.book.open_flights() == []
    with pytest.raises(OrderingError):
        plant.book.require_open(flight.id)


def test_set_cutoff_carousel_and_batch(plant, flight):
    assert plant.book.set_cutoff(flight.id, "2024-01-01T10:00:00Z").cutoff_at.endswith("Z")
    plant.book.set_carousel(flight.id, "T1-CRCR2")
    assert plant.book.get(flight.id).carousel == "T1-CRCR2"
    plant.book.set_batch(flight.id, 7)
    assert plant.book.batch(flight.id) == 7
    with pytest.raises(OrderingError):
        plant.book.set_batch(flight.id, -1)


def test_list_bags_for_a_flight(plant, flight):
    check_in(plant, flight.id, 3)
    bags = plant.book.list_bags_for(flight.id)
    assert [bag.barcode for bag in bags] == ["BAG0000", "BAG0001", "BAG0002"]


def test_remove_flight_retires_its_mappings(plant, flight):
    check_in(plant, flight.id, 2)
    plant.book.remove(flight.id)
    with pytest.raises(NotFoundError):
        plant.book.get(flight.id)
    assert plant.store.state().mappings == {}
    assert plant.store.tombstones()[0].kind == "flight.remove"


def test_schedule_revision_bumps_the_generation(plant, flight):
    first = plant.schedule.current(flight.id)
    assert first.generation == 1
    revised = plant.schedule.revise(flight.id, "2024-01-02T00:00:00Z")
    assert revised.generation == 2
    assert plant.schedule.ensure_current(flight.id, 2).cutoff_at == "2024-01-02T00:00:00Z"
    with pytest.raises(StaleError):
        plant.schedule.ensure_current(flight.id, 1)


def test_close_drains_before_marking_closed(plant, flight):
    drainer = RecordingDrainer(plant)
    closed = plant.closer.close(flight.id, drainer)
    assert drainer.calls == [(flight.id, "open")]
    assert closed.state is FlightState.CLOSED
    assert closed.closed_at != ""
