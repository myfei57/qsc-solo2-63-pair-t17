"""Console payload for a batch of check-in requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Entry:
    """One barcode paired with the flight the passenger is checking in for."""

    barcode: str
    flight_id: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Entry":
        return cls(barcode=str(raw.get("barcode", "")), flight_id=str(raw.get("flight_id", "")))
