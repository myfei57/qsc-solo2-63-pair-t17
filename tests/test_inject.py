"""Induction queue, retry and drain."""

from __future__ import annotations

import pytest

from bagsort.model.enums import BagState
from bagsort.errors import ConflictError
from tests.support import check_in


def test_queue_is_sequence_ordered(plant, flight):
    bags = check_in(plant, flight.id, 4)
    queue = plant.injector.queue(flight.id)
    assert [bag.id for bag in queue] == [bag.id for bag in bags]
    assert plant.injector.in_transit(flight.id) == 4


def test_push_assigns_the_chute_and_sorts(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    record = plant.injector.push(bag, "T1-CHA")
    assert record.chute_id == "T1-CHA"
    assert plant.store.state().bags[bag.id].state is BagState.SORTED
    assert plant.chutes.require(flight.id).generation == 1


def test_retry_is_idempotent_after_a_sort(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.injector.push(bag, "T1-CHA")
    assert plant.injector.retry(plant.bag(bag.id)) is False
    assert len(plant.sorter.log.records()) == 1


def test_retry_sorts_a_bag_that_never_reached_the_sorter(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.chutes.assign(flight.id, "T1-CHA")
    assert plant.injector.retry(plant.bag(bag.id)) is True
    assert plant.sorter.log.count_for(bag.id) == 1


def test_drain_marks_open_flight_bags_as_loaded(plant, flight):
    check_in(plant, flight.id, 3)
    drained = plant.injector.drain_in_transit(flight.id)
    assert drained == 3
    assert all(bag.state is BagState.LOADED for bag in plant.book.list_bags_for(flight.id))


def test_drain_marks_closed_flight_bags_as_diverted(plant, flight):
    check_in(plant, flight.id, 2)
    plant.book.mark_closed(flight.id)
    plant.injector.drain_in_transit(flight.id)
    assert all(bag.state is BagState.DIVERTED for bag in plant.book.list_bags_for(flight.id))


def test_pushing_twice_is_refused(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.injector.push(bag, "T1-CHA")
    with pytest.raises(ConflictError):
        plant.injector.push(plant.bag(bag.id), "T1-CHA")
