"""Terminal namespace, chute registry and handling topology."""

from __future__ import annotations

import pytest

from bagsort.errors import NotFoundError, OrderingError, ValidationError
from bagsort.ns.chutes import ChuteRegistry
from bagsort.ns.namespace import Namespace
from bagsort.ns.topology import handling_line


def test_namespace_prefixes_every_identifier():
    ns = Namespace("t2")
    assert ns.terminal == "T2"
    assert ns.bag_id("1234") == "T2-1234"
    assert ns.chute_id("a") == "T2-CHA"
    assert ns.carousel_id("cr1") == "T2-CRCR1"
    assert ns.flight_id("ca9") == "T2-CA9"


def test_namespace_rejects_an_empty_terminal():
    with pytest.raises(ValidationError):
        Namespace("  ")


def test_registry_registers_validates_and_toggles():
    registry = ChuteRegistry()
    lane = registry.register("T1-CHA", "T1-CRCR1")
    assert lane.enabled is True
    assert registry.validate("T1-CHA") is True
    assert registry.known("T1-CHA") is True
    registry.disable("T1-CHA")
    assert registry.validate("T1-CHA") is False
    registry.enable("T1-CHA")
    assert registry.validate("T1-CHA") is True


def test_registry_summary_lists_enabled_lanes_and_carousels():
    registry = ChuteRegistry()
    registry.register("T1-CHA", "T1-CRCR1")
    registry.register("T1-CHB", "T1-CRCR2")
    registry.disable("T1-CHB")
    summary = registry.summary()
    assert summary["count"] == 2
    assert summary["enabled"] == ["T1-CHA"]
    assert summary["carousels"] == ["T1-CRCR1", "T1-CRCR2"]


def test_registry_unknown_lane_raises():
    with pytest.raises(NotFoundError):
        ChuteRegistry().get("T1-CHZ")


def test_topology_enforces_the_handling_order():
    line = handling_line()
    assert line.before("tag", "sorter") is True
    assert line.before("sorter", "tag") is False
    assert line.count() == 8
    assert "tag -> inject" in line.describe()


def test_topology_ensure_before_rejects_a_reversed_step():
    with pytest.raises(OrderingError):
        handling_line().ensure_before("belt", "inject")


def test_topology_reports_next_and_following_stages():
    line = handling_line()
    assert line.next_stage("tag") == "inject"
    assert line.next_stage("audit") is None
    assert line.following("chute") == ("recheck", "belt", "audit")
    assert line.contains("recheck") is True
    assert line.index_of("missing") == -1
