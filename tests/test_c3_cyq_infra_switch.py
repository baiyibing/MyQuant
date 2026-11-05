"""Thin-host delegation and synthetic CYQ builds; no private infra in public CI."""

from importlib import import_module
import os
from pathlib import Path
import socket
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from my_scripts import build_winner_ratio as host


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def refuse(*_args, **_kwargs):
        pytest.fail("C3 tests must not connect to the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "unused-home"))
    monkeypatch.delenv("OSKH_SOURCE_PARQUET_ROOT", raising=False)


def arguments(tmp_path, *extra):
    return ["--provider-uri", str(tmp_path / "provider"), "--test", "2026-01-19:2026-01-20",
            "--out", str(tmp_path / "output/daily.parquet"), "--workers", "1", *extra]


def public_process(tmp_path, code):
    return subprocess.run(
        [sys.executable, "-S", "-c", "import sys; sys.path.insert(0, " + repr(str(ROOT)) + "); " + code],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=""), text=True,
        capture_output=True, timeout=20,
    )


@pytest.mark.parametrize("module", ["my_scripts.build_winner_ratio", "build_winner_ratio"])
def test_public_import_and_introspection_are_stdlib_only(tmp_path, module):
    result = public_process(tmp_path,
        "sys.path.append(" + repr(str(ROOT / "my_scripts")) + "); "
        "import importlib; m = importlib.import_module(" + repr(module) + "); "
        "assert not hasattr(m, '__path__'); "
        "assert not hasattr(m, 'unknown_attribute'); "
        "assert not any(n.startswith(('myquant_infra', 'qlib', 'numpy', 'pandas', 'train_wiring')) "
        "for n in sys.modules)")
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("style", ["script", "module"])
def test_public_help_without_infra(tmp_path, style):
    target = str(ROOT / "my_scripts/build_winner_ratio.py") if style == "script" else "my_scripts.build_winner_ratio"
    run = "runpy.run_path(" + repr(target) + ", run_name='__main__')" if style == "script" else (
        "runpy.run_module(" + repr(target) + ", run_name='__main__')")
    result = public_process(tmp_path, "import runpy; sys.argv = ['build_winner_ratio', '--help']; " + run)
    assert result.returncode == 0, result.stderr
    assert all(option in result.stdout for option in ("--provider-uri", "--out", "--output-root", "--shares"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("export", ["FeederConfig", "compute_winner_ratio", "run", "NoOutputError",
                                    "_triang_into", "_stock_winner_ratio_impl"])
def test_feature_use_without_infra_has_install_hint(tmp_path, export):
    result = public_process(tmp_path,
        "from my_scripts import build_winner_ratio as m; getattr(m, " + repr(export) + ")")
    assert result.returncode != 0
    assert "InstallError" in result.stderr and "requirements-infra.txt" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_without_infra_fails_before_writes(tmp_path):
    result = public_process(tmp_path,
        "from my_scripts.build_winner_ratio import main; raise SystemExit(main("
        + repr(arguments(tmp_path)) + "))")
    assert result.returncode == 2
    assert "pip install -r requirements-infra.txt" in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args, message", [
    (["--test", "2026-01-01:2026-01-02", "--out", "unused"], "--provider-uri"),
    (["--test", "2026-01-01:2026-01-02", "--provider-uri", "unused"], "--output-root"),
    (["--test", "2026-01-01:2026-01-02", "--provider-uri", "unused", "--out", "x", "--output-root", "y"], "not allowed"),
])
def test_explicit_paths_required_before_backend_load(tmp_path, args, message):
    result = public_process(tmp_path,
        "from my_scripts.build_winner_ratio import main; raise SystemExit(main(" + repr(args) + "))")
    assert result.returncode == 2 and message in result.stderr
    assert "requirements-infra.txt" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_main_delegates_all_arguments_and_exit_code(monkeypatch, tmp_path):
    calls = []
    argv = arguments(tmp_path, "--window", "33", "--step", "0.02", "--shares", "circ",
                     "--codes", "sh600000,SZ000001", "--kernels", "2")
    def load(name):
        assert name == "myquant_infra.derived_data.cyq.cli"
        return types.SimpleNamespace(main=lambda args: calls.append(args) or 3)
    monkeypatch.setattr(host, "import_module", load)
    assert host.main(argv) == 3
    assert calls == [argv]
    assert list(tmp_path.iterdir()) == []


def test_unrelated_import_error_keeps_dependency_name(monkeypatch):
    def load(_name):
        raise ModuleNotFoundError("missing numpy", name="numpy")
    monkeypatch.setattr(host, "import_module", load)
    with pytest.raises(ModuleNotFoundError) as caught:
        host.compute_winner_ratio
    assert type(caught.value) is ModuleNotFoundError and caught.value.name == "numpy"


@pytest.fixture
def infra():
    return pytest.importorskip("myquant_infra.derived_data.cyq")


def test_cli_matches_pinned_infra(infra):
    cli = import_module(infra.__name__ + ".cli")
    def signature(parser):
        return [(a.dest, a.option_strings, a.default, a.required, a.type, a.choices, a.nargs)
                for a in parser._actions]
    assert signature(host.build_parser()) == signature(cli.build_parser())
    assert [(g.required, [a.dest for a in g._group_actions]) for g in host.build_parser()._mutually_exclusive_groups] == [
        (g.required, [a.dest for a in g._group_actions]) for g in cli.build_parser()._mutually_exclusive_groups]


@pytest.mark.parametrize("export", list(host._EXPORTS))
def test_compatibility_symbols_are_actual_infra_objects(infra, export):
    backend = import_module(infra.__name__ + host._EXPORTS[export])
    assert getattr(host, export) is getattr(backend, export)


@pytest.fixture
def synthetic_provider(infra, monkeypatch, tmp_path):
    pd = pytest.importorskip("pandas")
    kernel = import_module(infra.__name__ + "._kernel")
    # Keep these host integration tests deterministic and avoid JIT cache writes.
    monkeypatch.setitem(kernel._work_one_state, "jit", True)
    dates = pd.bdate_range("2026-01-05", periods=12)
    frame = pd.DataFrame({
        "$close": [20.] * 11 + [10.], "$high": [20.] * 11 + [10.],
        "$low": [20.] * 11 + [10.], "$adjclose": [10.] * 12,
        "$amount": [10000.] * 12, "$netcsfree": [20000.] * 12,
        "$basiccurhold": [1.] * 12,
    }, index=pd.MultiIndex.from_product([["SH600000"], dates], names=["instrument", "datetime"]))
    requests = []
    class Provider:
        def calendar(self):
            return dates
        def instruments(self, market):
            assert market == "all"
            return "synthetic-all"
        def list_instruments(self, instruments, *, start_time, end_time, as_list):
            assert instruments == "synthetic-all" and as_list
            requests.append(("membership", start_time, end_time))
            return ["SH600000"]
        def features(self, instruments, fields, *, start_time, end_time):
            assert instruments == ["SH600000"]
            requests.append(("features", tuple(fields), start_time, end_time))
            mask = (dates >= start_time) & (dates <= end_time)
            return frame.loc[mask, fields].copy()
    root = tmp_path / "provider"
    root.mkdir()
    sentinel = root / "source.bin"
    sentinel.write_bytes(b"unchanged-provider")
    provider = Provider()
    feeder = import_module(infra.__name__ + ".feeder")
    opened = []
    def open_provider(path, *, kernels):
        assert Path(path) == root
        opened.append(kernels)
        return provider
    monkeypatch.setattr(feeder, "open_local_provider", open_provider)
    return provider, requests, opened, sentinel


@pytest.mark.parametrize("shares, turnover", [("free", 0.05), ("circ", 0.1)])
def test_cli_runs_real_feeder_and_replaces_whole_table(synthetic_provider, monkeypatch, tmp_path, shares, turnover):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    provider, requests, opened, sentinel = synthetic_provider
    output = tmp_path / "output/daily.parquet"
    output.parent.mkdir()
    pd.DataFrame({"old": [999]}).to_parquet(output, index=False)
    before = output.read_bytes()
    feeder = import_module("myquant_infra.derived_data.cyq.feeder")
    replace = feeder.os.replace
    publications = []
    def publish(src, dst):
        assert src == output.with_suffix(".tmp.parquet") and dst == output
        assert dst.read_bytes() == before
        assert pd.read_parquet(src).columns.tolist() == ["stock_code", "date", "winner_ratio"]
        publications.append((src, dst))
        replace(src, dst)
    monkeypatch.setattr(feeder.os, "replace", publish)
    monkeypatch.setenv("QLIB_KERNELS", "99")
    assert host.main(arguments(tmp_path, "--shares", shares, "--codes", "sh600000", "--kernels", "2")) == 0
    got = pd.read_parquet(output)
    assert got.stock_code.tolist() == ["SH600000", "SH600000"]
    assert got.date.tolist() == list(pd.to_datetime(["2026-01-19", "2026-01-20"]))
    assert got.winner_ratio.dtype == "float64"
    assert got.winner_ratio.tolist() == pytest.approx([1., turnover / (1 - (1 - turnover) ** 12)])
    assert requests[-1][2] == pd.Timestamp("2026-01-05")  # default warmup reaches calendar start
    assert "$volume" not in requests[-1][1]
    assert ("$basiccurhold" in requests[-1][1]) == (shares == "circ")
    assert "$netcsfree" in requests[-1][1]
    assert opened == [2] and len(publications) == 1
    assert not output.with_suffix(".tmp.parquet").exists()
    assert sentinel.read_bytes() == b"unchanged-provider"


@pytest.mark.parametrize("case, expected", [("short", 3), ("code", 2), ("step", 2), ("overlap", 2), ("write", 2)])
def test_failed_cli_preserves_output(synthetic_provider, monkeypatch, tmp_path, case, expected):
    provider, requests, opened, sentinel = synthetic_provider
    output = tmp_path / "output/daily.parquet"
    output.parent.mkdir()
    output.write_bytes(b"prior-output")
    extras = {"short": ["--window", "0"], "code": ["--codes", "SZ999999"],
              "step": ["--step", "0"], "overlap": ["--out", str(sentinel)], "write": []}[case]
    if case == "write":
        pd = pytest.importorskip("pandas")
        def fail(*_args, **_kwargs):
            raise OSError("synthetic publication failure")
        monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    if case in {"step", "overlap"}:
        with pytest.raises(SystemExit) as caught:
            host.main(arguments(tmp_path, *extras))
        assert caught.value.code == expected
        assert opened == []
    else:
        assert host.main(arguments(tmp_path, *extras)) == expected
    assert output.read_bytes() == b"prior-output"
    assert sentinel.read_bytes() == b"unchanged-provider"


def test_output_root_and_library_delegation(synthetic_provider, tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    provider, requests, opened, sentinel = synthetic_provider
    root = tmp_path / "derived"
    argv = ["--provider-uri", str(sentinel.parent), "--test", "2026-01-19:2026-01-20",
            "--output-root", str(root), "--workers", "1"]
    assert host.main(argv) == 0
    output = root / "cyq_winner_ratio/cyq_winner_ratio_daily_2026.parquet"
    config = host.FeederConfig(provider_uri=sentinel.parent, start="2026-01-20", end="2026-01-20",
                               output_file=output, workers=1)
    assert host.run(config, provider=provider) == output
    assert len(pd.read_parquet(output)) == 1
    got = host.compute_winner_ratio(provider, start=config.start, end=config.end, workers=1)
    pd.testing.assert_frame_equal(pd.read_parquet(output), got)
    assert opened == [1]  # injection uses the existing port without reopening qlib
