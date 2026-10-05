"""Terminal namespace: turns plant-local codes into globally unique identifiers."""

from __future__ import annotations

from bagsort.errors import ValidationError


class Namespace:
    """Prefixes every identifier with its terminal so two halls never collide."""

    def __init__(self, terminal: str) -> None:
        self._terminal = (terminal or "").strip().upper()
        if not self._terminal:
            raise ValidationError("terminal must not be empty")

    @property
    def terminal(self) -> str:
        return self._terminal

    def bag_id(self, barcode: str) -> str:
        return f"{self._terminal}-{barcode.strip()}"

    def chute_id(self, code: str) -> str:
        return f"{self._terminal}-CH{code.strip().upper()}"

    def carousel_id(self, code: str) -> str:
        return f"{self._terminal}-CR{code.strip().upper()}"

    def flight_id(self, code: str) -> str:
        return f"{self._terminal}-{code.strip().upper()}"
