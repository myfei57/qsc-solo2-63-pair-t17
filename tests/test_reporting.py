"""Plant report and CSV export."""

from __future__ import annotations

from bagsort.reporting import csv_export
from tests.support import check_in


def test_summary_reports_the_whole_line(plant, flight):
    check_in(plant, flight.id, 2)
    plant.chutes.assign(flight.id, "T1-CHA")
    summary = plant.report.summary()
    assert summary["terminal"] == "T1"
    assert summary["line"][0] == "checkin"
    assert summary["flights"] == 1
    assert summary["open_flights"] == 1
    assert summary["bags"] == 2
    assert summary["active_bags"] == 2
    assert summary["assignments"] == 1
    assert summary["audit_intact"] is True
    assert summary["watermark"] > 0


def test_text_report_lists_every_line(plant, flight):
    check_in(plant, flight.id, 1)
    text = plant.report.text()
    assert "terminal" in text
    assert "handling" not in text  # the line is rendered, not the topology name
    assert "checkin -> tag" in text
    assert text.endswith("\n")


def test_flight_rows_join_flights_and_assignments(plant, flight):
    check_in(plant, flight.id, 2)
    plant.chutes.assign(flight.id, "T1-CHA")
    rows = plant.report.flight_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == flight.id
    assert row["chute_id"] == "T1-CHA"
    assert row["chute_generation"] == 1
    assert row["bags"] == 2
    assert row["state"] == "open"


def test_csv_render_writes_a_header_and_rows():
    text = csv_export.render(["a", "b"], [{"a": 1, "b": 2}, {"a": 3, "b": 4}])
    lines = [line for line in text.splitlines() if line]
    assert lines[0] == "a,b"
    assert lines[1] == "1,2"
    assert lines[2] == "3,4"


def test_row_helpers_project_the_records(plant, flight):
    bag = check_in(plant, flight.id, 1)[0]
    plant.chutes.assign(flight.id, "T1-CHA")
    plant.injector.push(plant.bag(bag.id), "T1-CHA")
    plant.belt.set("T1-CRCR1", 1)
    plant.belt.place(plant.bag(bag.id))
    plant.belt.switch("T1-CRCR2", 2)

    audit_row = csv_export.audit_rows(plant.audit.entries())[0]
    assert set(csv_export.AUDIT_COLUMNS) <= set(audit_row)
    sort_row = csv_export.sort_rows(plant.sorter.records())[0]
    assert sort_row["chute_id"] == "T1-CHA"
    load_row = csv_export.load_rows(plant.belt.loads())[0]
    assert load_row["carousel"] == "T1-CRCR1"
    assert set(csv_export.LOAD_COLUMNS) <= set(load_row)
