"""Single source of truth for the console route table.

Literal paths are declared before parameterised ones so ``/api/flights/open``
is never mistaken for ``/api/flights/{id}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from .http import Router


@dataclass(frozen=True)
class Route:
    """One console endpoint and the handler function that serves it."""

    method: str
    path: str
    note: str
    handler: str

    def as_dict(self) -> dict[str, str]:
        return {"method": self.method, "path": self.path, "note": self.note}


def route_table() -> list[Route]:
    """Every route the console serves, in catalog order."""

    return [
        # -- service ------------------------------------------------------
        Route("GET", "/api/health", "service health", "handle_health"),
        Route("GET", "/api/version", "build version", "handle_version"),
        Route("GET", "/api/system", "runtime information", "handle_system"),
        Route("GET", "/api/topology", "handling line stages", "handle_topology"),
        Route("GET", "/api/topology/{stage}", "stages that follow one stage", "handle_topology_stage"),
        Route("GET", "/api/catalog", "list every console route", "handle_catalog"),
        Route("GET", "/api/stats", "store statistics", "handle_stats"),
        Route("POST", "/api/admin/reset", "clear the whole journal", "handle_reset"),
        Route("GET", "/api/metrics", "console request metrics", "handle_metrics"),
        Route("POST", "/api/metrics/reset", "reset console metrics", "handle_metrics_reset"),
        Route("GET", "/api/telemetry", "domain event counters", "handle_telemetry"),
        Route("GET", "/api/report", "plain text plant report", "handle_report"),
        Route("GET", "/api/report/flights", "per flight report rows", "handle_report_flights"),
        Route("GET", "/api/events", "recent domain events", "handle_events"),
        Route("GET", "/api/events/{topic}", "subscribers registered for a topic", "handle_events_topic"),
        Route("POST", "/api/telemetry/reset", "reset event counters", "handle_telemetry_reset"),
        # -- flights ------------------------------------------------------
        Route("GET", "/api/flights", "list flights", "handle_list_flights"),
        Route("POST", "/api/flights", "register a flight", "handle_register_flight"),
        Route("POST", "/api/flights/validate", "validate a flight payload", "handle_validate_flight"),
        Route("GET", "/api/flights/open", "flights still boarding", "handle_open_flights"),
        Route("GET", "/api/flights/code/{code}", "find a flight by code", "handle_find_by_code"),
        Route("GET", "/api/flights/{id}", "read one flight", "handle_get_flight"),
        Route("POST", "/api/flights/{id}/open", "re-open a flight", "handle_open_flight"),
        Route("POST", "/api/flights/{id}/board", "mark a flight boarding", "handle_board_flight"),
        Route("POST", "/api/flights/{id}/cutoff", "move a flight to cutoff", "handle_cutoff_flight"),
        Route("POST", "/api/flights/{id}/close", "drain then close a flight", "handle_close_flight"),
        Route("POST", "/api/flights/{id}/cutoff-time", "set the cutoff time", "handle_set_cutoff"),
        Route("POST", "/api/flights/{id}/carousel", "set the flight carousel", "handle_set_carousel"),
        Route("POST", "/api/flights/{id}/batch", "set the flight batch", "handle_set_batch"),
        Route("GET", "/api/flights/{id}/batch", "read the flight batch", "handle_get_batch"),
        Route("POST", "/api/flights/{id}/schedule", "revise the schedule", "handle_revise_schedule"),
        Route("GET", "/api/flights/{id}/schedule", "read the schedule", "handle_get_schedule"),
        Route("GET", "/api/flights/{id}/bags", "bags mapped to the flight", "handle_flight_bags"),
        Route("GET", "/api/flights/{id}/in-transit", "bags still on the belt", "handle_flight_in_transit"),
        Route("POST", "/api/flights/{id}/drain", "drain the in-transit queue", "handle_drain_flight"),
        Route("DELETE", "/api/flights/{id}", "retire a flight", "handle_remove_flight"),
        # -- bags ---------------------------------------------------------
        Route("GET", "/api/bags", "list committed bags", "handle_list_bags"),
        Route("POST", "/api/bags/checkin", "check in one bag", "handle_check_in"),
        Route("POST", "/api/bags/checkin-batch", "check in several bags", "handle_check_in_batch"),
        Route("GET", "/api/bags/{id}", "read one bag", "handle_get_bag"),
        Route("DELETE", "/api/bags/{id}", "cancel a check-in", "handle_cancel_check_in"),
        Route("GET", "/api/bags/{id}/flight", "flight a bag is mapped to", "handle_bag_flight"),
        Route("POST", "/api/bags/{id}/remap", "move a bag to another flight", "handle_remap_bag"),
        Route("GET", "/api/bags/{id}/route", "resolved route of a bag", "handle_route_detail"),
        Route("GET", "/api/bags/{id}/sort-count", "how often a bag was sorted", "handle_sort_count"),
        Route("GET", "/api/bags/{id}/last-chute", "the chute a bag last used", "handle_last_chute"),
        # -- chutes -------------------------------------------------------
        Route("GET", "/api/chutes", "list registered lanes", "handle_list_chutes"),
        Route("POST", "/api/chutes", "register a lane", "handle_register_chute"),
        Route("POST", "/api/chutes/validate", "validate a chute id", "handle_validate_chute"),
        Route("POST", "/api/chutes/assign", "assign a chute", "handle_assign_chute"),
        Route("POST", "/api/chutes/reassign", "re-assign a chute", "handle_reassign_chute"),
        Route("POST", "/api/chutes/enable", "enable a lane", "handle_enable_chute"),
        Route("POST", "/api/chutes/disable", "disable a lane", "handle_disable_chute"),
        Route("GET", "/api/chutes/summary", "lane summary", "handle_chute_summary"),
        Route("GET", "/api/assignments", "list every assignment", "handle_list_assignments"),
        Route("GET", "/api/assignments/by-chute", "assignments grouped by chute", "handle_assignments_by_chute"),
        Route("GET", "/api/assignments/{flight}", "read one assignment", "handle_get_assignment"),
        Route("GET", "/api/assignments/{flight}/history", "assignment history", "handle_assignment_history"),
        Route("POST", "/api/assignments/{flight}/confirm", "confirm a generation", "handle_confirm_assignment"),
        # -- tag ----------------------------------------------------------
        Route("POST", "/api/tag/read", "propose a barcode read", "handle_tag_read"),
        Route("POST", "/api/tag/read-batch", "propose several reads", "handle_tag_read_batch"),
        Route("POST", "/api/tag/commit", "commit a proposed read", "handle_tag_commit"),
        Route("GET", "/api/tag/sequence", "current sequence and epoch", "handle_tag_sequence"),
        Route("GET", "/api/tag/history", "committed read history", "handle_read_history"),
        # -- sort ---------------------------------------------------------
        Route("POST", "/api/sort", "assign a chute and dispatch", "handle_sort_push"),
        Route("POST", "/api/sort/dispatch", "dispatch a committed read", "handle_sort_dispatch"),
        Route("POST", "/api/sort/retry", "re-drive a bag idempotently", "handle_retry"),
        Route("POST", "/api/sort/divert", "divert a bag", "handle_divert"),
        Route("GET", "/api/sort/records", "list sort records", "handle_sort_records"),
        Route("GET", "/api/sort/by-chute", "sort totals per chute", "handle_sort_by_chute"),
        Route("POST", "/api/sort/verdict", "classify a sequence pair", "handle_verdict"),
        Route("GET", "/api/sort/high-water", "freshness high water mark", "handle_high_water"),
        # -- inject -------------------------------------------------------
        Route("GET", "/api/inject/{flight}/queue", "in-transit queue", "handle_inject_queue"),
        Route("GET", "/api/inject/{flight}/in-transit", "in-transit count", "handle_in_transit"),
        # -- recheck ------------------------------------------------------
        Route("POST", "/api/recheck", "enqueue a bag for recheck", "handle_enqueue_recheck"),
        Route("POST", "/api/recheck/next", "process the oldest recheck", "handle_next_recheck"),
        Route("GET", "/api/recheck/peek", "peek at the recheck queue", "handle_recheck_peek"),
        Route("GET", "/api/recheck/items", "list the recheck queue", "handle_recheck_items"),
        Route("GET", "/api/recheck/deadline/{flight}", "cutoff for a flight", "handle_recheck_deadline"),
        Route("POST", "/api/recheck/clear", "clear the recheck queue", "handle_recheck_clear"),
        # -- belt ---------------------------------------------------------
        Route("GET", "/api/belt", "carousel and batch", "handle_belt_state"),
        Route("POST", "/api/belt/set", "set carousel and batch", "handle_belt_set"),
        Route("POST", "/api/belt/switch", "clear then switch batch", "handle_belt_switch"),
        Route("POST", "/api/belt/rotate", "retire stale transfer commands", "handle_belt_rotate"),
        Route("POST", "/api/belt/place", "place a bag on the carousel", "handle_belt_place"),
        Route("POST", "/api/belt/place-batch", "place several bags", "handle_belt_place_batch"),
        Route("GET", "/api/belt/on-carousel", "bags on the carousel", "handle_belt_on_carousel"),
        Route("GET", "/api/belt/loads", "load records", "handle_belt_loads"),
        Route("POST", "/api/belt/transfers", "append a transfer command", "handle_append_transfer"),
        Route("GET", "/api/belt/transfers", "list transfer commands", "handle_belt_transfers"),
        Route("GET", "/api/belt/replay", "transfer commands for this batch", "handle_belt_replay"),
        # -- quota --------------------------------------------------------
        Route("POST", "/api/quota", "set a flight allowance", "handle_set_quota"),
        Route("GET", "/api/quota", "list every allowance", "handle_quota_status"),
        Route("GET", "/api/quota/{flight}", "read one allowance", "handle_quota_for"),
        Route("POST", "/api/quota/consume", "consume allowance", "handle_quota_consume"),
        Route("POST", "/api/quota/release", "release allowance", "handle_quota_release"),
        # -- audit --------------------------------------------------------
        Route("GET", "/api/audit", "list audit entries", "handle_audit"),
        Route("GET", "/api/audit/count", "audit entry count", "handle_audit_count"),
        Route("GET", "/api/audit/summary", "audit counts by kind", "handle_audit_summary"),
        Route("GET", "/api/audit/stages", "audit counts by stage", "handle_audit_stages"),
        Route("GET", "/api/audit/last", "most recent audit entry", "handle_audit_last"),
        Route("GET", "/api/audit/verify", "verify the audit chain", "handle_audit_verify"),
        Route("GET", "/api/audit/timeline", "audit timeline by stage", "handle_audit_timeline"),
        Route("GET", "/api/audit/out-of-order", "entries out of stage order", "handle_audit_out_of_order"),
        Route("GET", "/api/audit/bag/{bag}", "audit entries for one bag", "handle_audit_for_bag"),
        # -- journal ------------------------------------------------------
        Route("GET", "/api/store/journal", "committed journal entries", "handle_journal"),
        Route("GET", "/api/store/watermark", "commit watermark", "handle_watermark"),
        Route("GET", "/api/store/tombstones", "retired entity entries", "handle_tombstones"),
        Route("POST", "/api/store/persist", "persist a snapshot", "handle_persist"),
        Route("POST", "/api/store/replay", "rebuild state from the journal", "handle_replay"),
        Route("POST", "/api/store/rollback", "roll back buffered commands", "handle_rollback"),
        # -- export -------------------------------------------------------
        Route("GET", "/api/export/audit.csv", "audit trail as CSV", "handle_export_audit"),
        Route("GET", "/api/export/sort.csv", "sort records as CSV", "handle_export_sort"),
        Route("GET", "/api/export/loads.csv", "load records as CSV", "handle_export_loads"),
    ]


def register_routes(router: Router, handlers: ModuleType) -> None:
    """Bind every catalogued route to its handler function."""

    for route in route_table():
        router.add(route.method, route.path, getattr(handlers, route.handler))
