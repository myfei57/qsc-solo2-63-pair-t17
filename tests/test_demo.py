"""The deterministic scenario."""

from __future__ import annotations

import pytest

from bagsort.demo import invariants_hold, run_demo
from tests.support import make_plant


def test_demo_runs_and_invariants_hold(tmp_path):
    plant = make_plant(tmp_path, name="demo.json")
    summary = run_demo(plant, cycles=5)
    assert invariants_hold(summary) is True
    assert summary["checked_in"] == 5
    assert summary["sorted"] == 5
    assert summary["duplicate_retry_sorted"] is False
    assert summary["audit_verified"] is True


def test_demo_is_deterministic(tmp_path):
    first = run_demo(make_plant(tmp_path / "one"), cycles=4)
    second = run_demo(make_plant(tmp_path / "two"), cycles=4)
    assert first == second


def test_demo_rejects_a_zero_cycle_run(tmp_path):
    with pytest.raises(ValueError):
        run_demo(make_plant(tmp_path / "three"), cycles=0)
