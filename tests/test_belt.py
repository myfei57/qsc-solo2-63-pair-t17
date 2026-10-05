"""Carousel batch switching and transfer commands."""

from __future__ import annotations

import pytest

from bagsort.errors import ValidationError
from tests.support import check_in


def test_set_and_describe(plant):
    plant.belt.set("T1-CRCR1", 2)
    assert plant.belt.describe() == {"carousel": "T1-CRCR1", "batch": 2, "on_carousel": 0}


def test_switch_clears_the_current_batch_before_announcing_the_next(plant, flight):
    plant.belt.set("T1-CRCR1", 1)
    bag = check_in(plant, flight.id, 1)[0]
    plant.belt.place(bag)
    cleared = plant.belt.switch("T1-CRCR2", 2)
    assert cleared == 1
    assert plant.belt.describe()["carousel"] == "T1-CRCR2"
    assert plant.belt.describe()["batch"] == 2
    loads = plant.belt.loads()
    assert [(record.carousel, record.batch) for record in loads] == [("T1-CRCR1", 1)]


def test_switch_retires_the_previous_batch_transfer_commands(plant, flight):
    plant.belt.set("T1-CRCR1", 1)
    plant.belt.append_transfer(flight.id, "T1-CRCR1", 1)
    plant.belt.switch("T1-CRCR2", 2)
    assert plant.belt.transfers() == []


def test_replay_filters_to_the_running_batch(plant, flight):
    plant.belt.set("T1-CRCR1", 1)
    plant.belt.append_transfer(flight.id, "T1-CRCR1", 1)
    plant.belt.append_transfer(flight.id, "T1-CRCR1", 2)
    assert [command.batch for command in plant.belt.replay_transfers()] == [1]


def test_rotate_retires_older_batches(plant, flight):
    assert plant.belt.rotate() == 0
    plant.belt.set("T1-CRCR1", 3)
    plant.belt.append_transfer(flight.id, "T1-CRCR1", 2)
    plant.belt.append_transfer(flight.id, "T1-CRCR1", 3)
    assert plant.belt.rotate() == 1
    assert [command.batch for command in plant.belt.transfers()] == [3]


def test_place_batch_places_every_bag(plant, flight):
    bags = check_in(plant, flight.id, 3)
    assert plant.belt.place_batch(bags) == 3
    assert len(plant.belt.on_carousel()) == 3


def test_append_transfer_validates_the_payload(plant, flight):
    with pytest.raises(ValidationError):
        plant.belt.append_transfer(flight.id, "   ", 1)


def test_switch_rejects_a_negative_batch(plant):
    with pytest.raises(Exception):
        plant.belt.switch("T1-CRCR1", -1)
