"""Check-in desk: the entry point of the whole line.

A bag is only committed once the barcode read has been committed, and it is
only accepted while the flight is open and has allowance left. The desk also
keeps the bag's flight mapping in step with the bag record so downstream steps
never have to guess.
"""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.errors import QuotaError
from bagsort.model.entities import Bag
from bagsort.model.enums import BagState
from bagsort.model.errors import unknown_bag
from bagsort.store.store import Store
from bagsort.flight.book import FlightBook
from bagsort.flight.mapping import BagMapping
from bagsort.inject.injector import Injector
from bagsort.ns.topology import Topology
from bagsort.quota.quota import QuotaBook
from bagsort.tag.reader import TagReader
from .entries import Entry


class Desk:
    """Accepts baggage for the flights the terminal is still boarding."""

    def __init__(
        self,
        store: Store,
        reader: TagReader,
        book: FlightBook,
        mapping: BagMapping,
        injector: Injector,
        quota: QuotaBook,
        clock: Clock,
        topology: Topology,
    ) -> None:
        self._store = store
        self._reader = reader
        self._book = book
        self._mapping = mapping
        self._injector = injector
        self._quota = quota
        self._clock = clock
        self._topology = topology
        # The desk refuses to start if the line no longer reads before it injects.
        topology.ensure_before("checkin", "tag")
        topology.ensure_before("tag", "inject")

    def check_in(self, barcode: str, flight_id: str) -> Bag:
        self._book.require_open(flight_id)
        if not self._quota.allowed(flight_id):
            raise QuotaError(f"flight {flight_id!r} has no sorting allowance left")
        committed = self._reader.commit(self._reader.read(barcode))
        self._mapping.assign(committed.bag_id, flight_id)
        if self._quota.is_limited(flight_id):
            self._quota.consume(flight_id)
        bag = self._store.state().bags[committed.bag_id]
        return self._injector.accept(bag)

    def check_in_batch(self, entries: list[Entry]) -> list[Bag]:
        return [self.check_in(entry.barcode, entry.flight_id) for entry in entries]

    def cancel(self, bag_id: str) -> Bag:
        bag = self._store.state().bags.get(bag_id)
        if bag is None:
            raise unknown_bag(bag_id)
        updated = bag.evolved(state=BagState.DIVERTED)
        with self._store.session() as session:
            session.state.bags[updated.id] = updated
            session.record("bag.put", {"bag": updated.as_dict()}, self._clock.now_iso())
            session.record(
                "counter.add", {"name": "checkin.cancelled", "delta": 1}, self._clock.now_iso()
            )
        return updated
