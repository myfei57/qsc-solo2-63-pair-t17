"""Barcode reading and the two phase commit that makes a reading authoritative.

A read is a proposal: it carries the sequence it *would* take. Nothing else in
the plant may act on it. Only :meth:`TagReader.commit` allocates the sequence,
stores the bag and makes the reading visible to dispatch.
"""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.model.entities import Bag, Reading, Sequence
from bagsort.model.enums import BagState
from bagsort.model.validate import validate_reading
from bagsort.ns.namespace import Namespace
from bagsort.sequence.allocator import allocate
from bagsort.store.store import Store


class TagReader:
    """Reads barcodes from the induction belt and commits them to the log."""

    def __init__(self, store: Store, namespace: Namespace, clock: Clock) -> None:
        self._store = store
        self._ns = namespace
        self._clock = clock

    @property
    def namespace(self) -> Namespace:
        return self._ns

    def sequence(self) -> Sequence:
        return self._store.state().sequence

    def read(self, barcode: str) -> Reading:
        """Propose a reading without touching the log."""

        text = (barcode or "").strip()
        current = self._store.state().sequence
        allocation = allocate(current)
        return Reading(
            barcode=text,
            bag_id=self._ns.bag_id(text),
            sequence=allocation.value,
            epoch=allocation.sequence.epoch,
            committed=False,
        )

    def read_batch(self, barcodes: list[str]) -> list[Reading]:
        return [self.read(barcode) for barcode in barcodes]

    def commit(self, reading: Reading) -> Reading:
        """Allocate the sequence and persist the bag, returning the committed reading."""

        validate_reading(reading)
        state = self._store.state()
        allocation = allocate(state.sequence)
        bag = Bag(
            id=reading.bag_id,
            barcode=reading.barcode,
            sequence=allocation.value,
            epoch=allocation.sequence.epoch,
            state=BagState.CHECKED_IN,
        )
        with self._store.session() as session:
            session.state.sequence = allocation.sequence
            session.state.bags[bag.id] = bag
            at = self._clock.now_iso()
            session.record("sequence.put", allocation.sequence.as_dict(), at)
            session.record("bag.put", {"bag": bag.as_dict()}, at)
            session.record(
                "counter.add",
                {"name": "tag.committed", "delta": 1},
                at,
            )
        return Reading(
            barcode=reading.barcode,
            bag_id=reading.bag_id,
            sequence=allocation.value,
            epoch=allocation.sequence.epoch,
            committed=True,
        )

    def commit_batch(self, readings: list[Reading]) -> list[Reading]:
        committed: list[Reading] = []
        for reading in readings:
            committed.append(self.commit(reading))
        return committed
