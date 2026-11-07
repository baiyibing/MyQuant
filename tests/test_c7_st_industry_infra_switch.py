"""C7 optional imports, pinned reader parity, and host ST/path compatibility."""

from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import ModuleType

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from my_scripts import data_root as roots, st_status as host  # noqa: E402

PIN = "3c377e9718e811112993579b6d91a603395db699"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("C7 tests must not connect to the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def infra():
    return pytest.importorskip("myquant_infra.reference_data.st.readers", reason="optional C7 infra pin")


@pytest.fixture
def lake_paths():
    return pytest.importorskip("myquant_infra.lake.paths", reason="optional C7 infra pin")


@pytest.fixture
def daily(tmp_path):
    path = tmp_path / "st_daily.parquet"
    pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-01-08", "2026-01-06", "2026-01-06"]),
        "code": ["920305.BJ", "000615.SZ", "600000.SH"],
        "is_st": [True, True, False],
    }).to_parquet(path, index=False)
    return path


def run_isolated(code, tmp_path):
    prefix = f"import sys; sys.path[:0] = {[str(ROOT), str(ROOT / 'my_scripts')]!r}\n"
    prefix += '''
import socket
def refuse(*args, **kwargs):
    raise AssertionError("C7 subprocess must not connect to the network")
socket.socket.connect = socket.create_connection = refuse
'''
    result = subprocess.run(
        [sys.executable, "-S", "-c", prefix + code], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1"),
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("module", ["st_status", "my_scripts.st_status", "data_root", "my_scripts.data_root"])
def test_public_import_does_not_attempt_infra_or_host_policy(module, tmp_path):
    run_isolated(f'''
import importlib
import importlib.abc
class RefuseOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {{"myquant_infra", "train_wiring", "qlib", "pandas"}}:
            raise AssertionError("Public import attempted " + fullname)
sys.meta_path.insert(0, RefuseOptional())
host = importlib.import_module({module!r})
names = (["to_wind_code", "to_qlib_code", "load_st_daily_index", "load_st_codes_asof",
          "coverage_fallback_qlib"] if "st_status" in {module!r} else
         ["DataRootError", "resolve_parquet_container", "resolve_st_daily", "resolve_sw_l1_map"])
for name in names:
    getattr(host, name)
''', tmp_path)


@pytest.mark.parametrize("module,operations", [
    ("st_status", ["host.to_wind_code('SH600000')", "host.to_qlib_code('600000.SH')",
                   "host.load_st_daily_index('missing')", "host.load_st_codes_asof('missing')",
                   "host.load_st_codes_asof('missing', '2026-01-08')"]),
    ("data_root", ["host.resolve_st_daily(must_exist=False)", "host.resolve_sw_l1_root()",
                   "host.resolve_sw_l1_map()", "host.resolve_sw_l1_map(explicit_root='map.csv')"]),
])
def test_missing_infra_fails_before_io_with_pin_and_install_hint(module, operations, tmp_path):
    run_isolated(f'''
import importlib
import os
os.environ["OSKH_SOURCE_PARQUET_ROOT"] = "unused-lake"
host = importlib.import_module({module!r})
for operation in {operations!r}:
    try:
        eval(operation)
    except ModuleNotFoundError as exc:
        assert "python -m pip install -r requirements-infra.txt" in str(exc)
        assert {PIN!r} in str(exc)
    else:
        raise AssertionError("Expected install hint: " + operation)
''', tmp_path)


@pytest.mark.parametrize("module", [host, roots])
def test_unrelated_missing_dependencies_keep_their_identity(monkeypatch, module):
    missing = ModuleNotFoundError("missing parquet dependency", name="other_backend")

    def fail(name):
        raise missing

    monkeypatch.setattr(module, "import_module", fail)
    with pytest.raises(ModuleNotFoundError) as caught:
        module._infra()
    assert caught.value is missing


@pytest.mark.parametrize("code", [
    "SH600000", " sz000001 ", "BJ920305", "600000.SH", "000001.sz", "920305.bj",
    "000001", "unknown", "", "SHodd",
])
def test_code_conversion_matches_pin(infra, code):
    assert host.to_wind_code(code) == infra.to_wind_code(code)
    assert host.to_qlib_code(code) == infra.to_qlib_code(code)


@pytest.mark.parametrize("asof,expected", [
    ("2026-01-05", set()), ("2026-01-06", {"SZ000615"}),
    (date(2026, 1, 7), {"SZ000615"}), ("2026-01-08", {"BJ920305"}),
    (pd.Timestamp("2026-01-09 12:30"), {"BJ920305"}),
])
def test_explicit_asof_and_index_match_pin(infra, daily, asof, expected):
    before = daily.read_bytes()
    assert host.load_st_daily_index(daily) == infra.load_st_daily_index(daily)
    assert host.load_st_codes_asof(daily, asof) == infra.load_st_codes_asof(daily, asof) == expected
    assert daily.read_bytes() == before


def test_default_asof_passes_last_host_day_explicitly(infra, daily, monkeypatch):
    by_date, _ = host.load_st_daily_index(daily)
    last = sorted(by_date)[-1]
    expected = infra.load_st_codes_asof(daily, last)
    original = infra.load_st_codes_asof
    calls = []

    def observe(path, asof):
        assert asof is not None
        calls.append((path, asof))
        return original(path, asof)

    monkeypatch.setattr(infra, "load_st_codes_asof", observe)
    assert host.load_st_codes_asof(daily, None) == expected == {"BJ920305"}
    assert calls == [(daily, last)]
    with pytest.raises(ValueError, match="explicit ST asof"):
        original(daily, None)


def test_dense_false_days_preserve_host_hit_only_observation_rule(infra, tmp_path):
    path = tmp_path / "dense.parquet"
    pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-01-06", "2026-01-07", "2026-01-08"]),
        "code": ["000615.SZ"] * 3, "is_st": [True, False, False],
    }).to_parquet(path, index=False)
    assert infra.load_st_daily_index(path)[0][date(2026, 1, 8)] == set()
    assert host.load_st_daily_index(path) == ({date(2026, 1, 6): {"SZ000615"}}, set())
    assert infra.load_st_codes_asof(path, "2026-01-08") == set()
    assert host.load_st_codes_asof(path, "2026-01-08") == {"SZ000615"}
    assert host.load_st_codes_asof(path) == {"SZ000615"}


def test_eligibility_consumer_keeps_host_dates_and_ignores_coverage(infra, daily, monkeypatch):
    # Exercise the existing file consumer without loading Qlib/the strategy.
    qlib = ModuleType("qlib")
    data = ModuleType("qlib.data")
    data.D = object()
    strategy = ModuleType("custom_strategy")
    strategy.TopkDropoutStrategyWithFilter = type("StrategyBase", (), {})
    for name, module in {"qlib": qlib, "qlib.data": data, "custom_strategy": strategy,
                         "st_status": host}.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("_c7_eligibility", ROOT / "my_scripts/buy_eligibility.py")
    consumer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consumer)
    frame = pd.read_parquet(daily)
    frame.loc[len(frame)] = [pd.Timestamp("2026-01-09"), "920305.BJ", False]
    frame.to_parquet(daily, index=False)
    daily.with_name("st_coverage.json").write_text("invalid JSON must not be read", encoding="utf-8")
    gate = consumer.BuyEligibilityFilter(st_codes={"SH688999"}, st_daily_file=daily)
    assert gate.st_codes_of_date("2026-01-05") == set()
    assert gate.st_codes_of_date("2026-01-07") == {"SZ000615"}
    assert gate.st_codes_of_date("2026-01-09") == {"BJ920305"}
    assert gate.st_fallback == set()


@pytest.mark.parametrize("rows", [0, 1])
def test_empty_or_all_false_matrix_has_no_default_hits(infra, tmp_path, rows):
    path = tmp_path / "empty.parquet"
    pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-01-08"] * rows),
        "code": ["000615.SZ"] * rows, "is_st": [False] * rows,
    }).to_parquet(path, index=False)
    assert host.load_st_daily_index(path) == ({}, set())
    assert host.load_st_codes_asof(path) == set()
    assert host.load_st_codes_asof(path, "2026-01-08") == set()


def test_default_readers_ignore_coverage_and_static_inputs(infra, daily):
    coverage = daily.with_name("st_coverage.json")
    coverage.write_text("invalid JSON must not be read", encoding="utf-8")
    assert host.load_st_daily_index(daily, coverage, {"SH688999"})[1] == set()
    assert host.load_st_codes_asof(daily, None, coverage, {"SH688999"}) == {"BJ920305"}


def test_coverage_branch_is_wholly_host_local(monkeypatch, daily):
    def refuse(name):
        raise AssertionError("host coverage fallback must not import infra")

    monkeypatch.setattr(host, "import_module", refuse)
    coverage = {
        "harvested_wind_codes": ["000615.SZ", "000504.SZ"],
        "unknown_end_wind_codes": ["000504.SZ"],
        "snapshot_fallback_wind_codes": ["603825.SH"],
    }
    static = {"SZ000615", "sz000504", "SH688999"}
    expected = {"SZ000504", "SH688999", "SH603825"}
    path = daily.with_name("st_coverage.json")
    path.write_text(json.dumps(coverage), encoding="utf-8")
    assert host.coverage_fallback_qlib(coverage, static) == expected
    assert host.coverage_fallback_qlib({}, static) == {c.upper() for c in static}
    assert host.load_st_daily_index(daily, fallback_static=static, use_coverage=True) == (
        {date(2026, 1, 6): {"SZ000615"}, date(2026, 1, 8): {"BJ920305"}}, expected,
    )
    path.unlink()
    assert host.load_st_daily_index(daily, fallback_static=static, use_coverage=True)[1] == {
        c.upper() for c in static
    }


@pytest.mark.parametrize("resolver", [
    roots.resolve_parquet_container, roots.resolve_st_daily, roots.resolve_sw_l1_root,
    roots.resolve_sw_l1_map, roots.resolve_qlib_csv_dir, roots.resolve_period_root,
    roots.resolve_index_daily_root, roots.resolve_index_minute_root, roots.resolve_etf_daily_root,
])
def test_unset_env_raises_host_error_before_infra(monkeypatch, resolver):
    for name in list(os.environ):
        if name.startswith("OSKH_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OSKH_DATA_ROOT", "/unused/workspace-not-a-lake")
    monkeypatch.setattr(roots, "import_module", lambda name: pytest.fail("env must resolve first"))
    with pytest.raises(roots.DataRootError, match="OSKH_"):
        resolver("1m") if resolver is roots.resolve_period_root else resolver()


def test_st_and_industry_paths_match_pin_and_keep_host_file_errors(lake_paths, monkeypatch, tmp_path):
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(tmp_path))
    assert roots.resolve_parquet_container() == tmp_path
    assert roots.resolve_st_daily(must_exist=False) == lake_paths.st_daily_path(tmp_path, must_exist=False)
    assert roots.resolve_sw_l1_root() == lake_paths.sw_l1_root(tmp_path)
    with pytest.raises(roots.DataRootError, match="ST 日表"):
        roots.resolve_st_daily()
    root = roots.resolve_sw_l1_root()
    root.mkdir()
    (root / "wind_l1_map.csv").write_text("unrelated", encoding="utf-8")
    with pytest.raises(roots.DataRootError, match="sw_l1_map.csv"):
        roots.resolve_sw_l1_map()
    path = root / "sw_l1_map.csv"
    path.write_text("code_qlib,sw_l1\nSH600000,银行\n", encoding="utf-8")
    assert roots.resolve_sw_l1_map() == lake_paths.sw_l1_map_path(tmp_path) == path
    monkeypatch.delenv("OSKH_SOURCE_PARQUET_ROOT")
    assert roots.resolve_sw_l1_map(explicit_root=path) == path
    with pytest.raises(roots.DataRootError, match="行业映射"):
        roots.resolve_sw_l1_map(explicit_root=tmp_path / "missing.csv")
