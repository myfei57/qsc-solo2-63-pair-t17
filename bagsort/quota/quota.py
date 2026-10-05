"""Per flight sorting allowance.

The stored value is how many bags the flight may still take. A flight with no
entry on record is unlimited (:data:`UNLIMITED`, a sentinel below zero), so a
configured allowance that has been spent down to zero correctly reads as
exhausted. Both movements are committed commands, so the allowance survives a
restart instead of living in a process variable.
"""

from __future__ import annotations

from bagsort.clock import Clock
from bagsort.errors import ValidationError
from bagsort.store.store import Store

UNLIMITED = -1


class QuotaBook:
    """Tracks how many more bags each flight may accept."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def set_limit(self, flight_id: str, limit: int) -> int:
        if not flight_id:
            raise ValidationError("flight id must not be empty")
        if limit < 0:
            raise ValidationError("quota limit must not be negative")
        with self._store.session() as session:
            session.state.quota_limits[flight_id] = limit
            session.record(
                "quota.set",
                {"flight_id": flight_id, "limit": limit},
                self._clock.now_iso(),
            )
        return limit

    def limit(self, flight_id: str) -> int:
        return self._store.state().quota_limits.get(flight_id, UNLIMITED)

    def is_limited(self, flight_id: str) -> bool:
        return self.limit(flight_id) >= 0

    def available(self, flight_id: str) -> int:
        """Remaining bags, or ``-1`` when the flight is unlimited."""

        return self.limit(flight_id)

    def allowed(self, flight_id: str) -> bool:
        limit = self.limit(flight_id)
        return limit < 0 or limit > 0

    def consume(self, flight_id: str, count: int = 1) -> bool:
        if count < 0:
            raise ValidationError("consume count must not be negative")
        limit = self.limit(flight_id)
        if limit < 0:
            return True
        if limit - count < 0:
            return False
        with self._store.session() as session:
            session.state.quota_limits[flight_id] = limit - count
            session.record(
                "quota.adjust",
                {"flight_id": flight_id, "delta": -count},
                self._clock.now_iso(),
            )
        return True

    def release(self, flight_id: str, count: int = 1) -> int:
        if count < 0:
            raise ValidationError("release count must not be negative")
        limit = self.limit(flight_id)
        if limit < 0:
            return UNLIMITED
        with self._store.session() as session:
            session.state.quota_limits[flight_id] = limit + count
            session.record(
                "quota.adjust",
                {"flight_id": flight_id, "delta": count},
                self._clock.now_iso(),
            )
        return limit + count

    def limits(self) -> dict[str, int]:
        return dict(sorted(self._store.state().quota_limits.items()))

    def status(self) -> list[dict[str, object]]:
        """One row per flight that has an allowance on record."""

        return [
            {
                "flight_id": flight_id,
                "limit": limit,
                "unlimited": limit < 0,
                "allowed": limit < 0 or limit > 0,
            }
            for flight_id, limit in sorted(self._store.state().quota_limits.items())
        ]
