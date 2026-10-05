"""The commit watermark, the pending buffer and tombstones."""

from __future__ import annotations

import pytest

from bagsort.errors import ConflictError
from bagsort.store.store import Store


def test_uncommitted_commands_are_invisible(tmp_path):
    store = Store(str(tmp_path / "state.json"))
    with store.session() as session:
        session.record("counter.add", {"name": "probe", "delta": 3})
        session.state.counters["probe"] = 3
        # Pending is visible to the writer, invisible to every reader.
        assert len(store.pending()) == 1
        assert store.state().counters == {}
    assert store.state().counters == {"probe": 3}
    assert store.watermark == 1


def test_rollback_drops_the_pending_buffer(tmp_path):
    store = Store(str(tmp_path / "state.json"))
    with pytest.raises(RuntimeError):
        with store.session() as session:
            session.record("counter.add", {"name": "probe", "delta": 1})
            raise RuntimeError("operator aborted")
    assert store.pending() == []
    assert store.state().counters == {}
    assert store.watermark == 0


def test_explicit_rollback_returns_the_dropped_count(tmp_path):
    store = Store(str(tmp_path / "state.json"))
    store.journal.append("counter.add", {"name": "probe", "delta": 1})
    store.journal.append("counter.add", {"name": "probe", "delta": 1})
    assert store.rollback() == 2
    assert store.state().counters == {}


def test_commit_without_pending_is_a_conflict(tmp_path):
    store = Store(str(tmp_path / "state.json"))
    with pytest.raises(ConflictError):
        store.commit()


def test_watermark_advances_once_per_command(tmp_path):
    store = Store(str(tmp_path / "state.json"))
    with store.session() as session:
        session.record("counter.add", {"name": "a", "delta": 1})
        session.record("counter.add", {"name": "b", "delta": 1})
    assert store.watermark == 2
    assert store.kinds() == {"counter.add": 2}
    assert len(store.entries_since(1)) == 1


def test_tombstones_are_marked(tmp_path):
    store = Store(str(tmp_path / "state.json"))
    with store.session() as session:
        session.record("bag.remove", {"bag_id": "T1-X"})
        session.record("bag.put", {"bag": {"id": "T1-Y", "barcode": "Y", "sequence": 1}})
    marks = store.tombstones()
    assert [entry.kind for entry in marks] == ["bag.remove"]
