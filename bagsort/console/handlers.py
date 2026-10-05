"""HTTP handlers. Every one delegates to an operation on the wired plant."""

from __future__ import annotations

from bagsort.checkin.entries import Entry
from bagsort.model.entities import Flight, Reading
from bagsort.model.validate import validate_flight
from bagsort.reporting import csv_export
from bagsort.sequence.allocator import preview
from bagsort.store.replay import replay
from .http import Request, Response, csv_response, json_response, text_response
from .routes import route_table
from .version import version_info


def _plant(server):
    return server.plant


# ---------------------------------------------------------------------------
# service level
# ---------------------------------------------------------------------------


def handle_health(server, request: Request) -> Response:
    plant = _plant(server)
    return json_response(
        {
            "status": "ok",
            "watermark": plant.store.watermark,
            "dirty": plant.store.dirty(),
            "audit_intact": plant.audit.verify(),
        }
    )


def handle_version(server, request: Request) -> Response:
    return json_response(version_info())


def handle_system(server, request: Request) -> Response:
    plant = _plant(server)
    payload = version_info()
    payload.update(
        {
            "terminal": plant.namespace.terminal,
            "store": plant.store.path,
            "watermark": plant.store.watermark,
            "clock": plant.clock.now_iso(),
        }
    )
    return json_response(payload)


def handle_topology(server, request: Request) -> Response:
    topology = _plant(server).topology
    return json_response(
        {
            "name": topology.name,
            "stages": list(topology.stages),
            "line": topology.describe(),
            "count": topology.count(),
        }
    )


def handle_topology_stage(server, request: Request) -> Response:
    topology = _plant(server).topology
    stage = request.param("stage")
    return json_response(
        {
            "stage": stage,
            "known": topology.contains(stage),
            "index": topology.index_of(stage),
            "next": topology.next_stage(stage),
            "following": list(topology.following(stage)),
        }
    )


def handle_catalog(server, request: Request) -> Response:
    return json_response([route.as_dict() for route in route_table()])


def handle_stats(server, request: Request) -> Response:
    return json_response(_plant(server).store.stats())


def handle_reset(server, request: Request) -> Response:
    plant = _plant(server)
    plant.store.reset()
    return json_response({"status": "cleared"})


def handle_metrics(server, request: Request) -> Response:
    return json_response(_plant(server).metrics.snapshot())


def handle_metrics_reset(server, request: Request) -> Response:
    plant = _plant(server)
    plant.metrics.reset()
    return json_response({"status": "reset"})


def handle_telemetry(server, request: Request) -> Response:
    telemetry = _plant(server).telemetry
    return json_response({"total": telemetry.total(), "topics": telemetry.snapshot()})


def handle_report(server, request: Request) -> Response:
    return text_response(_plant(server).report.text())


def handle_report_flights(server, request: Request) -> Response:
    return json_response(_plant(server).report.flight_rows())


def handle_events(server, request: Request) -> Response:
    bus = _plant(server).bus
    return json_response(
        {
            "delivered": bus.delivered(),
            "topics": bus.topics(),
            "history": [event.as_dict() for event in bus.history()],
        }
    )


def handle_events_topic(server, request: Request) -> Response:
    bus = _plant(server).bus
    topic = request.param("topic")
    return json_response(
        {
            "topic": topic,
            "subscribers": bus.subscribers(topic),
            "events": [event.as_dict() for event in bus.history(topic)],
        }
    )


def handle_telemetry_reset(server, request: Request) -> Response:
    plant = _plant(server)
    plant.telemetry.reset()
    return json_response({"status": "reset"})


# ---------------------------------------------------------------------------
# flights
# ---------------------------------------------------------------------------


def handle_list_flights(server, request: Request) -> Response:
    return json_response([flight.as_dict() for flight in _plant(server).book.list()])


def handle_register_flight(server, request: Request) -> Response:
    plant = _plant(server)
    flight = plant.register_flight(
        request.required("code"),
        request.str_field("carousel"),
        request.str_field("chute"),
    )
    return json_response(flight.as_dict(), status=201)


def handle_validate_flight(server, request: Request) -> Response:
    flight = Flight(
        id=request.str_field("id"),
        code=request.str_field("code"),
        carousel=request.str_field("carousel"),
    )
    validate_flight(flight)
    return json_response({"valid": True, "id": flight.id})


def handle_open_flights(server, request: Request) -> Response:
    return json_response([flight.as_dict() for flight in _plant(server).book.open_flights()])


def handle_find_by_code(server, request: Request) -> Response:
    flight = _plant(server).book.find_by_code(request.param("code"))
    if flight is None:
        return json_response({"error": "not found"}, status=404)
    return json_response(flight.as_dict())


def handle_get_flight(server, request: Request) -> Response:
    return json_response(_plant(server).book.get(request.param("id")).as_dict())


def handle_open_flight(server, request: Request) -> Response:
    return json_response(_plant(server).book.open(request.param("id")).as_dict())


def handle_board_flight(server, request: Request) -> Response:
    return json_response(_plant(server).book.board(request.param("id")).as_dict())


def handle_cutoff_flight(server, request: Request) -> Response:
    return json_response(_plant(server).book.cutoff(request.param("id")).as_dict())


def handle_close_flight(server, request: Request) -> Response:
    return json_response(_plant(server).close_flight(request.param("id")).as_dict())


def handle_set_cutoff(server, request: Request) -> Response:
    flight = _plant(server).book.set_cutoff(request.param("id"), request.str_field("cutoff"))
    return json_response(flight.as_dict())


def handle_set_carousel(server, request: Request) -> Response:
    flight = _plant(server).book.set_carousel(request.param("id"), request.str_field("carousel"))
    return json_response(flight.as_dict())


def handle_set_batch(server, request: Request) -> Response:
    flight = _plant(server).book.set_batch(request.param("id"), request.int_field("batch"))
    return json_response(flight.as_dict())


def handle_get_batch(server, request: Request) -> Response:
    return json_response({"batch": _plant(server).book.batch(request.param("id"))})


def handle_revise_schedule(server, request: Request) -> Response:
    schedule = _plant(server).revise_schedule(
        request.param("id"), request.str_field("cutoff")
    )
    return json_response(schedule.as_dict())


def handle_get_schedule(server, request: Request) -> Response:
    return json_response(_plant(server).schedule.current(request.param("id")).as_dict())


def handle_flight_bags(server, request: Request) -> Response:
    bags = _plant(server).book.list_bags_for(request.param("id"))
    return json_response([bag.as_dict() for bag in bags])


def handle_flight_in_transit(server, request: Request) -> Response:
    plant = _plant(server)
    flight_id = request.param("id")
    return json_response(
        {"flight_id": flight_id, "in_transit": plant.injector.in_transit(flight_id)}
    )


def handle_drain_flight(server, request: Request) -> Response:
    drained = _plant(server).injector.drain_in_transit(request.param("id"))
    return json_response({"drained": drained})


def handle_remove_flight(server, request: Request) -> Response:
    plant = _plant(server)
    flight_id = request.param("id")
    plant.book.remove(flight_id)
    return json_response({"status": "retired", "flight_id": flight_id})


# ---------------------------------------------------------------------------
# bags
# ---------------------------------------------------------------------------


def handle_list_bags(server, request: Request) -> Response:
    bags = _plant(server).store.state().bags
    return json_response([bags[key].as_dict() for key in sorted(bags)])


def handle_check_in(server, request: Request) -> Response:
    bag = _plant(server).check_in(request.required("barcode"), request.required("flight_id"))
    return json_response(bag.as_dict(), status=201)


def handle_check_in_batch(server, request: Request) -> Response:
    entries = [Entry.from_dict(item) for item in request.list_payload() if isinstance(item, dict)]
    bags = _plant(server).desk.check_in_batch(entries)
    return json_response([bag.as_dict() for bag in bags], status=201)


def handle_get_bag(server, request: Request) -> Response:
    return json_response(_plant(server).bag(request.param("id")).as_dict())


def handle_cancel_check_in(server, request: Request) -> Response:
    return json_response(_plant(server).cancel_check_in(request.param("id")).as_dict())


def handle_bag_flight(server, request: Request) -> Response:
    flight_id = _plant(server).mapping.flight_of(request.param("id"))
    return json_response({"bag_id": request.param("id"), "flight_id": flight_id})


def handle_remap_bag(server, request: Request) -> Response:
    bag = _plant(server).remap_bag(request.param("id"), request.required("flight_id"))
    return json_response(bag.as_dict())


def handle_route_detail(server, request: Request) -> Response:
    return json_response(_plant(server).sorter.route(request.param("id")).as_dict())


def handle_sort_count(server, request: Request) -> Response:
    count = _plant(server).sorter.log.count_for(request.param("id"))
    return json_response({"bag_id": request.param("id"), "count": count})


def handle_last_chute(server, request: Request) -> Response:
    chute = _plant(server).sorter.log.last_chute(request.param("id"))
    return json_response({"bag_id": request.param("id"), "chute_id": chute})


# ---------------------------------------------------------------------------
# chutes and assignments
# ---------------------------------------------------------------------------


def handle_list_chutes(server, request: Request) -> Response:
    return json_response(_plant(server).registry.as_list())


def handle_register_chute(server, request: Request) -> Response:
    plant = _plant(server)
    lane = plant.registry.register(
        request.required("chute_id"),
        request.required("carousel_id"),
        request.bool_field("enabled", True),
    )
    return json_response(lane.as_dict(), status=201)


def handle_validate_chute(server, request: Request) -> Response:
    registry = _plant(server).registry
    chute_id = request.str_field("chute_id")
    return json_response({"known": registry.known(chute_id), "valid": registry.validate(chute_id)})


def handle_chute_summary(server, request: Request) -> Response:
    return json_response(_plant(server).registry.summary())


def handle_assign_chute(server, request: Request) -> Response:
    assignment = _plant(server).assign_chute(
        request.required("flight_id"), request.required("chute_id")
    )
    return json_response(assignment.as_dict())


def handle_reassign_chute(server, request: Request) -> Response:
    assignment = _plant(server).chutes.reassign(
        request.required("flight_id"), request.required("chute_id")
    )
    return json_response(assignment.as_dict())


def handle_enable_chute(server, request: Request) -> Response:
    return json_response(_plant(server).registry.enable(request.required("chute_id")).as_dict())


def handle_disable_chute(server, request: Request) -> Response:
    return json_response(_plant(server).registry.disable(request.required("chute_id")).as_dict())


def handle_list_assignments(server, request: Request) -> Response:
    assignments = _plant(server).store.state().assignments
    return json_response([assignments[key].as_dict() for key in sorted(assignments)])


def handle_assignments_by_chute(server, request: Request) -> Response:
    return json_response(_plant(server).chutes.by_chute())


def handle_get_assignment(server, request: Request) -> Response:
    assignment = _plant(server).chutes.current(request.param("flight"))
    if assignment is None:
        return json_response({"error": "not found"}, status=404)
    return json_response(assignment.as_dict())


def handle_assignment_history(server, request: Request) -> Response:
    history = _plant(server).chute_history.for_flight(request.param("flight"))
    return json_response([assignment.as_dict() for assignment in history])


def handle_confirm_assignment(server, request: Request) -> Response:
    assignment = _plant(server).chutes.ensure_current(
        request.param("flight"), request.int_field("generation")
    )
    return json_response({"confirmed": True, **assignment.as_dict()})


# ---------------------------------------------------------------------------
# tag
# ---------------------------------------------------------------------------


def handle_tag_read(server, request: Request) -> Response:
    reading = _plant(server).read_barcode(request.required("barcode"))
    return json_response(reading.as_dict())


def handle_tag_read_batch(server, request: Request) -> Response:
    barcodes = [str(item) for item in request.list_payload()]
    readings = _plant(server).reader.read_batch(barcodes)
    return json_response([reading.as_dict() for reading in readings])


def handle_tag_commit(server, request: Request) -> Response:
    plant = _plant(server)
    items = request.list_payload()
    if items:
        committed = plant.reader.commit_batch(
            plant.reader.read_batch([str(item) for item in items])
        )
        return json_response([reading.as_dict() for reading in committed])
    reading = plant.reader.commit(plant.reader.read(request.required("barcode")))
    return json_response(reading.as_dict(), status=201)


def handle_tag_sequence(server, request: Request) -> Response:
    current = _plant(server).reader.sequence()
    epoch, value = preview(current)
    return json_response({"current": current.as_dict(), "next": {"epoch": epoch, "sequence": value}})


def handle_read_history(server, request: Request) -> Response:
    reads = _plant(server).reads
    return json_response(
        {
            "count": reads.count(),
            "epochs": reads.epochs(),
            "bags": [bag.as_dict() for bag in reads.committed_bags()],
        }
    )


# ---------------------------------------------------------------------------
# sort
# ---------------------------------------------------------------------------


def handle_sort_push(server, request: Request) -> Response:
    record = _plant(server).push_bag(request.required("bag_id"), request.required("chute_id"))
    return json_response(record.as_dict(), status=201)


def handle_sort_dispatch(server, request: Request) -> Response:
    plant = _plant(server)
    bag = plant.bag(request.required("bag_id"))
    reading = Reading(
        barcode=bag.barcode,
        bag_id=bag.id,
        sequence=bag.sequence,
        epoch=bag.epoch,
        committed=request.bool_field("committed", True),
    )
    record = plant.sorter.dispatch(bag, reading)
    return json_response(record.as_dict(), status=201)


def handle_retry(server, request: Request) -> Response:
    sorted_now = _plant(server).retry_bag(request.required("bag_id"))
    return json_response({"sorted": sorted_now})


def handle_divert(server, request: Request) -> Response:
    return json_response(_plant(server).divert_bag(request.required("bag_id")).as_dict())


def handle_sort_records(server, request: Request) -> Response:
    records = _plant(server).sorter.records()
    return json_response([record.as_dict() for record in records])


def handle_sort_by_chute(server, request: Request) -> Response:
    flight_id = request.query_str("flight_id") or None
    return json_response(_plant(server).sorter.log.by_chute(flight_id))


def handle_verdict(server, request: Request) -> Response:
    plant = _plant(server)
    epoch = request.int_field("epoch")
    sequence = request.int_field("sequence")
    was_fresh = plant.sorter.is_fresh(epoch, sequence)
    verdict = plant.sorter.verdict(epoch, sequence)
    return json_response({"verdict": verdict.value, "fresh": was_fresh})


def handle_high_water(server, request: Request) -> Response:
    epoch, sequence = _plant(server).sorter.high_water()
    return json_response({"epoch": epoch, "sequence": sequence})


# ---------------------------------------------------------------------------
# inject
# ---------------------------------------------------------------------------


def handle_inject_queue(server, request: Request) -> Response:
    queue = _plant(server).injector.queue(request.param("flight"))
    return json_response([bag.as_dict() for bag in queue])


def handle_in_transit(server, request: Request) -> Response:
    return json_response({"in_transit": _plant(server).injector.in_transit(request.param("flight"))})


# ---------------------------------------------------------------------------
# recheck
# ---------------------------------------------------------------------------


def handle_enqueue_recheck(server, request: Request) -> Response:
    bag = _plant(server).enqueue_recheck(request.required("bag_id"))
    return json_response({"bag_id": bag.id, "length": _plant(server).recheck.length()}, status=201)


def handle_next_recheck(server, request: Request) -> Response:
    bag = _plant(server).process_recheck()
    if bag is None:
        return json_response({"error": "empty"}, status=404)
    return json_response(bag.as_dict())


def handle_recheck_peek(server, request: Request) -> Response:
    bag = _plant(server).recheck.peek()
    if bag is None:
        return json_response({"error": "empty"}, status=404)
    return json_response(bag.as_dict())


def handle_recheck_items(server, request: Request) -> Response:
    return json_response([bag.as_dict() for bag in _plant(server).recheck.items()])


def handle_recheck_deadline(server, request: Request) -> Response:
    plant = _plant(server)
    flight_id = request.param("flight")
    generation = request.query_int("generation", 0)
    if generation:
        plant.schedule.ensure_current(flight_id, generation)
    return json_response(
        {
            "flight_id": flight_id,
            "deadline": plant.recheck.deadline(flight_id),
            "schedule": plant.schedule.current(flight_id).as_dict(),
        }
    )


def handle_recheck_clear(server, request: Request) -> Response:
    dropped = _plant(server).recheck.clear()
    return json_response({"dropped": dropped})


# ---------------------------------------------------------------------------
# belt
# ---------------------------------------------------------------------------


def handle_belt_state(server, request: Request) -> Response:
    return json_response(_plant(server).belt.describe())


def handle_belt_set(server, request: Request) -> Response:
    payload = _plant(server).belt.set(request.required("carousel"), request.int_field("batch"))
    return json_response(payload)


def handle_belt_switch(server, request: Request) -> Response:
    cleared = _plant(server).switch_belt(request.required("carousel"), request.int_field("batch"))
    return json_response({"cleared": cleared, **_plant(server).belt.describe()})


def handle_belt_rotate(server, request: Request) -> Response:
    return json_response({"dropped": _plant(server).rotate_belt()})


def handle_belt_place(server, request: Request) -> Response:
    plant = _plant(server)
    count = plant.belt.place(plant.bag(request.required("bag_id")))
    return json_response({"on_carousel": count}, status=201)


def handle_belt_place_batch(server, request: Request) -> Response:
    plant = _plant(server)
    bags = [plant.bag(str(item)) for item in request.list_payload()]
    count = plant.belt.place_batch(bags)
    return json_response({"on_carousel": count}, status=201)


def handle_belt_on_carousel(server, request: Request) -> Response:
    return json_response([bag.as_dict() for bag in _plant(server).belt.on_carousel()])


def handle_belt_loads(server, request: Request) -> Response:
    return json_response([record.as_dict() for record in _plant(server).belt.loads()])


def handle_append_transfer(server, request: Request) -> Response:
    command = _plant(server).append_transfer(
        request.required("flight_id"),
        request.required("carousel"),
        request.int_field("batch"),
    )
    return json_response(command.as_dict(), status=201)


def handle_belt_transfers(server, request: Request) -> Response:
    return json_response([command.as_dict() for command in _plant(server).belt.transfers()])


def handle_belt_replay(server, request: Request) -> Response:
    commands = _plant(server).belt.replay_transfers()
    return json_response([command.as_dict() for command in commands])


# ---------------------------------------------------------------------------
# quota
# ---------------------------------------------------------------------------


def handle_set_quota(server, request: Request) -> Response:
    limit = _plant(server).set_quota(request.required("flight_id"), request.int_field("limit"))
    return json_response({"flight_id": request.str_field("flight_id"), "limit": limit})


def handle_quota_status(server, request: Request) -> Response:
    return json_response(_plant(server).quota.status())


def handle_quota_for(server, request: Request) -> Response:
    quota = _plant(server).quota
    flight_id = request.param("flight")
    return json_response(
        {
            "flight_id": flight_id,
            "limit": quota.limit(flight_id),
            "available": quota.available(flight_id),
            "allowed": quota.allowed(flight_id),
        }
    )


def handle_quota_consume(server, request: Request) -> Response:
    allowed = _plant(server).quota.consume(
        request.required("flight_id"), request.int_field("count", 1)
    )
    return json_response({"allowed": allowed})


def handle_quota_release(server, request: Request) -> Response:
    remaining = _plant(server).quota.release(
        request.required("flight_id"), request.int_field("count", 1)
    )
    return json_response({"remaining": remaining})


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def handle_audit(server, request: Request) -> Response:
    entries = _plant(server).audit.entries()
    return json_response([entry.as_dict() for entry in entries])


def handle_audit_count(server, request: Request) -> Response:
    return json_response({"count": _plant(server).audit.count()})


def handle_audit_summary(server, request: Request) -> Response:
    return json_response(_plant(server).audit.by_kind())


def handle_audit_stages(server, request: Request) -> Response:
    return json_response(_plant(server).audit.by_stage())


def handle_audit_last(server, request: Request) -> Response:
    entry = _plant(server).audit.last()
    if entry is None:
        return json_response({"error": "empty"}, status=404)
    return json_response(entry.as_dict())


def handle_audit_verify(server, request: Request) -> Response:
    return json_response({"intact": _plant(server).audit.verify()})


def handle_audit_timeline(server, request: Request) -> Response:
    subject = request.query_str("subject") or None
    entries = _plant(server).audit.timeline(subject)
    return json_response([entry.as_dict() for entry in entries])


def handle_audit_out_of_order(server, request: Request) -> Response:
    entries = _plant(server).audit.out_of_order()
    return json_response({"count": len(entries), "entries": [entry.as_dict() for entry in entries]})


def handle_audit_for_bag(server, request: Request) -> Response:
    entries = _plant(server).audit.for_subject(request.param("bag"))
    return json_response([entry.as_dict() for entry in entries])


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------


def handle_journal(server, request: Request) -> Response:
    plant = _plant(server)
    since = request.query_int("since", 0)
    entries = plant.store.entries_since(since)
    return json_response(
        {"since": since, "watermark": plant.store.watermark, "entries": [e.as_dict() for e in entries]}
    )


def handle_watermark(server, request: Request) -> Response:
    plant = _plant(server)
    return json_response(
        {
            "watermark": plant.store.watermark,
            "entries": len(plant.store.entries()),
            "pending": len(plant.store.pending()),
            "kinds": plant.store.kinds(),
        }
    )


def handle_tombstones(server, request: Request) -> Response:
    entries = _plant(server).store.tombstones()
    return json_response([entry.as_dict() for entry in entries])


def handle_persist(server, request: Request) -> Response:
    digest = _plant(server).store.persist()
    return json_response({"digest": digest})


def handle_replay(server, request: Request) -> Response:
    plant = _plant(server)
    rebuilt = replay(plant.store.entries())
    return json_response(
        {
            "matches": rebuilt.as_dict() == plant.store.state().as_dict(),
            "watermark": plant.store.watermark,
        }
    )


def handle_rollback(server, request: Request) -> Response:
    plant = _plant(server)
    dropped = plant.store.rollback()
    return json_response({"dropped": dropped, "pending": len(plant.store.pending())})


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def handle_export_audit(server, request: Request) -> Response:
    entries = _plant(server).audit.entries()
    return csv_response(csv_export.render(csv_export.AUDIT_COLUMNS, csv_export.audit_rows(entries)))


def handle_export_sort(server, request: Request) -> Response:
    records = _plant(server).sorter.records()
    return csv_response(csv_export.render(csv_export.SORT_COLUMNS, csv_export.sort_rows(records)))


def handle_export_loads(server, request: Request) -> Response:
    records = _plant(server).belt.loads()
    return csv_response(csv_export.render(csv_export.LOAD_COLUMNS, csv_export.load_rows(records)))
