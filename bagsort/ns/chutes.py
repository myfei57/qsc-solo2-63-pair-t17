"""Registry of the physical chutes and carousels the terminal operates."""

from __future__ import annotations

from dataclasses import dataclass, field

from bagsort.errors import NotFoundError, ValidationError


@dataclass(frozen=True)
class Lane:
    """One chute with the carousel it feeds."""

    chute_id: str
    carousel_id: str
    enabled: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "chute_id": self.chute_id,
            "carousel_id": self.carousel_id,
            "enabled": self.enabled,
        }


@dataclass
class ChuteRegistry:
    """Which chutes exist, which are enabled and which carousel they feed."""

    lanes: dict[str, Lane] = field(default_factory=dict)

    def register(self, chute_id: str, carousel_id: str, enabled: bool = True) -> Lane:
        identifier = (chute_id or "").strip()
        if not identifier:
            raise ValidationError("chute id must not be empty")
        lane = Lane(chute_id=identifier, carousel_id=carousel_id.strip(), enabled=enabled)
        self.lanes[identifier] = lane
        return lane

    def get(self, chute_id: str) -> Lane:
        lane = self.lanes.get(chute_id)
        if lane is None:
            raise NotFoundError(f"chute {chute_id!r} is not registered")
        return lane

    def known(self, chute_id: str) -> bool:
        return chute_id in self.lanes

    def validate(self, chute_id: str) -> bool:
        lane = self.lanes.get((chute_id or "").strip())
        return bool(lane and lane.enabled)

    def disable(self, chute_id: str) -> Lane:
        lane = self.get(chute_id)
        updated = Lane(chute_id=lane.chute_id, carousel_id=lane.carousel_id, enabled=False)
        self.lanes[chute_id] = updated
        return updated

    def enable(self, chute_id: str) -> Lane:
        lane = self.get(chute_id)
        updated = Lane(chute_id=lane.chute_id, carousel_id=lane.carousel_id, enabled=True)
        self.lanes[chute_id] = updated
        return updated

    def enabled_chutes(self) -> list[str]:
        return sorted(lane.chute_id for lane in self.lanes.values() if lane.enabled)

    def carousels(self) -> list[str]:
        return sorted({lane.carousel_id for lane in self.lanes.values() if lane.carousel_id})

    def as_list(self) -> list[dict[str, object]]:
        return [self.lanes[key].as_dict() for key in sorted(self.lanes)]

    def summary(self) -> dict[str, object]:
        return {
            "lanes": self.as_list(),
            "enabled": self.enabled_chutes(),
            "carousels": self.carousels(),
            "count": len(self.lanes),
        }
