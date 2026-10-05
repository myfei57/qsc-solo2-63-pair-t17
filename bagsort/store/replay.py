"""Rebuild materialised state from a committed journal."""

from __future__ import annotations

from typing import Any, Iterable

from bagsort.model.state import State, fold
from .journal import JournalEntry


def replay(entries: Iterable[JournalEntry]) -> State:
    """Fold committed entries into a fresh :class:`State`."""

    return fold(command_pairs(entries))


def command_pairs(entries: Iterable[JournalEntry]) -> list[tuple[str, dict[str, Any]]]:
    return [(entry.kind, entry.payload) for entry in entries]
