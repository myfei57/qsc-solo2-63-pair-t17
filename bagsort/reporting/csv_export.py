"""CSV rendering used by the export endpoints."""

from __future__ import annotations

import csv
import io
from typing import Iterable, Sequence


def render(columns: Sequence[str], rows: Iterable[dict[str, object]]) -> str:
    """Render a header plus one line per row, in the column order given."""

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


def audit_rows(entries: Iterable[object]) -> list[dict[str, object]]:
    return [
        {
            "sequence": entry.sequence,
            "kind": entry.kind,
            "subject": entry.subject,
            "stage": entry.detail.get("stage", ""),
            "at": entry.at,
            "digest": entry.digest,
        }
        for entry in entries
    ]


def sort_rows(records: Iterable[object]) -> list[dict[str, object]]:
    return [
        {
            "bag_id": record.bag_id,
            "flight_id": record.flight_id,
            "chute_id": record.chute_id,
            "sequence": record.sequence,
            "epoch": record.epoch,
            "at": record.at,
        }
        for record in records
    ]


def load_rows(records: Iterable[object]) -> list[dict[str, object]]:
    return [
        {
            "bag_id": record.bag_id,
            "carousel": record.carousel,
            "batch": record.batch,
            "at": record.at,
        }
        for record in records
    ]


AUDIT_COLUMNS = ("sequence", "kind", "subject", "stage", "at", "digest")
SORT_COLUMNS = ("bag_id", "flight_id", "chute_id", "sequence", "epoch", "at")
LOAD_COLUMNS = ("bag_id", "carousel", "batch", "at")
