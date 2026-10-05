"""Shared builders for the test suite."""

from __future__ import annotations

from pathlib import Path

from bagsort.app import Plant
from bagsort.clock import Clock
from bagsort.console.server import Server
from bagsort.store.store import Store


def make_plant(tmp_path: Path, terminal: str = "T1", name: str = "state.json") -> Plant:
    """A wired plant backed by a fresh file in ``tmp_path``."""

    store = Store(str(tmp_path / name))
    return Plant.build(store, terminal=terminal, clock=Clock())


def make_server(tmp_path: Path, terminal: str = "T1") -> Server:
    return Server(make_plant(tmp_path, terminal=terminal))


def register_flight(plant: Plant, code: str = "CA1234", carousel: str = "CR1", chute: str = ""):
    return plant.register_flight(code, carousel, chute)


def check_in(plant: Plant, flight_id: str, count: int, prefix: str = "BAG") -> list:
    return [plant.check_in(f"{prefix}{index:04d}", flight_id) for index in range(count)]
