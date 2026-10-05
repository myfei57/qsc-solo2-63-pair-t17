"""Bag sequence allocation with epoch rollover.

Sequences count up to :data:`MAX_SEQUENCE` and then wrap, bumping the epoch. A
rolled epoch keeps new bags distinguishable from a replayed old sequence, which
is the only reason the freshness verdict can stay correct across a wrap.
"""

from __future__ import annotations

from dataclasses import dataclass

from bagsort.model.entities import Sequence

MAX_SEQUENCE = 1000


@dataclass(frozen=True)
class Allocation:
    """The sequence a caller may use, and whether the epoch rolled."""

    sequence: Sequence
    value: int
    rolled_over: bool


def allocate(current: Sequence) -> Allocation:
    next_value = current.next_value + 1
    rolled = False
    if next_value > MAX_SEQUENCE:
        next_value = 1
        rolled = True
    updated = Sequence(epoch=current.epoch + (1 if rolled else 0), next_value=next_value)
    return Allocation(sequence=updated, value=next_value, rolled_over=rolled)


def preview(current: Sequence) -> tuple[int, int]:
    """The (epoch, sequence) the next committed reading would receive."""

    allocation = allocate(current)
    return allocation.sequence.epoch, allocation.value
