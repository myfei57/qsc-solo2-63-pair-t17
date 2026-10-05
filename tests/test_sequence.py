"""Sequence allocation across an epoch rollover."""

from __future__ import annotations

from bagsort.model.entities import Sequence
from bagsort.model.enums import Verdict
from bagsort.sequence.allocator import MAX_SEQUENCE, allocate, preview
from bagsort.sequence.verdict import VerdictTracker


def test_allocate_increments_within_an_epoch():
    allocation = allocate(Sequence(epoch=0, next_value=4))
    assert allocation.value == 5
    assert allocation.sequence == Sequence(epoch=0, next_value=5)
    assert allocation.rolled_over is False


def test_allocate_rolls_the_epoch_at_the_maximum():
    allocation = allocate(Sequence(epoch=3, next_value=MAX_SEQUENCE))
    assert allocation.value == 1
    assert allocation.sequence.epoch == 4
    assert allocation.rolled_over is True


def test_preview_matches_the_next_allocated_pair():
    current = Sequence(epoch=2, next_value=9)
    assert preview(current) == (2, 10)


def test_verdict_classifies_new_and_replayed_pairs():
    tracker = VerdictTracker(epoch=1, sequence=5)
    assert tracker.classify(1, 6) is Verdict.FRESH
    assert tracker.classify(1, 5) is Verdict.REPLAYED
    assert tracker.classify(2, 0) is Verdict.FRESH
    assert tracker.classify(0, 99) is Verdict.ROLLED_OVER


def test_observe_advances_only_on_fresh_pairs():
    tracker = VerdictTracker()
    assert tracker.observe(0, 1) is Verdict.FRESH
    assert tracker.observe(0, 1) is Verdict.REPLAYED
    assert tracker.high_water() == (0, 1)
    assert tracker.seen == 1
    assert tracker.observe(1, 1) is Verdict.FRESH
    assert tracker.high_water() == (1, 1)


def test_old_epoch_is_never_fresh():
    tracker = VerdictTracker(epoch=5, sequence=1)
    assert tracker.is_fresh(4, 999) is False
    assert tracker.as_dict()["epoch"] == 5
