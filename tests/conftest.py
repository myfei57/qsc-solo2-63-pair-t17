"""Fixtures shared by every test module."""

from __future__ import annotations

import pytest

from .support import make_plant, make_server, register_flight


@pytest.fixture()
def plant(tmp_path):
    return make_plant(tmp_path)


@pytest.fixture()
def server(tmp_path):
    return make_server(tmp_path)


@pytest.fixture()
def flight(plant):
    # A flight with no chute yet, so tests control the assignment generations.
    return register_flight(plant, chute="")
