"""Per route request counters and latency totals."""

from __future__ import annotations


class Metrics:
    """Aggregated console traffic, refreshed by the middleware."""

    def __init__(self) -> None:
        self._requests = 0
        self._errors = 0
        self._seconds = 0.0
        self._by_path: dict[str, int] = {}
        self._by_status: dict[str, int] = {}

    def observe(self, path: str, status: int, seconds: float) -> None:
        self._requests += 1
        self._seconds += seconds
        if status >= 400:
            self._errors += 1
        self._by_path[path] = self._by_path.get(path, 0) + 1
        key = str(status)
        self._by_status[key] = self._by_status.get(key, 0) + 1

    def snapshot(self) -> dict[str, object]:
        average = (self._seconds / self._requests) if self._requests else 0.0
        return {
            "requests": self._requests,
            "errors": self._errors,
            "seconds": round(self._seconds, 6),
            "average_seconds": round(average, 6),
            "by_path": dict(sorted(self._by_path.items())),
            "by_status": dict(sorted(self._by_status.items())),
        }

    def reset(self) -> None:
        self.__init__()
