"""Check-in desk behaviour."""

from __future__ import annotations

import pytest

from bagsort.errors import OrderingError, QuotaError
from bagsort.checkin.entries import Entry
from bagsort.model.enums import BagState
from tests.support import register_flight


def test_check_in_commits_and_injects(plant, flight):
    bag = plant.desk.check_in("7001", flight.id)
    assert bag.state is BagState.INJECTED
    assert bag.flight_id == flight.id
    assert plant.store.state().bags[bag.id].sequence == 1
    assert plant.injector.in_transit(flight.id) == 1


def test_check_in_rejects_a_closed_flight(plant, flight):
    plant.book.cutoff(flight.id)
    plant.book.mark_closed(flight.id)
    with pytest.raises(OrderingError):
        plant.desk.check_in("7002", flight.id)


def test_check_in_batch_accepts_several_entries(plant, flight):
    entries = [Entry(barcode="8001", flight_id=flight.id), Entry(barcode="8002", flight_id=flight.id)]
    bags = plant.desk.check_in_batch(entries)
    assert [bag.barcode for bag in bags] == ["8001", "8002"]
    assert [bag.sequence for bag in bags] == [1, 2]


def test_check_in_honours_the_allowance(plant, flight):
    plant.quota.set_limit(flight.id, 1)
    plant.desk.check_in("9001", flight.id)
    assert plant.quota.limit(flight.id) == 0
    assert plant.quota.allowed(flight.id) is False
    with pytest.raises(QuotaError):
        plant.desk.check_in("9002", flight.id)


def test_cancel_diverts_the_bag(plant, flight):
    bag = plant.desk.check_in("9100", flight.id)
    cancelled = plant.desk.cancel(bag.id)
    assert cancelled.state is BagState.DIVERTED


def test_second_flight_shares_the_bag_namespace(plant, flight):
    other = register_flight(plant, code="QQ9")
    bag = plant.desk.check_in("9200", other.id)
    assert bag.flight_id == other.id
    assert plant.mapping.flight_of(bag.id) == other.id
