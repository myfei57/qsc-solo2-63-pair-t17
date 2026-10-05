"""Resolved destination of one bag at one instant."""

from __future__ import annotations


class RouteDetail:
    """Where a bag will go, and which assignment generation decided it."""

    __slots__ = ("bag_id", "flight_id", "chute_id", "generation")

    def __init__(self, bag_id: str, flight_id: str, chute_id: str, generation: int) -> None:
        self.bag_id = bag_id
        self.flight_id = flight_id
        self.chute_id = chute_id
        self.generation = generation

    def as_dict(self) -> dict[str, object]:
        return {
            "bag_id": self.bag_id,
            "flight_id": self.flight_id,
            "chute_id": self.chute_id,
            "generation": self.generation,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RouteDetail):
            return NotImplemented
        return (
            self.bag_id == other.bag_id
            and self.flight_id == other.flight_id
            and self.chute_id == other.chute_id
            and self.generation == other.generation
        )

    def __repr__(self) -> str:
        return (
            f"RouteDetail(bag_id={self.bag_id!r}, flight_id={self.flight_id!r}, "
            f"chute_id={self.chute_id!r}, generation={self.generation})"
        )
