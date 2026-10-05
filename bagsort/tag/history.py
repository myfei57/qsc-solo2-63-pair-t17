"""Projection of committed reads, rebuilt from the journal."""

from __future__ import annotations

from bagsort.model.entities import Bag
from bagsort.store.store import Store


class ReadHistory:
    """Which barcodes have been committed, and how many epoch wraps happened."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def committed_bags(self) -> list[Bag]:
        state = self._store.state()
        return [state.bags[key] for key in sorted(state.bags)]

    def count(self) -> int:
        return len(self._store.state().bags)

    def epochs(self) -> list[int]:
        """Distinct epochs that have produced committed readings."""

        return sorted({bag.epoch for bag in self._store.state().bags.values()})
