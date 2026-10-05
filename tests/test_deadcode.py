"""The dead code and reachability gate itself."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_gate():
    spec = importlib.util.spec_from_file_location("deadcode", ROOT / "tools" / "deadcode.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_gate_passes_on_the_shipped_package():
    report = _load_gate().analyze(str(ROOT / "bagsort"))
    assert report["ok"] is True, json.dumps(report, ensure_ascii=False)
    assert report["unused_symbols"] == []
    assert report["unreachable_modules"] == []
    assert report["files"] > 50
    assert report["symbols"] > 300


def test_gate_flags_an_unreferenced_symbol(tmp_path):
    package = tmp_path / "probe"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(
        "from probe.mod import used\n\nused()\n", encoding="utf-8"
    )
    (package / "mod.py").write_text(
        "def used():\n    return 1\n\n\ndef orphan():\n    return 2\n",
        encoding="utf-8",
    )
    report = _load_gate().analyze(str(package))
    assert report["ok"] is False
    assert [item["name"] for item in report["unused_symbols"]] == ["orphan"]


def test_gate_flags_an_unreachable_module(tmp_path):
    package = tmp_path / "probe"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text("print('hi')\n", encoding="utf-8")
    (package / "island.py").write_text("def lonely():\n    return 1\n", encoding="utf-8")
    report = _load_gate().analyze(str(package))
    assert "probe.island" in report["unreachable_modules"]
