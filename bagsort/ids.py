"""Deterministic identifier factory.

Identifiers are drawn from a monotonic counter, so replaying the same command
stream on two machines produces byte-identical records. No randomness and no
wall clock are involved.
"""

from __future__ import annotations


class IdFactory:
    """Emit ``prefix-NNNNNN`` identifiers from a monotonically increasing counter."""

    def __init__(self, prefix: str, start: int = 0, width: int = 6) -> None:
        self._prefix = prefix
        self._next = start
        self._width = width

    def next(self) -> str:
        self._next += 1
        return f"{self._prefix}-{self._next:0{self._width}d}"
