"""Freshness comparison across an epoch that can roll over."""

from __future__ import annotations

from dataclasses import dataclass

from bagsort.model.enums import Verdict


@dataclass
class VerdictTracker:
    """High-water mark of the (epoch, sequence) pairs already acted upon."""

    epoch: int = 0
    sequence: int = 0
    seen: int = 0

    def classify(self, epoch: int, sequence: int) -> Verdict:
        """Decide whether the pair is new, a replay of the mark, or an older wrap."""

        if epoch > self.epoch:
            return Verdict.FRESH
        if epoch < self.epoch:
            return Verdict.ROLLED_OVER
        if sequence > self.sequence:
            return Verdict.FRESH
        if sequence < self.sequence:
            return Verdict.ROLLED_OVER
        return Verdict.REPLAYED

    def observe(self, epoch: int, sequence: int) -> Verdict:
        """Classify and, when fresh, advance the mark."""

        verdict = self.classify(epoch, sequence)
        if verdict is Verdict.FRESH:
            self.epoch = epoch
            self.sequence = sequence
            self.seen += 1
        return verdict

    def is_fresh(self, epoch: int, sequence: int) -> bool:
        return self.classify(epoch, sequence) is Verdict.FRESH

    def high_water(self) -> tuple[int, int]:
        return self.epoch, self.sequence

    def as_dict(self) -> dict[str, int]:
        return {"epoch": self.epoch, "sequence": self.sequence, "seen": self.seen}
