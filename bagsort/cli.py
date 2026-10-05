"""Command line entry point for the control service."""

from __future__ import annotations

import argparse
import json
import logging
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from .app import DEFAULT_TERMINAL, Plant
from .clock import Clock
from .console.seed import seed_defaults
from .console.server import Server
from .console.version import version_string
from .demo import invariants_hold, run_demo
from .store.store import Store

LOGGER = logging.getLogger("bagsort")


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """Serve concurrent control requests from a pool of worker threads."""

    daemon_threads = True


def parse_address(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not port.isdigit():
        raise argparse.ArgumentTypeError("address must look like host:port")
    return host or "0.0.0.0", int(port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bagsort", description="line control service")
    parser.add_argument("--state", default="var/state.json", help="journal snapshot path")
    parser.add_argument("--terminal", default=DEFAULT_TERMINAL, help="terminal namespace")
    parser.add_argument("--version", action="store_true", help="print the build version and exit")
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="run the JSON control console")
    serve.add_argument("--addr", default=":8080", help="listen address as host:port")
    serve.add_argument("--seed", action="store_true", help="seed default lanes and flights")
    serve.add_argument("--persist-on-start", action="store_true", help="write a snapshot first")

    demo = commands.add_parser("demo", help="run the deterministic scenario")
    demo.add_argument("--cycles", type=int, default=6, help="bags to check in")
    demo.add_argument("--persist", action="store_true", help="write a snapshot afterwards")

    commands.add_parser("report", help="print the plant report")
    commands.add_parser("status", help="print the store status")
    commands.add_parser("export", help="print audit and sort records as CSV")

    seed = commands.add_parser("seed", help="seed default lanes and flights")
    seed.add_argument("--persist", action="store_true", help="write a snapshot afterwards")

    reset = commands.add_parser("reset", help="clear the journal")
    reset.add_argument("--persist", action="store_true", help="write the empty snapshot")
    return parser


def _load_store(path: str) -> Store:
    return Store.open(path)


def _build(store: Store, terminal: str) -> Plant:
    return Plant.build(store, terminal=terminal, clock=Clock())


def _command_serve(store: Store, plant: Plant, args: argparse.Namespace) -> int:
    if args.seed:
        seed_defaults(plant)
    if args.persist_on_start:
        store.persist()
    host, port = parse_address(args.addr)
    application = Server(plant)
    with make_server(host, port, application, server_class=ThreadingWSGIServer) as httpd:
        LOGGER.info("control console listening on %s:%d", host, port)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("control console stopped")
    if args.seed:
        store.persist()
    return 0


def _command_demo(store: Store, plant: Plant, args: argparse.Namespace) -> int:
    summary = run_demo(plant, cycles=args.cycles)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if args.persist:
        store.persist()
    return 0 if invariants_hold(summary) else 1


def _command_report(plant: Plant) -> int:
    print(plant.report.text(), end="")
    return 0


def _command_status(store: Store, plant: Plant) -> int:
    payload = {
        "path": store.path,
        "watermark": store.watermark,
        "dirty": store.dirty(),
        "audit_intact": plant.audit.verify(),
        "stats": store.stats(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _command_export(plant: Plant) -> int:
    from .reporting import csv_export

    print(csv_export.render(csv_export.AUDIT_COLUMNS, csv_export.audit_rows(plant.audit.entries())))
    return 0


def _command_seed(store: Store, plant: Plant, args: argparse.Namespace) -> int:
    seeded = seed_defaults(plant)
    print(json.dumps(seeded, ensure_ascii=False, sort_keys=True))
    if args.persist:
        store.persist()
    return 0


def _command_reset(store: Store, plant: Plant, args: argparse.Namespace) -> int:
    store.reset()
    if args.persist:
        store.persist()
    print(json.dumps({"status": "reset", "watermark": store.watermark}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(version_string())
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = _load_store(args.state)
    plant = _build(store, args.terminal)

    if args.command in (None, "serve"):
        if args.command is None:
            args.addr = ":8080"
            args.seed = False
            args.persist_on_start = False
        return _command_serve(store, plant, args)
    if args.command == "demo":
        return _command_demo(store, plant, args)
    if args.command == "report":
        return _command_report(plant)
    if args.command == "status":
        return _command_status(store, plant)
    if args.command == "export":
        return _command_export(plant)
    if args.command == "seed":
        return _command_seed(store, plant, args)
    if args.command == "reset":
        return _command_reset(store, plant, args)
    parser.error(f"unknown command {args.command!r}")
    return 2
