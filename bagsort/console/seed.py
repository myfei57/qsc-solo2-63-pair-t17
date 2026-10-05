"""Deterministic starter data so a fresh console is immediately usable."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bagsort.app import Plant

DEFAULT_CHUTES = (
    ("A", "CR1"),
    ("B", "CR1"),
    ("C", "CR2"),
    ("D", "CR2"),
)

DEFAULT_FLIGHTS = (
    ("CA1234", "CR1"),
    ("MU5678", "CR2"),
)


def seed_defaults(plant: "Plant") -> dict[str, object]:
    """Register the standard lanes and flights when the plant is empty."""

    seeded: dict[str, object] = {"chutes": [], "flights": []}
    if not plant.registry.lanes:
        for code, carousel in DEFAULT_CHUTES:
            lane = plant.registry.register(
                plant.namespace.chute_id(code), plant.namespace.carousel_id(carousel)
            )
            seeded["chutes"].append(lane.chute_id)
    if not plant.book.list():
        for code, carousel in DEFAULT_FLIGHTS:
            flight = plant.register_flight(code, carousel)
            seeded["flights"].append(flight.id)
    return seeded
