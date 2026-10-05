"""Read-only projection over the committed sort records."""

from __future__ import annotations

from bagsort.model.entities import SortRecord
from bagsort.store.store import Store


class SortLog:
    """Answers the questions dispatch needs before it writes a new record."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def records(self) -> list[SortRecord]:
        return list(self._store.state().sort_records)

    def was_executed(self, bag_id: str) -> bool:
        return self.count_for(bag_id) > 0

    def count_for(self, bag_id: str) -> int:
        return sum(1 for record in self._store.state().sort_records if record.bag_id == bag_id)

    def last_chute(self, bag_id: str) -> str:
        last = ""
        for record in self._store.state().sort_records:
            if record.bag_id == bag_id:
                last = record.chute_id
        return last

    def by_chute(self, flight_id: str | None = None) -> dict[str, int]:
        summary: dict[str, int] = {}
        for record in self._store.state().sort_records:
            if flight_id is not None and record.flight_id != flight_id:
                continue
            summary[record.chute_id] = summary.get(record.chute_id, 0) + 1
        return dict(sorted(summary.items()))
