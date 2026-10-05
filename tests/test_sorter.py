"""Dispatch, routing, deduplication and freshness."""

from __future__ import annotations

import pytest

from bagsort.errors import ConflictError
from bagsort.model.entities import Reading
from bagsort.model.enums import BagState, Verdict
from tests.support import check_in


def _committed(bag, committed: bool = True) -> Reading:
    return Reading(
        barcode=bag.barcode,
        bag_id=bag.id,
        sequence=bag.sequence,
        epoch=bag.epoch,
        committed=committed,
    )


def test_dispatch_refuses_an_uncommitted_reading(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.chutes.assign(flight.id, "T1-CHA")
    with pytest.raises(ConflictError):
        plant.sorter.dispatch(plant.bag(bag.id), _committed(bag, committed=False))


def test_dispatch_records_and_updates_the_bag(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.chutes.assign(flight.id, "T1-CHA")
    record = plant.sorter.dispatch(plant.bag(bag.id), _committed(bag))
    assert record.chute_id == "T1-CHA"
    assert record.flight_id == flight.id
    assert plant.bag(bag.id).state is BagState.SORTED
    assert plant.bag(bag.id).chute_id == "T1-CHA"


def test_dispatch_refuses_a_duplicate(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.chutes.assign(flight.id, "T1-CHA")
    plant.sorter.dispatch(plant.bag(bag.id), _committed(bag))
    with pytest.raises(ConflictError):
        plant.sorter.dispatch(plant.bag(bag.id), _committed(bag))


def test_route_follows_the_current_assignment(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.chutes.assign(flight.id, "T1-CHA")
    first = plant.sorter.route(bag.id)
    assert (first.chute_id, first.generation) == ("T1-CHA", 1)
    plant.chutes.reassign(flight.id, "T1-CHB")
    second = plant.sorter.route(bag.id)
    assert (second.chute_id, second.generation) == ("T1-CHB", 2)
    assert first != second
    assert "T1-CHB" in repr(second)


def test_divert_sets_the_state_and_counts(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    updated = plant.sorter.divert(plant.bag(bag.id))
    assert updated.state is BagState.DIVERTED
    assert plant.store.state().counters["sorter.diverted"] == 1


def test_verdict_and_high_water(plant):
    assert plant.sorter.is_fresh(0, 5) is True
    assert plant.sorter.verdict(0, 5) is Verdict.FRESH
    assert plant.sorter.high_water() == (0, 5)
    assert plant.sorter.is_fresh(0, 5) is False
    assert plant.sorter.verdict(0, 5) is Verdict.REPLAYED
    assert plant.sorter.high_water() == (0, 5)


def test_by_chute_totals(plant, flight):
    bags = check_in(plant, flight.id, 2)
    plant.chutes.assign(flight.id, "T1-CHA")
    for bag in bags:
        plant.injector.push(plant.bag(bag.id), "T1-CHA")
    assert plant.sorter.log.by_chute() == {"T1-CHA": 2}
    assert plant.sorter.log.by_chute("T1-OTHER") == {}
    assert plant.sorter.log.last_chute(bags[0].id) == "T1-CHA"
