"""Counts of published domain events, kept as a projection of the event bus."""

from __future__ import annotations


class Telemetry:
    """How many of each kind of thing the plant did this process lifetime."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def observe(self, topic: str) -> None:
        self._counters[topic] = self._counters.get(topic, 0) + 1

    def total(self) -> int:
        return sum(self._counters.values())

    def snapshot(self) -> dict[str, int]:
        return dict(sorted(self._counters.items()))

    def reset(self) -> None:
        self._counters = {}
