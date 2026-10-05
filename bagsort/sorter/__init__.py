"""Dispatch, routing, deduplication and freshness verdicts."""

from __future__ import annotations

from .records import SortLog
from .route import RouteDetail
from .sorter import Sorter

__all__ = ["RouteDetail", "SortLog", "Sorter"]
