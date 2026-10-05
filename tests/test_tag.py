"""Barcode reading and the two phase commit."""

from __future__ import annotations

from bagsort.model.entities import Sequence
from bagsort.sequence.allocator import MAX_SEQUENCE
from bagsort.tag.history import ReadHistory


def test_read_is_a_proposal_that_allocates_nothing(plant):
    reading = plant.reader.read("9001")
    assert reading.committed is False
    assert reading.bag_id == "T1-9001"
    assert plant.store.watermark == 0
    assert plant.reader.sequence().next_value == 0


def test_commit_persists_the_bag_and_advances_the_sequence(plant):
    committed = plant.reader.commit(plant.reader.read("9001"))
    assert committed.committed is True
    assert committed.sequence == 1
    bag = plant.store.state().bags["T1-9001"]
    assert bag.barcode == "9001"
    assert bag.sequence == 1
    assert plant.reader.sequence().next_value == 1


def test_commit_batch_allocates_contiguous_sequences(plant):
    readings = plant.reader.read_batch(["a", "b", "c"])
    committed = plant.reader.commit_batch(readings)
    assert [item.sequence for item in committed] == [1, 2, 3]
    assert ReadHistory(plant.store).count() == 3


def test_sequence_rolls_the_epoch_after_the_maximum(plant):
    with plant.store.session() as session:
        session.state.sequence = Sequence(epoch=0, next_value=MAX_SEQUENCE - 1)
        session.record("sequence.put", {"epoch": 0, "next": MAX_SEQUENCE - 1})
    committed = plant.reader.commit(plant.reader.read("last"))
    assert committed.sequence == MAX_SEQUENCE
    rolled = plant.reader.commit(plant.reader.read("wrap"))
    assert rolled.sequence == 1
    assert rolled.epoch == 1


def test_history_reports_epochs_and_bags(plant):
    plant.reader.commit_batch(plant.reader.read_batch(["x", "y"]))
    history = ReadHistory(plant.store)
    assert history.count() == 2
    assert history.epochs() == [0]
    assert [bag.barcode for bag in history.committed_bags()] == ["x", "y"]
