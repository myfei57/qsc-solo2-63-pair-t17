"""Chute assignment with an expiring generation."""

from __future__ import annotations

import pytest

from bagsort.errors import NotFoundError, StaleError, ValidationError
from bagsort.chute.history import AssignmentHistory
from tests.support import register_flight


def test_first_assignment_is_generation_one(plant, flight):
    assignment = plant.chutes.assign(flight.id, "T1-CHA")
    assert assignment.generation == 1
    assert plant.chutes.current(flight.id).chute_id == "T1-CHA"


def test_reassignment_bumps_the_generation(plant, flight):
    plant.chutes.assign(flight.id, "T1-CHA")
    moved = plant.chutes.reassign(flight.id, "T1-CHB")
    assert moved.generation == 2
    assert plant.chutes.require(flight.id).chute_id == "T1-CHB"


def test_confirm_rejects_a_stale_generation(plant, flight):
    plant.chutes.assign(flight.id, "T1-CHA")
    plant.chutes.assign(flight.id, "T1-CHB")
    assert plant.chutes.ensure_current(flight.id, 2).chute_id == "T1-CHB"
    with pytest.raises(StaleError):
        plant.chutes.ensure_current(flight.id, 1)


def test_assign_requires_a_known_flight(plant):
    with pytest.raises(NotFoundError):
        plant.chutes.assign("T1-GHOST", "T1-CHA")


def test_assign_rejects_an_empty_chute(plant, flight):
    with pytest.raises(ValidationError):
        plant.chutes.assign(flight.id, "   ")


def test_current_requires_an_assignment(plant, flight):
    with pytest.raises(ValidationError):
        plant.chutes.require(flight.id)


def test_by_chute_groups_flights(plant):
    first = register_flight(plant, code="AA1")
    second = register_flight(plant, code="BB2")
    plant.chutes.assign(first.id, "T1-CHA")
    plant.chutes.assign(second.id, "T1-CHA")
    plant.chutes.assign(second.id, "T1-CHB")
    assert plant.chutes.by_chute() == {"T1-CHA": [first.id], "T1-CHB": [second.id]}
    assert plant.chutes.count() == 2


def test_history_replays_every_assignment(plant, flight):
    plant.chutes.assign(flight.id, "T1-CHA")
    plant.chutes.assign(flight.id, "T1-CHB")
    history = AssignmentHistory(plant.store).for_flight(flight.id)
    assert [item.chute_id for item in history] == ["T1-CHA", "T1-CHB"]
    assert [item.generation for item in history] == [1, 2]
