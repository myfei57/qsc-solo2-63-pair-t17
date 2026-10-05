"""The JSON control console, exercised through the in-process entry point."""

from __future__ import annotations

import io
import json

from tests.support import make_server


def call(server, method: str, path: str, payload=None, query=None):
    response = server.call(method, path, payload, query)
    if response.content_type.startswith("application/json"):
        return response.status, json.loads(response.body)
    return response.status, response.body.decode("utf-8")


def bootstrap(server):
    status, _ = call(
        server,
        "POST",
        "/api/flights",
        {"code": "CA1234", "carousel": "CR1", "chute": "A"},
    )
    assert status == 201
    return "T1-CA1234"


def test_service_endpoints(server):
    status, health = call(server, "GET", "/api/health")
    assert (status, health["status"]) == (200, "ok")
    assert health["audit_intact"] is True

    assert call(server, "GET", "/api/version")[1]["service"] == "line-control-service"
    assert call(server, "GET", "/api/system")[1]["terminal"] == "T1"

    status, topology = call(server, "GET", "/api/topology")
    assert topology["count"] == 8
    status, stage = call(server, "GET", "/api/topology/tag")
    assert stage["next"] == "inject"
    assert stage["following"] == ["inject", "sorter", "chute", "recheck", "belt", "audit"]

    status, catalog = call(server, "GET", "/api/catalog")
    assert status == 200
    assert len(catalog) >= 90

    status, report = call(server, "GET", "/api/report")
    assert status == 200 and "terminal" in report

    status, events = call(server, "GET", "/api/events")
    assert events["delivered"] == 0


def test_flight_endpoints(server):
    flight_id = bootstrap(server)
    status, flights = call(server, "GET", "/api/flights")
    assert len(flights) == 1
    assert call(server, "GET", "/api/flights/open")[1][0]["id"] == flight_id
    assert call(server, "GET", f"/api/flights/code/ca1234")[1]["id"] == flight_id
    assert call(server, "GET", f"/api/flights/{flight_id}")[1]["code"] == "CA1234"

    status, valid = call(server, "POST", "/api/flights/validate", {"id": "T1-X", "code": "X"})
    assert (status, valid["valid"]) == (200, True)

    assert call(server, "POST", f"/api/flights/{flight_id}/board")[1]["state"] == "boarding"
    assert call(server, "POST", f"/api/flights/{flight_id}/cutoff-time", {"cutoff": "10:00"})[1][
        "cutoff_at"
    ] == "10:00"
    assert call(server, "POST", f"/api/flights/{flight_id}/carousel", {"carousel": "CR2"})[1][
        "carousel"
    ] == "CR2"
    assert call(server, "POST", f"/api/flights/{flight_id}/batch", {"batch": 4})[1]["batch"] == 4
    assert call(server, "GET", f"/api/flights/{flight_id}/batch")[1]["batch"] == 4

    status, revised = call(server, "POST", f"/api/flights/{flight_id}/schedule", {"cutoff": "11:00"})
    assert revised["generation"] == 2
    assert call(server, "GET", f"/api/flights/{flight_id}/schedule")[1]["generation"] == 2

    assert call(server, "POST", f"/api/flights/{flight_id}/close")[1]["state"] == "closed"
    assert call(server, "DELETE", f"/api/flights/{flight_id}")[1]["status"] == "retired"
    assert call(server, "GET", f"/api/flights/{flight_id}")[0] == 404


def test_bag_and_tag_endpoints(server):
    flight_id = bootstrap(server)
    status, reading = call(server, "POST", "/api/tag/read", {"barcode": "1001"})
    assert (status, reading["committed"]) == (200, False)

    status, readings = call(server, "POST", "/api/tag/read-batch", ["1002", "1003"])
    assert [item["bag_id"] for item in readings] == ["T1-1002", "T1-1003"]

    status, committed = call(server, "POST", "/api/tag/commit", {"barcode": "1001"})
    assert (status, committed["sequence"]) == (201, 1)
    status, batch = call(server, "POST", "/api/tag/commit", ["1002", "1003"])
    assert [item["sequence"] for item in batch] == [2, 3]

    status, sequence = call(server, "GET", "/api/tag/sequence")
    assert sequence["current"] == {"epoch": 0, "next": 3}
    assert sequence["next"] == {"epoch": 0, "sequence": 4}
    assert call(server, "GET", "/api/tag/history")[1]["count"] == 3

    status, bag = call(server, "POST", "/api/bags/checkin", {"barcode": "2001", "flight_id": flight_id})
    assert (status, bag["state"]) == (201, "injected")
    assert call(server, "GET", f"/api/bags/{bag['id']}")[1]["barcode"] == "2001"
    assert call(server, "GET", f"/api/bags/{bag['id']}/flight")[1]["flight_id"] == flight_id
    assert call(server, "POST", "/api/bags/checkin-batch", [{"barcode": "2002", "flight_id": flight_id}])[0] == 201
    assert len(call(server, "GET", "/api/bags")[1]) == 5


def test_chute_endpoints(server):
    flight_id = bootstrap(server)
    status, lane = call(server, "POST", "/api/chutes", {"chute_id": "T1-CHZ", "carousel_id": "T1-CRCR9"})
    assert (status, lane["enabled"]) == (201, True)
    assert call(server, "GET", "/api/chutes/summary")[1]["count"] == 1
    assert call(server, "POST", "/api/chutes/validate", {"chute_id": "T1-CHZ"})[1] == {
        "known": True,
        "valid": True,
    }
    assert call(server, "POST", "/api/chutes/disable", {"chute_id": "T1-CHZ"})[1]["enabled"] is False
    assert call(server, "POST", "/api/chutes/enable", {"chute_id": "T1-CHZ"})[1]["enabled"] is True

    status, assignment = call(server, "POST", "/api/chutes/reassign", {"flight_id": flight_id, "chute_id": "T1-CHZ"})
    assert (assignment["chute_id"], assignment["generation"]) == ("T1-CHZ", 2)
    assert call(server, "GET", f"/api/assignments/{flight_id}")[1]["generation"] == 2
    assert len(call(server, "GET", f"/api/assignments/{flight_id}/history")[1]) == 2
    assert call(server, "POST", f"/api/assignments/{flight_id}/confirm", {"generation": 2})[1][
        "confirmed"
    ] is True
    assert call(server, "POST", f"/api/assignments/{flight_id}/confirm", {"generation": 1})[0] == 409
    assert call(server, "GET", "/api/assignments/by-chute")[1] == {"T1-CHZ": [flight_id]}


def test_sort_and_inject_endpoints(server):
    flight_id = bootstrap(server)
    call(server, "POST", "/api/chutes/assign", {"flight_id": flight_id, "chute_id": "T1-CHA"})
    call(server, "POST", "/api/bags/checkin", {"barcode": "3001", "flight_id": flight_id})
    bag_id = "T1-3001"

    assert call(server, "GET", f"/api/inject/{flight_id}/queue")[1][0]["id"] == bag_id
    assert call(server, "GET", f"/api/inject/{flight_id}/in-transit")[1]["in_transit"] == 1

    status, record = call(server, "POST", "/api/sort/dispatch", {"bag_id": bag_id, "committed": False})
    assert status == 409
    status, record = call(server, "POST", "/api/sort/dispatch", {"bag_id": bag_id})
    assert (status, record["chute_id"]) == (201, "T1-CHA")
    assert call(server, "POST", "/api/sort/dispatch", {"bag_id": bag_id})[0] == 409
    assert call(server, "POST", "/api/sort/retry", {"bag_id": bag_id})[1]["sorted"] is False
    assert call(server, "GET", "/api/sort/records")[1][0]["bag_id"] == bag_id
    assert call(server, "GET", f"/api/bags/{bag_id}/sort-count")[1]["count"] == 1
    assert call(server, "GET", f"/api/bags/{bag_id}/last-chute")[1]["chute_id"] == "T1-CHA"
    assert call(server, "GET", "/api/sort/by-chute")[1] == {"T1-CHA": 1}

    assert call(server, "POST", "/api/sort/verdict", {"epoch": 0, "sequence": 9})[1] == {
        "verdict": "fresh",
        "fresh": True,
    }
    assert call(server, "GET", "/api/sort/high-water")[1] == {"epoch": 0, "sequence": 9}


def test_recheck_and_belt_endpoints(server):
    flight_id = bootstrap(server)
    call(server, "POST", "/api/bags/checkin", {"barcode": "4001", "flight_id": flight_id})
    assert call(server, "POST", "/api/recheck", {"bag_id": "T1-4001"})[1]["length"] == 1
    assert call(server, "GET", "/api/recheck/peek")[1]["id"] == "T1-4001"
    assert call(server, "GET", "/api/recheck/items")[1][0]["id"] == "T1-4001"
    assert call(server, "GET", f"/api/recheck/deadline/{flight_id}")[1]["schedule"]["generation"] == 1
    assert call(server, "POST", "/api/recheck/next")[1]["id"] == "T1-4001"
    assert call(server, "POST", "/api/recheck/clear")[1]["dropped"] == 0

    assert call(server, "POST", "/api/belt/set", {"carousel": "T1-CRCR1", "batch": 1})[1]["batch"] == 1
    assert call(server, "POST", "/api/belt/place", {"bag_id": "T1-4001"})[1]["on_carousel"] == 1
    assert len(call(server, "GET", "/api/belt/on-carousel")[1]) == 1
    assert call(server, "POST", "/api/belt/transfers", {"flight_id": flight_id, "carousel": "T1-CRCR1", "batch": 1})[0] == 201
    assert len(call(server, "GET", "/api/belt/transfers")[1]) == 1
    assert len(call(server, "GET", "/api/belt/replay")[1]) == 1
    assert call(server, "POST", "/api/belt/switch", {"carousel": "T1-CRCR2", "batch": 2})[1]["cleared"] == 1
    assert call(server, "GET", "/api/belt/loads")[1][0]["carousel"] == "T1-CRCR1"
    assert call(server, "POST", "/api/belt/rotate")[1]["dropped"] == 0


def test_quota_and_audit_endpoints(server):
    flight_id = bootstrap(server)
    assert call(server, "POST", "/api/quota", {"flight_id": flight_id, "limit": 2})[1]["limit"] == 2
    assert call(server, "GET", "/api/quota")[1][0]["limit"] == 2
    assert call(server, "GET", f"/api/quota/{flight_id}")[1]["available"] == 2
    assert call(server, "POST", "/api/quota/consume", {"flight_id": flight_id, "count": 1})[1]["allowed"] is True
    assert call(server, "POST", "/api/quota/release", {"flight_id": flight_id, "count": 2})[1]["remaining"] == 3

    call(server, "POST", "/api/bags/checkin", {"barcode": "5001", "flight_id": flight_id})
    assert call(server, "GET", "/api/audit/count")[1]["count"] == 2
    assert call(server, "GET", "/api/audit/summary")[1]["checkin"] == 1
    assert call(server, "GET", "/api/audit/stages")[1]["checkin"] == 1
    assert call(server, "GET", "/api/audit/last")[1]["kind"] == "checkin"
    assert call(server, "GET", "/api/audit/verify")[1]["intact"] is True
    assert call(server, "GET", "/api/audit/timeline")[1][0]["subject"] == "T1-5001"
    assert call(server, "GET", "/api/audit/out-of-order")[1]["count"] == 0
    assert call(server, "GET", "/api/audit/bag/T1-5001")[1][0]["kind"] == "checkin"
    assert len(call(server, "GET", "/api/audit")[1]) == 2


def test_journal_and_export_endpoints(server):
    flight_id = bootstrap(server)
    call(server, "POST", "/api/bags/checkin", {"barcode": "6001", "flight_id": flight_id})
    status, watermark = call(server, "GET", "/api/store/watermark")
    assert watermark["watermark"] > 0
    assert watermark["pending"] == 0

    status, journal = call(server, "GET", "/api/store/journal", query={"since": ["0"]})
    assert journal["entries"][0]["sequence"] == 1
    status, rolled = call(server, "POST", "/api/store/rollback")
    assert rolled == {"dropped": 0, "pending": 0}
    assert call(server, "POST", "/api/store/replay")[1]["matches"] is True
    assert call(server, "POST", "/api/store/persist")[1]["digest"]
    assert call(server, "GET", "/api/store/tombstones")[1] == []

    status, audit_csv = call(server, "GET", "/api/export/audit.csv")
    assert status == 200 and audit_csv.startswith("sequence,kind,subject")
    assert call(server, "GET", "/api/export/sort.csv")[1].startswith("bag_id,flight_id")
    assert call(server, "GET", "/api/export/loads.csv")[1].startswith("bag_id,carousel")


def _wsgi(server, method: str, path: str, body: bytes = b"") -> int:
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split(" ")[0])

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
    }
    server(environ, start_response)
    return captured["status"]


def test_metrics_and_telemetry(server):
    bootstrap(server)
    assert call(server, "GET", "/api/telemetry")[1]["total"] > 0
    assert _wsgi(server, "GET", "/api/health") == 200
    assert _wsgi(server, "GET", "/api/health") == 200
    assert call(server, "GET", "/api/metrics")[1]["requests"] == 2
    call(server, "POST", "/api/metrics/reset")
    assert call(server, "GET", "/api/metrics")[1]["requests"] == 0
    call(server, "POST", "/api/telemetry/reset")
    assert call(server, "GET", "/api/telemetry")[1]["total"] == 0


def test_error_translation(server):
    assert call(server, "GET", "/api/nope")[0] == 404
    assert call(server, "POST", "/api/health")[0] == 405
    assert call(server, "POST", "/api/bags/checkin", {})[0] == 400
    assert call(server, "GET", "/api/flights/T1-MISSING")[0] == 404
    assert call(server, "GET", "/api/tag/sequence")[0] == 200


def test_wsgi_callable_serves_json(tmp_path):
    server = make_server(tmp_path, "T9")
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/api/flights",
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(b'{"code":"AA1"}')),
        "wsgi.input": io.BytesIO(b'{"code":"AA1"}'),
    }
    chunks = server(environ, start_response)
    assert captured["status"].startswith("201")
    payload = json.loads(b"".join(chunks))
    assert payload["id"] == "T9-AA1"

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/api/health",
        "QUERY_STRING": "",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    chunks = server(environ, start_response)
    assert captured["status"].startswith("200")
    assert json.loads(b"".join(chunks))["status"] == "ok"


def test_wsgi_rejects_a_bad_body(tmp_path):
    server = make_server(tmp_path, "T8")
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/api/flights",
        "QUERY_STRING": "",
        "CONTENT_LENGTH": "5",
        "wsgi.input": io.BytesIO(b"{bad}"),
    }
    chunks = server(environ, start_response)
    assert captured["status"].startswith("400")
    assert json.loads(b"".join(chunks))["error"]
