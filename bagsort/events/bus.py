"""Synchronous in-process event bus.

Subsystems publish what happened; projections such as the audit trail and the
telemetry counters subscribe. Delivery is deterministic because subscribers run
in registration order and nothing is queued across threads.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Event:
    """One domain event."""

    topic: str
    payload: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"topic": self.topic, "payload": dict(self.payload)}


Subscriber = Callable[[Event], None]


class EventBus:
    """Topic based publish/subscribe with a bounded history for inspection."""

    def __init__(self, history_limit: int = 256) -> None:
        self._handlers: dict[str, list[Subscriber]] = defaultdict(list)
        self._history: list[Event] = []
        self._limit = history_limit
        self._delivered = 0

    def subscribe(self, topic: str, handler: Subscriber) -> None:
        self._handlers[topic].append(handler)

    def subscribers(self, topic: str) -> int:
        return len(self._handlers.get(topic, ()))

    def publish(self, topic: str, **payload: object) -> Event:
        event = Event(topic=topic, payload=dict(payload))
        for handler in tuple(self._handlers.get(topic, ())):
            handler(event)
        for handler in tuple(self._handlers.get("*", ())):
            handler(event)
        self._history.append(event)
        if len(self._history) > self._limit:
            self._history = self._history[-self._limit :]
        self._delivered += 1
        return event

    def delivered(self) -> int:
        return self._delivered

    def history(self, topic: str | None = None) -> list[Event]:
        if topic is None:
            return list(self._history)
        return [event for event in self._history if event.topic == topic]

    def topics(self) -> list[str]:
        return sorted(set(self._handlers) - {"*"})
