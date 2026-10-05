"""Build version surfaced by the console and the CLI."""

from __future__ import annotations

from bagsort import __version__

SERVICE_NAME = "line-control-service"
SCHEMA_VERSION = 3


def version_info() -> dict[str, object]:
    return {
        "service": SERVICE_NAME,
        "version": __version__,
        "schema": SCHEMA_VERSION,
        "runtime": "python",
    }


def version_string() -> str:
    return f"{SERVICE_NAME} {__version__} (schema {SCHEMA_VERSION})"
