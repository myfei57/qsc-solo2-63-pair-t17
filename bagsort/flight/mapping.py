"""Bag to flight mapping, including schedule driven re-mapping."""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.errors import OrderingError
from bagsort.model.errors import unknown_bag
from bagsort.store.store import Store


class BagMapping:
    """Which flight each committed bag currently belongs to."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def assign(self, bag_id: str, flight_id: str) -> None:
        bag = self._store.state().bags.get(bag_id)
        if bag is None:
            raise unknown_bag(bag_id)
        updated = bag.evolved(flight_id=flight_id)
        at = self._clock.now_iso()
        with self._store.session() as session:
            session.state.mappings[bag_id] = flight_id
            session.state.bags[bag_id] = updated
            session.record(
                "mapping.put",
                {"bag_id": bag_id, "flight_id": flight_id},
                at,
            )
            session.record("bag.put", {"bag": updated.as_dict()}, at)

    def flight_of(self, bag_id: str) -> str:
        flight_id = self._store.state().mappings.get(bag_id)
        if flight_id is None:
            raise unknown_bag(bag_id)
        return flight_id

    def remap(self, bag_id: str, flight_id: str) -> None:
        """Move a bag to the flight the newest schedule names."""

        if self.flight_of(bag_id) == flight_id:
            raise OrderingError(f"bag {bag_id!r} already belongs to {flight_id!r}")
        self.assign(bag_id, flight_id)
