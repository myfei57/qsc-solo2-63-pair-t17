"""Per flight allowance."""

from __future__ import annotations

import pytest

from bagsort.errors import ValidationError
from bagsort.quota.quota import UNLIMITED
from bagsort.store.store import Store


def test_unlimited_by_default(plant, flight):
    assert plant.quota.limit(flight.id) == UNLIMITED
    assert plant.quota.is_limited(flight.id) is False
    assert plant.quota.allowed(flight.id) is True
    assert plant.quota.consume(flight.id, 5) is True


def test_allowance_is_consumed_and_persisted(plant, flight):
    plant.quota.set_limit(flight.id, 3)
    assert plant.quota.is_limited(flight.id) is True
    assert plant.quota.consume(flight.id, 2) is True
    assert plant.quota.available(flight.id) == 1
    plant.store.persist()
    reopened = Store.open(plant.store.path)
    assert reopened.state().quota_limits[flight.id] == 1


def test_consuming_past_the_limit_is_refused(plant, flight):
    plant.quota.set_limit(flight.id, 1)
    assert plant.quota.consume(flight.id, 1) is True
    assert plant.quota.allowed(flight.id) is False
    assert plant.quota.consume(flight.id, 1) is False


def test_release_returns_allowance(plant, flight):
    plant.quota.set_limit(flight.id, 2)
    plant.quota.consume(flight.id, 2)
    assert plant.quota.release(flight.id, 1) == 1
    assert plant.quota.allowed(flight.id) is True
    assert plant.quota.release("T1-UNSET", 1) == UNLIMITED


def test_status_rows_describe_every_allowance(plant, flight):
    plant.quota.set_limit(flight.id, 4)
    rows = plant.quota.status()
    assert rows == [{"flight_id": flight.id, "limit": 4, "unlimited": False, "allowed": True}]
    assert plant.quota.limits() == {flight.id: 4}


def test_invalid_inputs_are_rejected(plant, flight):
    with pytest.raises(ValidationError):
        plant.quota.set_limit(flight.id, -2)
    with pytest.raises(ValidationError):
        plant.quota.consume(flight.id, -1)
    with pytest.raises(ValidationError):
        plant.quota.release(flight.id, -1)
    with pytest.raises(ValidationError):
        plant.quota.set_limit("", 1)
