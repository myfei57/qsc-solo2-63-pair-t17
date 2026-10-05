"""Assignment history rebuilt from the chute commands in the journal."""

from __future__ import annotations

from bagsort.model.entities import ChuteAssignment
from bagsort.store.store import Store


class AssignmentHistory:
    """Every assignment a flight has ever had, in commit order."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def for_flight(self, flight_id: str) -> list[ChuteAssignment]:
        return [
            ChuteAssignment.from_dict(entry.payload)
            for entry in self._store.entries()
            if entry.kind == "chute.assign" and entry.payload.get("flight_id") == flight_id
        ]
