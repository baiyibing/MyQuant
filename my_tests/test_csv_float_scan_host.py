"""Host imports, CLI and preflight contracts without a private dependency."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

_CLI = Path(__file__).resolve().parents[1] / "qlib_scripts" / "csv_float_scan.py"
_BACKEND = "myquant_infra.data_validation.csv_float"


@pytest.fixture
def host():
    # An isolated module avoids caching stub exports in other test modules.
    spec = importlib.util.spec_from_file_location("_csv_float_scan_host_test", _CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_infra(monkeypatch):
    for name in ("myquant_infra", "myquant_infra.data_validation", _BACKEND):
        monkeypatch.setitem(sys.modules, name, None)


def test_legacy_imports_delegate_to_infra(host, monkeypatch):
    backend = ModuleType(_BACKEND)
    names = (
        "ILLEGAL_FLOAT_RE", "ILLEGAL_CELL_RE", "PRICE_FIELDS", "ID_COLUMNS",
        "file_has_illegal_float", "inspect_csv_illegal", "scan_csv_dir",
        "summarize_hits_by_column", "format_column_summary", "format_scan_report",
    )
    for name in names:
        setattr(backend, name, object())
    monkeypatch.setitem(sys.modules, _BACKEND, backend)
    for name in names:
        assert getattr(host, name) is getattr(backend, name)


@pytest.mark.parametrize("fatal", [False, True])
def test_script_cli_delegates_and_preserves_exit_status(tmp_path, monkeypatch, capsys, fatal):
    report = {"fatal": [{"file": "bad.csv"}] if fatal else []}
    backend = ModuleType(_BACKEND)
    backend.scan_csv_dir = Mock(return_value=report)
    backend.format_scan_report = Mock(return_value="[csv-scan] stub report")
    monkeypatch.setitem(sys.modules, _BACKEND, backend)
    monkeypatch.setattr(sys, "argv", [str(_CLI), "--csv-dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(_CLI), run_name="__main__")

    assert exc.value.code == (2 if fatal else 0)
    backend.scan_csv_dir.assert_called_once_with(tmp_path)
    backend.format_scan_report.assert_called_once_with(report)
    assert capsys.readouterr().out == "[csv-scan] stub report\n"


@pytest.mark.parametrize("argv,code", [
    (["--help"], 0),
    ([], 2),
    (["--csv-dir", ".", "--fatal-columns", "close"], 2),
])
def test_cli_parser_works_without_infra(no_infra, monkeypatch, capsys, argv, code):
    monkeypatch.setattr(sys, "argv", [str(_CLI), *argv])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(_CLI), run_name="__main__")
    assert exc.value.code == code
    output = capsys.readouterr()
    assert "--csv-dir" in (output.out if code == 0 else output.err)


def test_missing_infra_fails_with_install_guidance(host, no_infra, tmp_path):
    with pytest.raises(ModuleNotFoundError, match="optional pinned") as exc:
        host.main(["--csv-dir", str(tmp_path)])
    assert "docs/engineering/c2-csv-float-infra-switch-20261105.md" in str(exc.value)
    with pytest.raises(ModuleNotFoundError):
        host.scan_csv_dir(tmp_path)
    with pytest.raises(AttributeError):
        host.unknown_export


def test_backend_dependency_failure_is_not_relabelled(host, monkeypatch, tmp_path):
    missing_dependency = ModuleNotFoundError("missing backend dependency", name="pandas")
    monkeypatch.setattr(host, "import_module", Mock(side_effect=missing_dependency))
    with pytest.raises(ModuleNotFoundError) as exc:
        host.main(["--csv-dir", str(tmp_path)])
    assert exc.value is missing_dependency


@pytest.mark.parametrize("fatal", [False, True])
def test_refresh_preflight_uses_infra_report(tmp_path, monkeypatch, capsys, fatal):
    import refresh_mydata as refresh

    hit = {"file": "fixture.csv"}
    report = {"fatal": [hit] if fatal else [], "warn": [] if fatal else [hit]}
    backend = ModuleType(_BACKEND)
    backend.scan_csv_dir = Mock(return_value=report)
    backend.format_scan_report = Mock(return_value="[csv-scan] preflight report")
    monkeypatch.setitem(sys.modules, _BACKEND, backend)
    cfg = refresh.RefreshConfig(csv_dir=tmp_path)

    if fatal:
        with pytest.raises(refresh.RefreshError, match="OHLC.*fixture.csv"):
            refresh.run_csv_scan_preflight(cfg)
    else:
        assert refresh.run_csv_scan_preflight(cfg) is report

    backend.scan_csv_dir.assert_called_once_with(tmp_path)
    backend.format_scan_report.assert_called_once_with(report)
    assert capsys.readouterr().out == "[csv-scan] preflight report\n"


@pytest.mark.parametrize("skip", ["skip_merge", "skip_csv_scan"])
def test_skipped_preflight_does_not_require_infra(no_infra, skip):
    import refresh_mydata as refresh

    assert refresh.run_csv_scan_preflight(refresh.RefreshConfig(**{skip: True})) is None
