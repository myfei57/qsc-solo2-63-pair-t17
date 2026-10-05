"""The synchronous event bus."""

from __future__ import annotations

from bagsort.events.bus import EventBus


def test_subscribers_receive_matching_events():
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe("bag.sorted", lambda event: seen.append(event.payload["bag_id"]))
    bus.publish("bag.sorted", bag_id="T1-1")
    bus.publish("flight.closed", flight_id="T1-CA1")
    assert seen == ["T1-1"]
    assert bus.delivered() == 2


def test_wildcard_subscriber_sees_every_topic():
    bus = EventBus()
    topics: list[str] = []
    bus.subscribe("*", lambda event: topics.append(event.topic))
    bus.publish("a")
    bus.publish("b")
    assert topics == ["a", "b"]


def test_history_is_bounded_and_filterable():
    bus = EventBus(history_limit=3)
    for index in range(5):
        bus.publish("tick", index=index)
    assert len(bus.history()) == 3
    assert len(bus.history("tick")) == 3
    assert bus.history("missing") == []


def test_topics_and_subscriber_counts_are_reported():
    bus = EventBus()
    bus.subscribe("bag.sorted", lambda event: None)
    bus.subscribe("bag.sorted", lambda event: None)
    assert bus.subscribers("bag.sorted") == 2
    assert bus.topics() == ["bag.sorted"]
    assert bus.publish("bag.sorted").as_dict()["topic"] == "bag.sorted"
