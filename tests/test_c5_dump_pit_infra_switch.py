"""C5 host delegation and PIT availability contracts; synthetic files only."""

import csv
import importlib
import importlib.util
import os
import socket
import struct
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PACKAGE = "myquant_infra.adapters.qlib_data"
SCRIPT = ROOT / "qlib_scripts/dump_pit.py"
RECORD = struct.Struct("IIdI")
NA = 0xFFFFFFFF


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def refuse(*_args, **_kwargs):
        pytest.fail("C5 tests must not connect to the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "ARROW_NUM_THREADS"):
        monkeypatch.setenv(name, "1")


def test_import_is_stdlib_only_and_never_attempts_backend_or_training(tmp_path):
    code = """
import importlib.abc
import sys
class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'myquant_infra', 'qlib', 'train_wiring', 'pandas', 'fire'}:
            raise AssertionError('unexpected import: ' + fullname)
sys.meta_path.insert(0, Refuse())
from qlib_scripts import dump_pit
assert callable(dump_pit.main)
assert 'DumpPitData' not in vars(dump_pit)
"""
    result = subprocess.run([sys.executable, "-S", "-c", code], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ROOT)), text=True,
                            capture_output=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entry", ["script", "module"])
def test_public_help_without_infra_outside_checkout(tmp_path, entry):
    command = [str(SCRIPT)] if entry == "script" else ["-m", "qlib_scripts.dump_pit"]
    result = subprocess.run([sys.executable, "-S", *command, "--help"], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ROOT)), text=True,
                            capture_output=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "date is availability date" in result.stdout
    assert "--date-column-name" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("feature", ["cli", "class"])
def test_missing_optional_infra_has_install_hint_and_writes_nothing(tmp_path, feature):
    command = [str(SCRIPT), "--csv_path=csv", "--qlib_dir=provider"]
    if feature == "class":
        command = ["-c", "from qlib_scripts.dump_pit import DumpPitData"]
    result = subprocess.run([sys.executable, "-S", *command], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ROOT)), text=True,
                            capture_output=True, timeout=20, check=False)
    assert result.returncode != 0
    assert "InstallError" in result.stderr
    assert "python -m pip install -r requirements-infra.txt" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_class_export_is_lazy_and_is_the_infra_class(monkeypatch):
    from qlib_scripts import _infra_qlib as host

    backend = types.ModuleType(PACKAGE + ".pit")
    backend.DumpPitData = type("DumpPitData", (), {})
    calls = []
    monkeypatch.setattr(host, "adapter", lambda name: calls.append(name) or backend)
    spec = importlib.util.spec_from_file_location("qlib_scripts._c5_test_pit", SCRIPT)
    caller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(caller)
    assert calls == []
    assert caller.DumpPitData is backend.DumpPitData
    assert calls == ["pit"]


@pytest.mark.parametrize("argv,exit_code", [
    (["--help"], 0),
    ([], 2),
    (["--csv-path=csv"], 2),
    (["--qlib-dir=provider"], 2),
    (["--csv-path=csv", "--qlib-dir=provider", "--interval=monthly"], 2),
])
def test_help_and_usage_errors_do_not_load_backend(monkeypatch, argv, exit_code):
    from qlib_scripts import dump_pit

    monkeypatch.setattr(dump_pit.host, "adapter", lambda *_: pytest.fail("loaded backend"))
    with pytest.raises(SystemExit) as exc:
        dump_pit.main(argv)
    assert exc.value.code == exit_code


def test_main_forwards_all_declared_options_and_exit_status(monkeypatch, tmp_path):
    from qlib_scripts import dump_pit

    args = ["--csv_path=" + str(tmp_path / "csv_with_{braces}"),
            "--qlib_dir=" + str(tmp_path / "provider"),
            "--backup_dir=" + str(tmp_path / "backup"), "--interval=annual", "--overwrite",
            "--max_workers=1", "--date_column_name=available_date",
            "--period_column_name=report_period", "--value_column_name=amount",
            "--field_column_name=metric", "--file_suffix=.txt",
            "--include_fields=roe,eps", "--exclude_fields=debt", "--limit_nums=2"]
    forwarded = []
    names = []
    backend = types.SimpleNamespace(main=lambda argv: forwarded.append(argv) or 17)
    monkeypatch.setattr(dump_pit.host, "adapter", lambda name: names.append(name) or backend)
    assert dump_pit.main(args) == 17
    assert names == ["pit"]
    parser = dump_pit.build_parser()
    assert vars(parser.parse_args(forwarded[0])) == vars(parser.parse_args(args))
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def backend():
    return pytest.importorskip(PACKAGE + ".pit", reason="optional C5 requirements-infra.txt pin")


def test_host_parser_matches_pinned_infra(backend):
    from qlib_scripts import dump_pit

    def declarations(parser):
        return [(a.dest, a.option_strings, type(a), a.type, a.nargs, a.required, a.default, a.choices)
                for a in parser._actions]

    cli = importlib.import_module(PACKAGE + ".cli")
    assert declarations(dump_pit.build_parser()) == declarations(cli.pit_parser())
    assert dump_pit.DumpPitData is backend.DumpPitData


def write_source(tmp_path, columns, rows):
    path = tmp_path / "csv" / "SH600000.csv"
    path.parent.mkdir()
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)
    return path


@pytest.mark.parametrize("entry", ["host-cli", "host-class", "infra-cli"])
@pytest.mark.parametrize("interval,period,report_end", [
    ("quarterly", 202401, "2024-03-31"),
    ("annual", 2023, "2023-12-31"),
])
@pytest.mark.parametrize("date_column,first_date", [("date", "2024-05-17"),
                                                    ("available_date", "20240517")])
def test_available_date_survives_report_period_and_revision(
    backend, tmp_path, entry, interval, period, report_end, date_column, first_date,
):
    from qlib_scripts import dump_pit

    # Deliberately out of order. Both publications follow the report end, and
    # the first is an arbitrary caller date rather than an inferred cutoff.
    source = write_source(tmp_path, [date_column, "period", "value", "field", "report_end"], [
        ["2024-06-03", period, 2.5, "roe", report_end],
        [first_date, period, 1.25, "roe", report_end],
    ])
    source_bytes = source.read_bytes()
    provider = tmp_path / "provider"
    args = ["--csv-path", str(source), "--qlib-dir", str(provider), "--max-workers", "1",
            "--interval", interval, "--date-column-name", date_column]
    if entry == "host-class":
        dump_pit.DumpPitData(str(source), str(provider), max_workers=1, freq=interval,
                             date_column_name=date_column).dump()
    elif entry == "host-cli":
        assert dump_pit.main(args) == 0
    else:
        cli = importlib.import_module(PACKAGE + ".cli")
        assert cli.main(["dump-pit", *args]) == 0

    stem = provider / "financial/sh600000" / ("roe_" + interval[0])
    data = stem.with_suffix(".data").read_bytes()
    assert data == (RECORD.pack(20240517, period, 1.25, RECORD.size)
                    + RECORD.pack(20240603, period, 2.5, NA))
    slots = [0, NA, NA, NA] if interval == "quarterly" else [0]
    first_year = period // 100 if interval == "quarterly" else period
    assert stem.with_suffix(".index").read_bytes() == struct.pack("I" * (len(slots) + 1), first_year, *slots)

    # Independent as-of read: report end and the day before availability must
    # yield no value, while each caller-supplied publication unlocks its revision.
    records = list(RECORD.iter_unpack(data))
    def asof(date):
        visible = [value for available, _, value, _ in records if available <= date]
        return visible[-1] if visible else None

    assert asof(int(report_end.replace("-", ""))) is None
    assert asof(20240516) is None
    assert asof(20240517) == 1.25
    assert asof(20240602) == 1.25
    assert asof(20240603) == 2.5
    assert source.read_bytes() == source_bytes


@pytest.mark.parametrize("date_column,available", [("date", None), ("available_date", None),
                                                   ("date", ""), ("available_date", "")])
def test_missing_available_date_never_falls_back_to_report_end_or_period(
    backend, tmp_path, date_column, available,
):
    from qlib_scripts import dump_pit

    columns = ["period", "value", "field", "report_end"]
    row = [202401, 1.0, "roe", "2024-03-31"]
    if available is not None:
        columns.insert(0, date_column)
        row.insert(0, available)
    source = write_source(tmp_path, columns, [row])
    before = source.read_bytes()
    provider = tmp_path / "provider"
    with pytest.raises(ValueError, match="missing PIT columns|availability dates"):
        dump_pit.main(["--csv-path", str(source), "--qlib-dir", str(provider),
                       "--max-workers", "1", "--date-column-name", date_column])
    assert not provider.exists()
    assert source.read_bytes() == before
