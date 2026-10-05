"""Induction: bags enter the handling line here.

Membership of the in-transit queue is derived from committed bag state rather
than held in memory, so a restart rebuilds the queue instead of losing it. A
retry is idempotent: if the sorter already has a record for the bag, the retry
returns without writing a second one.
"""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.model.entities import Bag, Reading, SortRecord
from bagsort.model.enums import BagState
from bagsort.store.store import Store
from bagsort.sorter.sorter import Sorter


class Injector:
    """Moves committed bags from the desk onto the sorter's input queue."""

    def __init__(self, store: Store, book: object, sorter: Sorter, clock: Clock) -> None:
        self._store = store
        self._book = book
        self._sorter = sorter
        self._clock = clock

    def accept(self, bag: Bag) -> Bag:
        """Take custody of a checked-in bag."""

        updated = bag.evolved(state=BagState.INJECTED)
        with self._store.session() as session:
            session.state.bags[updated.id] = updated
            session.record("bag.put", {"bag": updated.as_dict()}, self._clock.now_iso())
            session.record(
                "counter.add", {"name": "inject.accepted", "delta": 1}, self._clock.now_iso()
            )
        return updated

    def queue(self, flight_id: str) -> list[Bag]:
        """Committed bags waiting to be sorted, in sequence order."""

        bags = [
            bag
            for bag in self._store.state().bags.values()
            if bag.state is BagState.INJECTED and bag.flight_id == flight_id
        ]
        return sorted(bags, key=lambda bag: (bag.epoch, bag.sequence, bag.id))

    def in_transit(self, flight_id: str) -> int:
        return len(self.queue(flight_id))

    def push(self, bag: Bag, chute_id: str) -> SortRecord:
        """Assign the lane and dispatch the bag in one operator action."""

        self._sorter.assign_chute(bag.flight_id, chute_id)
        reading = Reading(
            barcode=bag.barcode,
            bag_id=bag.id,
            sequence=bag.sequence,
            epoch=bag.epoch,
            committed=True,
        )
        return self._sorter.dispatch(bag, reading)

    def retry(self, bag: Bag) -> bool:
        """Re-drive a bag that may already have been sorted; returns True if it sorted."""

        if self._sorter.was_executed(bag.id):
            return False
        reading = Reading(
            barcode=bag.barcode,
            bag_id=bag.id,
            sequence=bag.sequence,
            epoch=bag.epoch,
            committed=True,
        )
        self._sorter.dispatch(bag, reading)
        return True

    def drain_in_transit(self, flight_id: str) -> int:
        """Settle everyone still on the belt when a flight is cut off."""

        waiting = self.queue(flight_id)
        if not waiting:
            return 0
        destination = BagState.LOADED if self._book.is_open(flight_id) else BagState.DIVERTED
        with self._store.session() as session:
            at = self._clock.now_iso()
            for bag in waiting:
                updated = bag.evolved(state=destination)
                session.state.bags[updated.id] = updated
                session.record("bag.put", {"bag": updated.as_dict()}, at)
            session.record(
                "counter.add",
                {"name": "inject.drained", "delta": len(waiting)},
                at,
            )
        return len(waiting)
