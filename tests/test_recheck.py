"""The first in, first out recheck backlog."""

from __future__ import annotations

from bagsort.model.enums import BagState
from bagsort.store.store import Store
from tests.support import check_in


def test_queue_processes_in_arrival_order(plant, flight):
    bags = check_in(plant, flight.id, 3)
    for bag in bags:
        plant.recheck.enqueue(bag)
    assert [bag.id for bag in plant.recheck.items()] == [bag.id for bag in bags]
    first = plant.recheck.dequeue()
    assert first.id == bags[0].id
    assert first.state is BagState.RECHECKED
    assert plant.recheck.length() == 2


def test_peek_does_not_remove(plant, flight):
    bags = check_in(plant, flight.id, 2)
    plant.recheck.enqueue(bags[0])
    assert plant.recheck.peek().id == bags[0].id
    assert plant.recheck.length() == 1


def test_empty_queue_returns_none(plant):
    assert plant.recheck.peek() is None
    assert plant.recheck.dequeue() is None
    assert plant.recheck.items() == []


def test_enqueue_is_idempotent(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.recheck.enqueue(bag)
    plant.recheck.enqueue(plant.bag(bag.id))
    assert plant.recheck.length() == 1


def test_clear_drops_the_backlog(plant, flight):
    bags = check_in(plant, flight.id, 2)
    for bag in bags:
        plant.recheck.enqueue(bag)
    assert plant.recheck.clear() == 2
    assert plant.recheck.length() == 0


def test_backlog_survives_a_restart(plant, flight):
    bags = check_in(plant, flight.id, 2)
    for bag in bags:
        plant.recheck.enqueue(bag)
    path = plant.store.persist()
    assert path
    reopened = Store.open(plant.store.path)
    assert reopened.state().recheck_queue == [bag.id for bag in bags]


def test_deadline_reads_the_flight_schedule(plant, flight):
    plant.book.set_cutoff(flight.id, "2024-01-01T12:00:00Z")
    assert plant.recheck.deadline(flight.id) == "2024-01-01T12:00:00Z"
