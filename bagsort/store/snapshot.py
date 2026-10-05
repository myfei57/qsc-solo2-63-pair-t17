"""Checksummed snapshot envelope used to persist the committed journal."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .journal import JournalEntry

ENVELOPE_VERSION = 1


def canonical(entries: list[JournalEntry]) -> str:
    """Stable JSON rendering used for the integrity digest."""

    payload = [entry.as_dict() for entry in entries]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_for(entries: list[JournalEntry]) -> str:
    return hashlib.sha256(canonical(entries).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Envelope:
    """A snapshot of the committed journal plus enough metadata to verify it."""

    watermark: int
    digest: str
    entries: tuple[JournalEntry, ...]
    version: int = ENVELOPE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "watermark": self.watermark,
            "digest": self.digest,
            "entry_count": len(self.entries),
            "entries": [entry.as_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Envelope":
        entries = tuple(JournalEntry.from_dict(item) for item in raw.get("entries", []))
        return cls(
            watermark=int(raw.get("watermark", 0)),
            digest=str(raw.get("digest", "")),
            entries=entries,
            version=int(raw.get("version", ENVELOPE_VERSION)),
        )

    def verify(self) -> bool:
        """True when the digest still matches the entries and the watermark agrees."""

        if digest_for(list(self.entries)) != self.digest:
            return False
        if self.watermark != (self.entries[-1].sequence if self.entries else 0):
            return False
        return True


def build(entries: list[JournalEntry]) -> Envelope:
    watermark = entries[-1].sequence if entries else 0
    return Envelope(watermark=watermark, digest=digest_for(entries), entries=tuple(entries))
