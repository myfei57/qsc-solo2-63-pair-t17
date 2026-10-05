"""File-backed journal store: the single writer all subsystems mutate through."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

from bagsort.errors import ConflictError, ValidationError
from bagsort.model.state import State
from .journal import Journal, JournalEntry
from .replay import replay
from .snapshot import Envelope, build


class Session:
    """A buffered write transaction.

    Commands land in the journal's *pending* buffer as they are recorded, so
    they are visible to ``Store.pending()`` but not to any reader. Nothing
    becomes visible until the session commits, and an exception drops the whole
    buffer.
    """

    def __init__(self, store: "Store") -> None:
        self._store = store
        self.state = store.state().copy()
        self._last_at = ""

    def record(self, kind: str, payload: dict[str, Any], at: str = "") -> None:
        if at:
            self._last_at = at
        self._store.journal.append(kind, payload, at or self._last_at)


class Store:
    """Append-only command log with a materialised view and a commit watermark."""

    def __init__(self, path: str) -> None:
        self._path = os.path.abspath(path)
        self._journal = Journal()
        self._cache: State | None = None
        self._dirty = False

    @property
    def path(self) -> str:
        return self._path

    @property
    def watermark(self) -> int:
        return self._journal.watermark

    # -- read side ---------------------------------------------------------

    def state(self) -> State:
        if self._cache is None:
            self._cache = replay(self._journal.committed())
        return self._cache

    def entries(self) -> list[JournalEntry]:
        return self._journal.committed()

    def entries_since(self, watermark: int) -> list[JournalEntry]:
        return self._journal.since(watermark)

    def pending(self) -> list[tuple[str, dict[str, Any], str]]:
        return self._journal.pending()

    def tombstones(self) -> list[JournalEntry]:
        return self._journal.tombstones()

    def kinds(self) -> dict[str, int]:
        return self._journal.kinds()

    def dirty(self) -> bool:
        return self._dirty

    def stats(self) -> dict[str, int]:
        state = self.state()
        return {
            "watermark": self.watermark,
            "entries": len(self._journal.committed()),
            "flights": len(state.flights),
            "bags": len(state.bags),
            "assignments": len(state.assignments),
            "sort_records": len(state.sort_records),
            "transfer_commands": len(state.transfer_commands),
            "load_records": len(state.load_records),
            "audit": len(state.audit),
        }

    # -- write side --------------------------------------------------------

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Buffer commands; commit on clean exit, roll back on any exception."""

        try:
            yield Session(self)
        except BaseException:
            self._journal.rollback()
            raise
        else:
            if self._journal.has_pending():
                self.commit()

    @property
    def journal(self) -> Journal:
        """The pending/committed log, exposed so a session can stage commands."""

        return self._journal

    def commit(self) -> int:
        if not self._journal.has_pending():
            raise ConflictError("nothing to commit")
        watermark = self._journal.commit()
        self._cache = None
        self._dirty = True
        return watermark

    def rollback(self) -> int:
        dropped = self._journal.rollback()
        if dropped:
            self._dirty = True
        return dropped

    def reset(self) -> None:
        """Drop the whole history, keeping the store usable."""

        self._journal = Journal()
        self._cache = State()
        self._dirty = True

    # -- persistence -------------------------------------------------------

    def envelope(self) -> Envelope:
        return build(self._journal.committed())

    def persist(self) -> str:
        """Write the checksummed envelope atomically and return the digest."""

        envelope = self.envelope()
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        raw = json.dumps(envelope.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        temporary = f"{self._path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(raw)
        os.replace(temporary, self._path)
        self._dirty = False
        return envelope.digest

    def restore(self, envelope: Envelope) -> None:
        """Replace the log with a verified envelope.

        A snapshot whose digest no longer matches its entries is rejected rather
        than silently loaded, so restart cannot resurrect a tampered document.
        """

        if not envelope.verify():
            raise ValidationError("snapshot digest does not match its entries")
        self._journal = Journal()
        for entry in envelope.entries:
            self._journal.append(entry.kind, entry.payload, entry.at)
        self._journal.commit()
        self._cache = None
        self._dirty = False

    @classmethod
    def open(cls, path: str) -> "Store":
        """Load a persisted store, or start an empty one when the file is absent."""

        store = cls(path)
        try:
            with open(store.path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except FileNotFoundError:
            return store
        if not raw.strip():
            return store
        try:
            envelope = Envelope.from_dict(json.loads(raw))
        except (ValueError, TypeError) as exc:
            raise ValidationError(f"store file is not a valid snapshot: {exc}") from exc
        store.restore(envelope)
        return store
