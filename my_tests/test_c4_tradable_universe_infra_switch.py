"""C4 host policy injection and optional infra IO, using only temporary inputs."""

import builtins
import os
from pathlib import Path
import socket
import subprocess
import sys
import textwrap
import types

import pytest

import build_tradable_universe as host

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "my_scripts" / "build_tradable_universe.py"
PACKAGE = "myquant_infra.adapters.qlib_data.universe"
ASOF = "2026-01-08"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*_args, **_kwargs):
        pytest.fail("C4 tests must not connect to the network or discover a home provider")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(Path, "home", classmethod(refuse))


def python(tmp_path, *args, stdlib=False):
    env = dict(os.environ)
    if stdlib:
        env["PYTHONPATH"] = ""
    return subprocess.run(
        [sys.executable, *(["-S"] if stdlib else []), *args],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30,
    )


def test_public_import_never_loads_optional_or_host_policy(tmp_path):
    code = f"""
        import importlib.abc
        import sys
        class BlockOptional(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, *args):
                if fullname.split('.')[0] in {{'myquant_infra', 'train_wiring', 'buy_eligibility',
                                               'st_status', 'qlib', 'pandas'}}:
                    raise AssertionError('unexpected import: ' + fullname)
        sys.meta_path.insert(0, BlockOptional())
        sys.path.insert(0, {str(SCRIPT.parent)!r})
        import build_tradable_universe
    """
    result = python(tmp_path, "-c", textwrap.dedent(code), stdlib=True)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_public_help_without_site_packages(tmp_path):
    result = python(tmp_path, str(SCRIPT), "--help", stdlib=True)
    assert result.returncode == 0, result.stderr
    for option in ("--qlib-dir", "--calendar", "--asof", "--st-asof", "--age-days"):
        assert option in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("omit", ["--qlib-dir", "--calendar", "--asof"])
def test_cli_requires_explicit_inputs_without_loading_infra(tmp_path, omit):
    options = {"--qlib-dir": "provider", "--calendar": "day.txt", "--asof": ASOF}
    argv = [item for key, value in options.items() if key != omit for item in (key, value)]
    result = python(tmp_path, str(SCRIPT), *argv, stdlib=True)
    assert result.returncode == 2
    assert omit in result.stderr
    assert "InstallError" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_invalid_snapshot_before_loading_policy(tmp_path):
    result = python(tmp_path, str(SCRIPT), "--qlib-dir", "provider", "--calendar", "day.txt",
                    "--asof", "not-a-date", stdlib=True)
    assert result.returncode == 2
    assert "--asof" in result.stderr
    assert "InstallError" not in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("call", [
    "host.read_calendar('day.txt')",
    "host.drop_excluded([], set())",
    "host.shift_start_for_age([], [], 0)",
    "host.build('provider', exclusions=set(), age_days=0, calendar=[], asof='2026-01-08')",
    "host.main(['--qlib-dir', 'provider', '--calendar', 'day.txt', '--asof', '2026-01-08'])",
])
def test_feature_use_without_infra_has_install_hint_and_no_writes(tmp_path, call):
    code = f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); import build_tradable_universe as host; {call}"
    result = python(tmp_path, "-c", code, stdlib=True)
    assert result.returncode != 0
    assert "InstallError" in result.stderr
    assert "python -m pip install -r requirements-infra.txt" in result.stderr
    assert "train_wiring" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_missing_backend_dependency_is_not_relabelled(monkeypatch):
    error = ModuleNotFoundError("missing backend dependency", name="pandas")

    def fail(_name):
        raise error

    monkeypatch.setattr(host, "import_module", fail)
    with pytest.raises(ModuleNotFoundError) as exc:
        host.read_calendar("day.txt")
    assert exc.value is error


def test_generic_wrappers_forward_inputs_without_loading_host_policy(monkeypatch, tmp_path):
    calls = []
    backend = types.SimpleNamespace()
    results = {name: object() for name in ("read_calendar", "drop_excluded", "shift_start_for_age", "build")}

    def operation(name):
        def run(*args, **kwargs):
            calls.append((name, args, kwargs))
            return results[name]
        return run

    for name in results:
        setattr(backend, name, operation(name))
    imports = []
    monkeypatch.setattr(host, "import_module", lambda name: imports.append(name) or backend)
    original_import = builtins.__import__

    def no_policy(name, *args, **kwargs):
        assert name.split(".")[-1] not in {"train_wiring", "buy_eligibility", "st_status"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_policy)
    calendar_path = tmp_path / "day.txt"
    provider = tmp_path / "provider"
    calendar, lines, exclusions = ["2026-01-05"], ["SZ000001\t2026-01-05\t2026-01-09"], set()
    assert host.read_calendar(calendar_path) is results["read_calendar"]
    assert host.drop_excluded(lines, exclusions) is results["drop_excluded"]
    assert host.shift_start_for_age(lines, calendar, 2) is results["shift_start_for_age"]
    assert host.build(provider, exclusions=exclusions, age_days=2, calendar=calendar, asof=ASOF) is results["build"]
    assert imports == [PACKAGE] * 4
    assert calls == [
        ("read_calendar", (calendar_path,), {}),
        ("drop_excluded", (lines, exclusions), {}),
        ("shift_start_for_age", (lines, calendar, 2), {}),
        ("build", (provider,), {"exclusions": exclusions, "age_days": 2, "calendar": calendar, "asof": ASOF}),
    ]
    assert calls[-1][2]["exclusions"] is exclusions
    assert calls[-1][2]["calendar"] is calendar
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("missing", ["exclusions", "age_days", "calendar", "asof"])
def test_build_requires_every_caller_policy_input(monkeypatch, missing):
    monkeypatch.setattr(host, "_universe", lambda: pytest.fail("loaded infra before argument validation"))
    kwargs = dict(exclusions=set(), age_days=0, calendar=[], asof=ASOF)
    del kwargs[missing]
    with pytest.raises(TypeError, match=missing):
        host.build("provider", **kwargs)


def policy_stubs(monkeypatch, static=()):
    train = types.ModuleType("train_wiring")
    train.EXCLUDE_STOCKS_DEFAULT = list(static)
    monkeypatch.setitem(sys.modules, "train_wiring", train)
    st = types.ModuleType("st_status")
    monkeypatch.setitem(sys.modules, "st_status", st)
    return st


def test_exclusions_are_resolved_by_host_before_infra(monkeypatch, tmp_path):
    st = policy_stubs(monkeypatch, ["sz000001"])
    extra = tmp_path / "extra.txt"
    extra.write_text(" sh600000 \n\nSZ000001\n", encoding="utf-8")
    daily = tmp_path / "st_daily.parquet"
    calls = []
    st.load_st_codes_asof = lambda path, **kwargs: calls.append((path, kwargs)) or {"BJ920072"}
    monkeypatch.setattr(host, "_universe", lambda: pytest.fail("policy resolver must not call infra"))
    assert host.resolve_exclusions(extra, daily, asof=ASOF) == {"SZ000001", "SH600000", "BJ920072"}
    assert calls == [(daily, {"asof": ASOF})]


@pytest.mark.parametrize("extra", [None, "missing-extra.txt"])
def test_empty_host_policy_is_explicit_and_needs_no_st_loader(monkeypatch, extra):
    # The empty ST stub has no loader: absent --st-daily-file must not consult it.
    policy_stubs(monkeypatch)
    assert host.resolve_exclusions(extra, None, asof=ASOF) == set()


@pytest.mark.parametrize("asof_option,age_options,age", [
    ("--asof", [], 60), ("--st-asof", ["--age-days", "2"], 2),
])
def test_cli_injects_resolved_policy_and_explicit_paths(monkeypatch, tmp_path, capsys,
                                                      asof_option, age_options, age):
    st = policy_stubs(monkeypatch, ["sz000001"])
    st.load_st_codes_asof = lambda path, *, asof: {"SH600001"} if asof == ASOF else pytest.fail("wrong asof")
    extra = tmp_path / "extra.txt"
    extra.write_text("bj920072\n", encoding="utf-8")
    provider, calendar_path = tmp_path / "provider", tmp_path / "day.txt"
    calendar = ["2026-01-05", "2026-01-06"]
    calls = []

    def read(path):
        assert path == calendar_path
        return calendar

    def build(path, **kwargs):
        calls.append((path, kwargs))
        return dict(total=5, dropped_st=3, kept=2, path=str(provider / "instruments/all_tradable.txt"), asof=ASOF)

    monkeypatch.setattr(host, "_universe", lambda: types.SimpleNamespace(read_calendar=read, build=build))
    assert host.main([
        "--qlib-dir", str(provider), "--calendar", str(calendar_path), asof_option, ASOF,
        "--extra-exclude-file", str(extra), "--st-daily-file", str(tmp_path / "st_daily.parquet"), *age_options,
    ]) == 0
    assert calls == [(provider, dict(exclusions={"SZ000001", "SH600001", "BJ920072"},
                                    age_days=age, calendar=calendar, asof=ASOF))]
    assert "asof=" + ASOF in capsys.readouterr().out


@pytest.fixture
def infra():
    return pytest.importorskip(PACKAGE, reason="optional C4 infra pin")


@pytest.fixture
def provider(tmp_path):
    root = tmp_path / "provider_with_{braces}"
    for directory in ("instruments", "calendars", "features/sz000001"):
        (root / directory).mkdir(parents=True)
    (root / "calendars/day.txt").write_text(
        "2026-01-05\n2026-01-06\n2026-01-07\n2026-01-08\n2026-01-09\n", encoding="utf-8",
    )
    (root / "instruments/all.txt").write_text(
        "sz000001\t2026-01-05\t2026-01-09\n"
        "SH600001\t2026-01-05\t2026-01-09\n"
        "SH600000\t2019-01-01\t2026-01-09\n"
        "SZ300001\t2026-01-05\t2026-01-09\n"
        "BJ920072\t2026-01-09\t2026-01-09\n"
        "SZ300002\t2026-01-05 09:30:00\t2026-01-09 15:00:00\n"
        "SH600002\t2026-01-06\t2026-01-06\n"
        "malformed\n\n", encoding="utf-8",
    )
    (root / "instruments/all_tradable.txt").write_text("previous membership\n", encoding="utf-8")
    (root / "features/sz000001/close.day.bin").write_bytes(b"protected features\x00")
    return root


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_real_build_writes_only_membership_and_preserves_transform_semantics(infra, provider):
    before = snapshot(provider)
    calendar = host.read_calendar(provider / "calendars/day.txt")
    stats = host.build(provider, exclusions={"sz000001"}, age_days=2, calendar=calendar, asof=ASOF)
    output = provider / "instruments/all_tradable.txt"
    assert output.read_bytes() == (
        b"SH600001\t2026-01-07\t2026-01-09\n"
        b"SH600000\t2019-01-01\t2026-01-09\n"
        b"SZ300001\t2026-01-07\t2026-01-09\n"
        b"BJ920072\t9999-12-31\t2026-01-09\n"
        b"SZ300002\t2026-01-07 09:30:00\t2026-01-09 15:00:00\n"
        b"SH600002\t2026-01-08\t2026-01-06\n"
        b"malformed\n"
    )
    assert stats == dict(total=8, dropped_st=1, kept=7, path=str(output), asof=ASOF)
    after = snapshot(provider)
    assert before.keys() == after.keys()
    assert [name for name in before if before[name] != after[name]] == ["instruments/all_tradable.txt"]
    assert host.build(provider, exclusions={"sz000001"}, age_days=2, calendar=calendar, asof=ASOF) == stats
    assert snapshot(provider) == after


def test_real_cli_keeps_st_asof_and_coverage_policy_in_host(infra, provider, tmp_path, monkeypatch):
    import pandas as pd

    policy_stubs(monkeypatch, ["SZ000001"])
    # Use the real, unchanged MQ ST reader, not the stub used by policy-only tests.
    monkeypatch.delitem(sys.modules, "st_status")
    daily = tmp_path / "st_daily.parquet"
    pd.DataFrame({"trade_date": ["2026-01-05", "2026-01-09"],
                  "code": ["600001.SH", "600000.SH"], "is_st": [True, True]}).to_parquet(daily)
    (tmp_path / "st_coverage.json").write_text(
        '{"snapshot_fallback_wind_codes": ["600002.SH"]}', encoding="utf-8",
    )
    extra = tmp_path / "extra.txt"
    extra.write_text("sz300001\n", encoding="utf-8")
    assert host.main([
        "--qlib-dir", str(provider), "--calendar", str(provider / "calendars/day.txt"),
        "--asof", ASOF, "--age-days", "2", "--extra-exclude-file", str(extra), "--st-daily-file", str(daily),
    ]) == 0
    output = (provider / "instruments/all_tradable.txt").read_text(encoding="utf-8")
    codes = {line.split("\t")[0] for line in output.splitlines()}
    assert not codes & {"sz000001", "SH600001", "SZ300001"}
    assert {"SH600000", "SH600002"} <= codes  # Later ST and sidecar fallback do not enter this snapshot.


def test_real_generic_path_never_imports_train_wiring_or_eligibility(infra, provider, tmp_path):
    code = f"""
        import importlib.abc
        import socket
        import sys
        class BlockHostPolicy(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, *args):
                if fullname.split('.')[-1] in {{'train_wiring', 'buy_eligibility', 'st_status'}} or fullname == 'qlib':
                    raise AssertionError('host policy in generic infra path: ' + fullname)
        def offline(*args, **kwargs):
            raise AssertionError('network in C4 test')
        socket.socket.connect = offline
        socket.create_connection = offline
        sys.meta_path.insert(0, BlockHostPolicy())
        sys.path.insert(0, {str(SCRIPT.parent)!r})
        import build_tradable_universe as caller
        cal = caller.read_calendar({str(provider / 'calendars/day.txt')!r})
        assert caller.drop_excluded(['SH600000'], set()) == (['SH600000'], [])
        assert caller.shift_start_for_age(['SH600000\\t2026-01-05\\t2026-01-09'], cal, 2) == [
            'SH600000\\t2026-01-07\\t2026-01-09']
        stats = caller.build({str(provider)!r}, exclusions=set(), age_days=2, calendar=cal, asof={ASOF!r})
        assert stats['kept'] == 8 and stats['dropped_st'] == 0
        assert not {{'train_wiring', 'buy_eligibility', 'st_status', 'qlib'}} & sys.modules.keys()
    """
    result = python(tmp_path, "-c", textwrap.dedent(code))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("target", ["instruments/all.txt", "calendars/day.txt", "features/sz000001/close.day.bin"])
def test_real_disjoint_guard_rejects_output_symlink_to_inputs(infra, provider, target):
    output = provider / "instruments/all_tradable.txt"
    output.unlink()
    output.symlink_to(provider / target)
    before = snapshot(provider)
    with pytest.raises(ValueError, match="overlaps"):
        host.build(provider, exclusions=set(), age_days=0, calendar=["2026-01-05"], asof=ASOF)
    assert snapshot(provider) == before


@pytest.mark.parametrize("override", [
    {"qlib_dir": None}, {"exclusions": None}, {"exclusions": "SZ000001"},
    {"age_days": -1}, {"age_days": True}, {"calendar": None},
    {"calendar": ["2026-01-05", "2026-01-05"]},
    {"calendar": ["2026-01-06", "2026-01-05"]}, {"asof": None},
])
def test_real_invalid_inputs_do_not_overwrite_membership(infra, provider, override):
    before = snapshot(provider)
    kwargs = dict(qlib_dir=provider, exclusions=set(), age_days=0, calendar=["2026-01-05"], asof=ASOF)
    kwargs.update(override)
    with pytest.raises(ValueError):
        host.build(**kwargs)
    assert snapshot(provider) == before


@pytest.mark.parametrize("calendar", [[], ["2026-01-05"]])
def test_real_empty_or_exhausted_calendar_keeps_unbuyable_sentinel(infra, calendar):
    assert host.shift_start_for_age(["BJ920072\t2026-01-05\t2026-01-09"], calendar, 1) == [
        "BJ920072\t9999-12-31\t2026-01-09",
    ]
