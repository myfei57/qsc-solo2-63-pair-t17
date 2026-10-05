"""Domain event bus used to fan out to projections."""

from __future__ import annotations

from .bus import Event, EventBus, Subscriber

__all__ = ["Event", "EventBus", "Subscriber"]
