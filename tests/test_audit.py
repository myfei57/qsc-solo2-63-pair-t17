"""The tamper evident audit chain."""

from __future__ import annotations

import pytest

from bagsort.model.entities import AuditEntry
from bagsort.audit.chain import GENESIS, digest_of
from tests.support import check_in, register_flight


def test_entries_link_back_to_the_previous_digest(plant, flight):
    check_in(plant, flight.id, 1)
    plant.assign_chute(flight.id, "T1-CHA")
    entries = plant.audit.entries()
    assert entries[0].prev_digest == GENESIS
    assert entries[1].prev_digest == entries[0].digest
    assert plant.audit.count() == len(entries)
    assert plant.audit.last() == entries[-1]
    assert plant.audit.verify() is True


def test_verify_detects_a_tampered_entry(plant, flight):
    check_in(plant, flight.id, 1)
    state = plant.store.state()
    original = state.audit[0]
    state.audit[0] = AuditEntry(
        sequence=original.sequence,
        kind="rewritten",
        subject=original.subject,
        detail=original.detail,
        prev_digest=original.prev_digest,
        digest=original.digest,
        at=original.at,
    )
    assert plant.audit.verify() is False


def test_digest_is_stable_for_identical_records():
    entry = AuditEntry(sequence=1, kind="x", subject="s", detail={"a": 1}, prev_digest=GENESIS)
    again = AuditEntry(sequence=1, kind="x", subject="s", detail={"a": 1}, prev_digest=GENESIS)
    assert digest_of(entry) == digest_of(again)


def test_summaries_group_by_kind_and_stage(plant, flight):
    check_in(plant, flight.id, 2)
    plant.switch_belt("T1-CRCR1", 1)
    kinds = plant.audit.by_kind()
    stages = plant.audit.by_stage()
    assert kinds["checkin"] == 2
    assert stages["checkin"] == 2
    assert "belt" in stages


def test_timeline_orders_by_handling_stage(plant, flight):
    check_in(plant, flight.id, 1)
    plant.belt.set("T1-CRCR1", 1)
    plant.append_transfer(flight.id, "T1-CRCR1", 1)
    ordered = plant.audit.timeline()
    indexes = [entry.detail["stage_index"] for entry in ordered]
    assert indexes == sorted(indexes)


def test_out_of_order_flags_a_step_that_claims_to_be_earlier(plant, flight):
    check_in(plant, flight.id, 1)
    bag = check_in(plant, flight.id, 1)[0]
    plant.audit.record("sort", bag.id, "sorter")
    plant.audit.record("late_checkin", bag.id, "checkin")
    flagged = plant.audit.out_of_order()
    assert [entry.kind for entry in flagged] == ["late_checkin"]


def test_for_subject_filters_by_bag(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    other = register_flight(plant, code="ZZ1")
    check_in(plant, other.id, 1, prefix="XX")
    assert [entry.subject for entry in plant.audit.for_subject(bag.id)] == [bag.id]


def test_unknown_stage_is_rejected(plant):
    with pytest.raises(ValueError):
        plant.audit.record("probe", "subject", "nowhere")
