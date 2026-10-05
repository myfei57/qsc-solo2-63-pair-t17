"""Carousel and batch transfer.

Switching a batch must clear the carousel before the new batch is announced and
must retire the previous batch's transfer commands. Doing either in the other
order is how bags ride across batches and how a stale command re-delivers a bag
to the carousel it already left.
"""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.errors import OrderingError
from bagsort.ids import IdFactory
from bagsort.model.entities import Bag, LoadRecord, TransferCommand
from bagsort.model.enums import BagState
from bagsort.model.validate import validate_transfer
from bagsort.store.store import Store


class Belt:
    """The outbound carousel and the transfer commands that feed it."""

    def __init__(self, store: Store, clock: Clock, ids: IdFactory) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    def carousel(self) -> str:
        return self._store.state().belt_carousel

    def batch(self) -> int:
        return self._store.state().belt_batch

    def describe(self) -> dict[str, object]:
        return {
            "carousel": self.carousel(),
            "batch": self.batch(),
            "on_carousel": len(self._store.state().belt_on_carousel),
        }

    def set(self, carousel: str, batch: int) -> dict[str, object]:
        if batch < 0:
            raise OrderingError("batch number must not be negative")
        with self._store.session() as session:
            session.state.belt_carousel = carousel.strip()
            session.state.belt_batch = batch
            session.record(
                "belt.set",
                {"carousel": carousel.strip(), "batch": batch},
                self._clock.now_iso(),
            )
        return self.describe()

    def place(self, bag: Bag) -> int:
        with self._store.session() as session:
            if bag.id not in session.state.belt_on_carousel:
                session.state.belt_on_carousel.append(bag.id)
            session.record("belt.place", {"bag_id": bag.id}, self._clock.now_iso())
        return len(self._store.state().belt_on_carousel)

    def place_batch(self, bags: list[Bag]) -> int:
        for bag in bags:
            self.place(bag)
        return len(self._store.state().belt_on_carousel)

    def on_carousel(self) -> list[Bag]:
        state = self._store.state()
        return [state.bags[bag_id] for bag_id in state.belt_on_carousel if bag_id in state.bags]

    def loads(self) -> list[LoadRecord]:
        return list(self._store.state().load_records)

    def switch(self, carousel: str, batch: int) -> int:
        """Clear the current batch, then announce the next one."""

        if batch < 0:
            raise OrderingError("batch number must not be negative")
        cleared = self._clear_current()
        self.set(carousel, batch)
        self.discard_stale(batch)
        return cleared

    def rotate(self) -> int:
        """Retire transfer commands older than the running batch."""

        if not self.carousel():
            return 0
        return self.discard_stale(self.batch())

    def append_transfer(self, flight_id: str, carousel: str, batch: int) -> TransferCommand:
        command = TransferCommand(
            id=self._ids.next(),
            flight_id=flight_id.strip(),
            carousel=carousel.strip(),
            batch=batch,
            created_at=self._clock.now_iso(),
        )
        validate_transfer(command)
        with self._store.session() as session:
            session.state.transfer_commands.append(command)
            session.record(
                "transfer.append", {"command": command.as_dict()}, self._clock.now_iso()
            )
        return command

    def transfers(self) -> list[TransferCommand]:
        return list(self._store.state().transfer_commands)

    def replay_transfers(self) -> list[TransferCommand]:
        """Commands that still belong to the batch currently on the carousel."""

        batch = self.batch()
        return [
            command
            for command in self._store.state().transfer_commands
            if command.batch == batch
        ]

    def discard_stale(self, floor: int) -> int:
        """Drop every transfer command older than ``floor``; returns how many went."""

        doomed = [
            command for command in self._store.state().transfer_commands if command.batch < floor
        ]
        if not doomed:
            return 0
        with self._store.session() as session:
            session.state.transfer_commands = [
                command
                for command in session.state.transfer_commands
                if command.batch >= floor
            ]
            session.record(
                "transfer.clear_before", {"batch": floor}, self._clock.now_iso()
            )
        return len(doomed)

    def _clear_current(self) -> int:
        state = self._store.state()
        pending = list(state.belt_on_carousel)
        if not pending:
            return 0
        at = self._clock.now_iso()
        with self._store.session() as session:
            for bag_id in pending:
                bag = session.state.bags.get(bag_id)
                if bag is not None and bag.state is not BagState.LOADED:
                    updated = bag.evolved(state=BagState.LOADED)
                    session.state.bags[bag_id] = updated
                    session.record("bag.put", {"bag": updated.as_dict()}, at)
                record = LoadRecord(
                    bag_id=bag_id,
                    carousel=state.belt_carousel,
                    batch=state.belt_batch,
                    at=at,
                )
                session.state.load_records.append(record)
                session.record("load.append", {"record": record.as_dict()}, at)
            session.state.belt_on_carousel = []
            session.record(
                "belt.clear",
                {"carousel": state.belt_carousel, "batch": state.belt_batch},
                at,
            )
            session.record(
                "counter.add", {"name": "belt.loaded", "delta": len(pending)}, at
            )
        return len(pending)
