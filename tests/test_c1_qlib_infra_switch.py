"""Host delegation and real local production, with optional infra and no live inputs."""

from dataclasses import dataclass
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODULES = (
    "refresh_mydata", "refresh_mydata_1min", "merge_archive_and_csv", "patch_index_data",
    "dump_bin", "stage_1min_from_lake", "build_mydata_1min", "qlib_1min_increment_receipt",
    "stage_etf_daily_from_lake", "build_etf_qlib", "check_dump_bin", "check_data_health",
)
PACKAGE = "myquant_infra.adapters.qlib_data"


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def refuse(*_args, **_kwargs):
        pytest.fail("C1 tests must not connect to the network")

    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "ARROW_NUM_THREADS"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for name in ("OSKH_SOURCE_PARQUET_ROOT", "OSKH_QLIB_CSV_DIR", "OSKH_ETF_DAILY_ROOT",
                 "OSKH_INDEX_DAILY_ROOT", "OSKH_INDEX_1M_ROOT", "OSKH_PERIOD_1M_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))


def load_stub(monkeypatch, name):
    """Load an independent host caller without requiring the optional package."""
    stub = types.ModuleType(PACKAGE + "." + name)

    @dataclass
    class Config:
        pass

    stub.RefreshConfig = stub.BuildConfig = Config
    stub.main = lambda argv=None: 23
    stub.production_operation = object()
    monkeypatch.setitem(sys.modules, stub.__name__, stub)
    module_name = "qlib_scripts._c1_test_" + name
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "qlib_scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module, stub


@pytest.mark.parametrize("name", MODULES)
def test_host_import_delegates_without_optional_dependencies(monkeypatch, name):
    caller, stub = load_stub(monkeypatch, name)
    assert caller.production_operation is stub.production_operation
    assert caller._adapter is stub


@pytest.mark.parametrize("name", MODULES)
def test_missing_optional_pin_is_actionable_and_writes_nothing(tmp_path, name):
    # -S excludes site packages; the empty PYTHONPATH also excludes local infra copies.
    env = dict(os.environ, PYTHONPATH="")
    script = ROOT / "qlib_scripts" / (name + ".py")
    result = subprocess.run([sys.executable, "-S", str(script), "--help"], cwd=tmp_path,
                            env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode != 0
    assert "requirements-infra.txt" in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name,method", [("check_dump_bin", "check"),
                                         ("check_data_health", "check_data")])
def test_checker_legacy_flags_method_and_exit_status(monkeypatch, tmp_path, name, method):
    caller, stub = load_stub(monkeypatch, name)
    calls = []
    stub.main = lambda argv: calls.append(argv) or 17
    path = str(tmp_path / "csv_with_{braces}")
    assert caller.main(["--csv_path=" + path, method]) == 17
    assert calls == [["--csv-path=" + path]]


@pytest.mark.parametrize("name,method", [("check_dump_bin", "check"),
                                         ("check_data_health", "check_data")])
def test_checker_method_name_can_also_be_an_option_value(monkeypatch, name, method):
    caller, stub = load_stub(monkeypatch, name)
    calls = []
    stub.main = lambda argv: calls.append(argv) or 0
    assert caller.main(["--csv_path", method, method]) == 0
    assert calls == [["--csv-path", method]]


@pytest.fixture
def adapters():
    pytest.importorskip(PACKAGE, reason="optional C1 infra pin")
    return {name: importlib.import_module("qlib_scripts." + name) for name in MODULES}


def cli(tmp_path, name, args):
    result = subprocess.run([sys.executable, str(ROOT / "qlib_scripts" / (name + ".py")), *args],
                            cwd=tmp_path, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.mark.parametrize("name", [name for name in MODULES if name != "qlib_1min_increment_receipt"])
def test_direct_cli_help_outside_checkout_requires_no_path_environment(adapters, tmp_path, name):
    assert "usage:" in cli(tmp_path, name, ["--help"]).stdout.lower()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("skip_verify", [False, True])
def test_daily_host_binds_environment_defaults_and_keeps_readback_default(
    adapters, tmp_path, monkeypatch, skip_verify,
):
    caller = adapters["refresh_mydata"]
    lake, csv, provider = [tmp_path / name for name in ("lake", "csv", "daily")]
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    monkeypatch.setenv("OSKH_QLIB_CSV_DIR", str(csv))
    forwarded = []
    monkeypatch.setattr(caller._adapter, "main", lambda argv: forwarded.append(argv) or 19)
    args = ["--archive-dir", str(tmp_path / "archive"), "--qlib-dir", str(provider), "--dry-run"]
    if skip_verify:
        args.append("--skip-verify-patch")
    assert caller.main(args) == 19
    bound = caller._adapter.build_parser().parse_args(forwarded[0])
    assert bound.csv_dir == str(csv)
    assert bound.lake_index_root == str(lake / "index/period=1d/dividend_type=none")
    assert Path(bound.staging_dir).parent == provider.parent
    assert Path(bound.new_qlib_dir).parent == provider.parent
    assert bound.verify_patch is not skip_verify
    assert bound.csv_validator == "qlib_scripts.csv_float_scan:scan_csv_dir"
    assert list(tmp_path.iterdir()) == []


def test_build_minute_skip_stage_needs_no_lake_environment(adapters, monkeypatch, tmp_path):
    caller = adapters["build_mydata_1min"]
    staging, provider, daily = [tmp_path / name for name in ("stage", "minute", "daily")]
    calls = []
    monkeypatch.setattr(caller._adapter, "dump_all_1min", lambda *args: calls.append(args))
    assert caller.main(["--skip-stage", "--staging-dir", str(staging), "--qlib-dir", str(provider),
                        "--daily-dir", str(daily), "--max-workers", "1"]) == 0
    assert calls == [(staging, provider, 1)]
    assert list(tmp_path.iterdir()) == []


def test_host_minute_build_append_and_noop_receipt(adapters, tmp_path):
    import pandas as pd

    lake, provider, staging, daily = [tmp_path / name for name in ("lake", "minute", "stage", "daily")]
    partition = lake / "symbol=000001_SZ"
    partition.mkdir(parents=True)
    (daily / "calendars").mkdir(parents=True)
    daily_calendar = daily / "calendars/day.txt"
    daily_calendar.write_bytes(b"2026-11-02\n")

    def source(count):
        times = pd.date_range("2026-11-02 09:30", periods=count, freq="min")
        pd.DataFrame({"time": times.as_unit("ms").asi8, "close": 10., "volume": 100.,
                      "amount": 100000.}).to_parquet(partition / "data.parquet", index=False)

    source(2)
    base = ["--lake-root", str(lake), "--skip-index", "--qlib-dir", str(provider),
            "--daily-dir", str(daily), "--staging-dir", str(staging), "--max-workers", "1"]
    cli(tmp_path, "build_mydata_1min", base + ["--symbols", "SZ000001"])
    feature = provider / "features/sz000001/close.1min.bin"
    before = feature.read_bytes()
    assert before == struct.pack("<3f", 0, 10, 10)
    source(3)
    source_bytes = (partition / "data.parquet").read_bytes()
    receipt_path = tmp_path / "receipt.json"
    args = base + ["--receipt", str(receipt_path)]
    cli(tmp_path, "refresh_mydata_1min", args)
    assert feature.read_bytes() == before + struct.pack("<f", 10)
    receipt = json.loads(receipt_path.read_text())
    assert receipt["mode"] == "incremental" and receipt["bars_appended"] == 1
    assert receipt["daily_day_txt_unchanged"] is True
    cli(tmp_path, "refresh_mydata_1min", args)
    assert json.loads(receipt_path.read_text())["mode"] == "noop"
    assert feature.read_bytes() == before + struct.pack("<f", 10)
    assert daily_calendar.read_bytes() == b"2026-11-02\n"
    assert (partition / "data.parquet").read_bytes() == source_bytes


def test_host_etf_cli_real_stage_gates_and_dump(adapters, tmp_path):
    import numpy as np

    lake = tmp_path / "fixture_lake"
    shutil.copytree(ROOT / "tests/fixtures/etf_daily_lake", lake)
    before = {p: p.read_bytes() for p in lake.rglob("*.parquet")}
    daily, minute, provider = [tmp_path / name for name in ("daily", "minute", "etf")]
    for path in (daily, minute):
        path.mkdir()
        (path / "KEEP").write_bytes(b"protected")
    cli(tmp_path, "build_etf_qlib", [
        "--lake-root", str(lake / "dividend_type=front"), "--staging-dir", str(tmp_path / "stage"),
        "--qlib-dir", str(provider), "--protected-dir", str(daily), "--protected-dir", str(minute),
        "--skip-verify",
    ])
    assert len((provider / "calendars/day.txt").read_text().splitlines()) == 31
    assert len((provider / "instruments/all.txt").read_text().splitlines()) == 4
    for code in ("sh510300", "sh510050", "sz159915", "sh518880"):
        fields = provider / "features" / code
        np.testing.assert_allclose(np.fromfile(fields / "close.day.bin", dtype="<f4"),
                                   np.fromfile(fields / "vwap.day.bin", dtype="<f4"), equal_nan=True)
    assert {p: p.read_bytes() for p in lake.rglob("*.parquet")} == before
    for path in (daily, minute):
        assert list(path.iterdir()) == [path / "KEEP"]
        assert (path / "KEEP").read_bytes() == b"protected"


def test_host_daily_refresh_real_merge_dump_patch_gates_and_swap(adapters, tmp_path):
    import numpy as np
    import pandas as pd

    archive, csv, lake, provider = [tmp_path / name for name in ("archive", "csv", "index_lake", "daily")]
    (archive / "calendars").mkdir(parents=True)
    (archive / "calendars/day.txt").write_text("2026-10-30\n2026-11-02\n")
    csv.mkdir()
    codes = ["SH600000", "SH600519", "SZ000001"]
    fields = ["open", "high", "low", "close", "volume", "amount", "factor", "vwap", "winratio",
              *["raw" + str(i) for i in range(7)]]
    for code in codes:
        features = archive / "features" / code.lower()
        features.mkdir(parents=True)
        for field in fields:
            values = [0.4, 0.5] if field == "winratio" else [10., 11.]
            (features / (field + ".day.bin")).write_bytes(struct.pack("<3f", 0, *values))
        pd.DataFrame({"date": ["2026-11-02", "2026-11-03"], "close": [11., 12.],
                      "open": [11., 12.]}).to_csv(csv / (code + ".csv"), index=False)
    dates = pd.to_datetime(["2026-10-30", "2026-11-02", "2026-11-03"], utc=True)
    for symbol in ("000001_SH", "000300_SH"):
        partition = lake / ("symbol=" + symbol)
        partition.mkdir(parents=True)
        pd.DataFrame({"time": dates.as_unit("ms").asi8,
                      **{field: [100., 101., 102.] for field in fields[:6]}}).to_parquet(
                          partition / "data.parquet", index=False)
    source_before = {p: p.read_bytes() for root in (archive, csv, lake) for p in root.rglob("*") if p.is_file()}
    (provider / "instruments").mkdir(parents=True)
    (provider / "instruments/all.txt").write_text("\n".join(
        code + "\t2026-10-30\t2026-11-02" for code in codes) + "\n")
    (provider / "KEEP").write_bytes(b"old provider")
    cli(tmp_path, "refresh_mydata", [
        "--archive-dir", str(archive), "--csv-dir", str(csv), "--lake-index-root", str(lake),
        "--qlib-dir", str(provider), "--skip-verify-patch", "--min-dump-free-gb", "0",
        "--min-staging-free-gb", "0",
    ])
    assert {p: p.read_bytes() for p in source_before} == source_before
    backups = list(tmp_path.glob("my_data_backup_*_pre_refresh"))
    assert len(backups) == 1 and (backups[0] / "KEEP").read_bytes() == b"old provider"
    assert (provider / "calendars/day.txt").read_text().splitlines() == [
        "2026-10-30", "2026-11-02", "2026-11-03"]
    np.testing.assert_allclose(np.fromfile(provider / "features/sh600000/winratio.day.bin", dtype="<f4"),
                               [0, 0.4, 0.5, np.nan], equal_nan=True)
    assert {line.split("\t")[0] for line in (provider / "instruments/all.txt").read_text().splitlines()} == set(codes)
    assert (provider / "instruments/index.txt").read_text().splitlines() == [
        "SH000001\t2026-10-30\t2026-11-03", "SH000300\t2026-10-30\t2026-11-03"]
