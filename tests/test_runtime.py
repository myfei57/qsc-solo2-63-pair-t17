"""Command line entry point."""

from __future__ import annotations

import argparse
import json

import pytest

from bagsort.cli import build_parser, main, parse_address
from bagsort.console.version import version_string


def test_version_flag_prints_the_build(capsys):
    assert main(["--version"]) == 0
    assert version_string() in capsys.readouterr().out


def test_parse_address_accepts_host_and_port():
    assert parse_address("127.0.0.1:9000") == ("127.0.0.1", 9000)
    assert parse_address(":8081") == ("0.0.0.0", 8081)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_address("bad")


def test_build_parser_lists_every_command():
    parser = build_parser()
    actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    assert actions, "expected subcommands"
    names = set(actions[0].choices)
    assert {"serve", "demo", "report", "status", "export", "seed", "reset"} <= names


def test_demo_command_reports_the_summary(tmp_path, capsys):
    state = tmp_path / "state.json"
    assert main(["--state", str(state), "demo", "--cycles", "3"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["sorted"] == 3
    assert summary["audit_intact"] is True


def test_seed_status_and_report_commands(tmp_path, capsys):
    state = tmp_path / "state.json"
    assert main(["--state", str(state), "seed", "--persist"]) == 0
    seeded = json.loads(capsys.readouterr().out)
    assert seeded["flights"] == ["T1-CA1234", "T1-MU5678"]

    assert main(["--state", str(state), "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["stats"]["flights"] == 2
    assert status["audit_intact"] is True

    assert main(["--state", str(state), "report"]) == 0
    assert "terminal" in capsys.readouterr().out


def test_export_and_reset_commands(tmp_path, capsys):
    state = tmp_path / "state.json"
    main(["--state", str(state), "demo", "--cycles", "2", "--persist"])
    capsys.readouterr()
    assert main(["--state", str(state), "export"]) == 0
    assert capsys.readouterr().out.startswith("sequence,kind,subject")

    assert main(["--state", str(state), "reset", "--persist"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "reset", "watermark": 0}
