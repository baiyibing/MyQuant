# -*- coding: utf-8 -*-
"""refresh_mydata 编排器单测（M1-A：参数校验 + dry-run 计划）。"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_QLIB_SCRIPTS = os.path.join(_ROOT, "qlib_scripts")
if _QLIB_SCRIPTS not in sys.path:
    sys.path.insert(0, _QLIB_SCRIPTS)

from refresh_mydata import (  # noqa: E402
    DEFAULT_MAX_WORKERS,
    RefreshConfig,
    RefreshError,
    build_dump_cmd,
    build_merge_cmd,
    build_patch_cmd,
    build_plan,
    config_from_args,
    build_parser,
    format_dry_run,
    require_valid,
    validate_params,
)


def _cfg(**kwargs) -> RefreshConfig:
    base = dict(
        archive_dir=Path("/tmp/archive"),
        csv_dir=Path("/tmp/csv"),
        qlib_dir=Path("/tmp/qlib_parent/my_data"),
        staging_dir=Path("/tmp/qlib_parent/staging"),
        new_qlib_dir=Path("/tmp/qlib_parent/new"),
        today=date(2026, 9, 13),
    )
    base.update(kwargs)
    cfg = RefreshConfig(**base)
    cfg.resolve_paths()
    return cfg


def test_validate_params_rejects_max_workers_16():
    cfg = _cfg(max_workers=16)
    errs = validate_params(cfg)
    assert any("max_workers" in e for e in errs)
    with pytest.raises(RefreshError):
        require_valid(cfg)


def test_validate_params_ok_default():
    assert validate_params(_cfg()) == []


def test_validate_params_bad_lake_symbol():
    errs = validate_params(_cfg(lake_symbol="000001"))
    assert any("lake_symbol" in e for e in errs)


def test_dump_cmd_is_dump_all_workers_8_no_update():
    cmd = build_dump_cmd(_cfg())
    joined = " ".join(cmd.argv)
    assert "dump_all" in cmd.argv
    assert "dump_update" not in joined
    assert f"--max_workers={DEFAULT_MAX_WORKERS}" in cmd.argv
    assert "--max_workers=16" not in joined


def test_merge_and_patch_cmds_point_at_scripts():
    cfg = _cfg()
    merge = build_merge_cmd(cfg)
    patch = build_patch_cmd(cfg)
    assert merge.argv[1].endswith("merge_archive_and_csv.py")
    assert str(cfg.staging_dir) in merge.argv
    assert patch.argv[1].endswith("patch_index_data.py")
    assert str(cfg.new_qlib_dir) in patch.argv
    assert "--no-backup" in patch.argv


def test_dry_run_output_contains_steps_and_paths(tmp_path, capsys):
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "SH600000.csv").write_text("date,close\n", encoding="utf-8")
    qlib = tmp_path / "my_data"
    (qlib / "instruments").mkdir(parents=True)
    (qlib / "instruments" / "all.txt").write_text(
        "SH600000\t2020-01-02\t2026-09-08\n", encoding="utf-8"
    )
    cfg = _cfg(csv_dir=csv_dir, qlib_dir=qlib, staging_dir=tmp_path / "stg", new_qlib_dir=tmp_path / "new")
    text = format_dry_run(cfg, build_plan(cfg))
    assert "merge_archive_and_csv" in text
    assert "dump_bin.dump_all" in text
    assert "patch_index_data" in text
    assert str(cfg.staging_dir) in text
    assert str(cfg.new_qlib_dir) in text
    assert str(cfg.qlib_dir) in text
    assert "max_workers: 8" in text
    assert "dump_update: FORBIDDEN" in text
    assert "universe_estimate:" in text


def test_cli_dry_run_exits_zero(tmp_path):
    from refresh_mydata import main

    code = main(
        [
            "--dry-run",
            "--csv-dir",
            str(tmp_path / "csv"),
            "--archive-dir",
            str(tmp_path / "arch"),
            "--qlib-dir",
            str(tmp_path / "my_data"),
            "--staging-dir",
            str(tmp_path / "stg"),
            "--new-qlib-dir",
            str(tmp_path / "new"),
        ]
    )
    assert code == 0


def test_config_from_args_resolves_defaults():
    args = build_parser().parse_args(["--dry-run", "--max-workers", "8"])
    cfg = config_from_args(args, today=date(2026, 9, 13))
    assert cfg.staging_dir.name.startswith("my_data_staging_20260913")
    assert cfg.new_qlib_dir.name.startswith("my_data_new_20260913")
    assert cfg.max_workers == 8
    assert cfg.wipe_new_qlib_dir is False


def test_dry_run_mentions_wipe_and_csv_scan(tmp_path):
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    qlib = tmp_path / "my_data"
    (qlib / "instruments").mkdir(parents=True)
    (qlib / "instruments" / "all.txt").write_text("SH600000\t2020-01-02\t2026-09-08\n", encoding="utf-8")
    cfg = _cfg(csv_dir=csv_dir, qlib_dir=qlib, staging_dir=tmp_path / "stg", new_qlib_dir=tmp_path / "new")
    text = format_dry_run(cfg, build_plan(cfg))
    assert "--wipe-new-qlib-dir" in text
    assert "illegal-float" in text
    assert "日历末日不变也要 dump_all" in text
    assert "read_bin_field" in text
    assert "overlay" in text
    assert "last_valid" in text
    assert "同日第二次自动 _2" in text
    assert "st_daily" in text


from refresh_mydata import (  # noqa: E402
    RefreshError,
    assert_disk_space,
    dump_target_is_dirty,
    ensure_dump_target_clean,
    print_refresh_summary,
    run_csv_profile_preflight,
    run_csv_scan_preflight,
    smoke_winratio_sample,
)


def test_ensure_dump_target_refuses_dirty_without_wipe(tmp_path):
    new = tmp_path / "new"
    (new / "calendars").mkdir(parents=True)
    (new / "calendars" / "day.txt").write_text("2020-01-02\n", encoding="utf-8")
    cfg = _cfg(new_qlib_dir=new)
    assert dump_target_is_dirty(new)
    with pytest.raises(RefreshError, match="半成品"):
        ensure_dump_target_clean(cfg)


def test_ensure_dump_target_wipes_when_flagged(tmp_path):
    new = tmp_path / "new"
    (new / "calendars").mkdir(parents=True)
    (new / "calendars" / "day.txt").write_text("2020-01-02\n", encoding="utf-8")
    cfg = _cfg(new_qlib_dir=new, wipe_new_qlib_dir=True)
    ensure_dump_target_clean(cfg)
    assert not new.exists()


def test_assert_disk_space_refuses_small_dump_drive(tmp_path):
    cfg = _cfg(
        skip_merge=True,
        skip_dump=False,
        new_qlib_dir=tmp_path / "new",
        min_dump_free_gb=10.0,
    )
    cfg.resolve_paths()
    tmp_path.mkdir(parents=True, exist_ok=True)

    class FakeUsage:
        free = int(1e9)  # 1 GB

    with pytest.raises(RefreshError, match="dump 目标盘"):
        assert_disk_space(cfg, usage_fn=lambda _p: FakeUsage)


def test_csv_scan_preflight_rejects_ohlc_junk(tmp_path):
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "SH600000.csv").write_text("date,close\n2020-01-02,-1.#J\n", encoding="utf-8")
    cfg = _cfg(csv_dir=csv_dir, skip_csv_scan=False)
    with pytest.raises(RefreshError, match="OHLC"):
        run_csv_scan_preflight(cfg)


def test_csv_scan_preflight_warns_only_on_winratio(tmp_path, capsys):
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "SH600157.csv").write_text(
        "date,close,winratio\n2020-01-02,10.0,-1.#J\n", encoding="utf-8"
    )
    cfg = _cfg(csv_dir=csv_dir)
    report = run_csv_scan_preflight(cfg)
    assert report["fatal"] == []
    assert len(report["warn"]) == 1
    assert "WARN" in capsys.readouterr().out


def test_print_refresh_summary(tmp_path, capsys):
    qlib = tmp_path / "new"
    (qlib / "calendars").mkdir(parents=True)
    (qlib / "calendars" / "day.txt").write_text("2020-01-02\n2026-09-14\n", encoding="utf-8")
    (qlib / "calendars" / "day_future.txt").write_text(
        "2020-01-02\n2026-09-14\n2026-09-15\n", encoding="utf-8"
    )
    (qlib / "instruments").mkdir(parents=True)
    (qlib / "instruments" / "index.txt").write_text(
        "SH000001\t2020-01-02\t2026-09-14\n", encoding="utf-8"
    )
    wr = qlib / "features" / "sh600000"
    wr.mkdir(parents=True)
    (wr / "winratio.day.bin").write_bytes(b"\x00" * 8)
    print_refresh_summary(qlib)
    out = capsys.readouterr().out
    assert "2026-09-14" in out
    assert "day_future .. 2026-09-15" in out
    assert "winratio bins=1" in out
    assert "winratio SH600000" in out
    assert "out_of_[0,1]=0" in out
    sample = smoke_winratio_sample(qlib)
    assert sample is not None
    assert sample["symbol"] == "SH600000"
    assert sample["out_of_01"] == 0


def test_csv_profile_preflight_flags_short_tail(tmp_path, capsys):
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    rows = "\n".join(f"SH600000,2026-09-{d:02d},10.0" for d in range(2, 12))
    (csv_dir / "SH600000.csv").write_text("code,date,close\n" + rows + "\n", encoding="utf-8")
    cfg = _cfg(csv_dir=csv_dir, archive_dir=tmp_path / "missing_archive")
    profile = run_csv_profile_preflight(cfg)
    assert profile["short_tail"] is True
    out = capsys.readouterr().out
    assert "short_tail=True" in out
    assert "overlay" in out


def test_smoke_winratio_reports_last_valid(tmp_path, capsys):
    import numpy as np

    qlib = tmp_path / "new"
    (qlib / "calendars").mkdir(parents=True)
    (qlib / "calendars" / "day.txt").write_text("2026-09-14\n2026-09-15\n", encoding="utf-8")
    feat = qlib / "features" / "sh600000"
    feat.mkdir(parents=True)
    arr = np.array([0.0, 0.56, np.nan], dtype="<f")
    arr.tofile(feat / "winratio.day.bin")
    (qlib / "instruments").mkdir(parents=True)
    (qlib / "instruments" / "all.txt").write_text(
        "SH600000\t2026-09-14\t2026-09-15\n", encoding="utf-8"
    )
    print_refresh_summary(qlib)
    out = capsys.readouterr().out
    assert "last_valid=2026-09-14=0.5600" in out
    assert "末日 winratio 为空可接受" in out
    sample = smoke_winratio_sample(qlib)
    assert sample["last"] is None
    assert sample["last_valid"] == "2026-09-14"
    assert sample["last_valid_value"] == pytest.approx(0.56)


# ----- M1-B：门禁 + 原子 swap -----

from refresh_mydata import (  # noqa: E402
    INDEX_CODE_RE,
    atomic_swap,
    backup_name,
    gate_calendar_vs_lake,
    gate_no_indices_in_all,
    gate_sample_values,
    gate_universe_diff,
    pick_sample_symbols,
    run_integrity_gates,
)


def _write_calendar(qlib_dir: Path, days: list[str]) -> None:
    cal = qlib_dir / "calendars"
    cal.mkdir(parents=True, exist_ok=True)
    (cal / "day.txt").write_text("\n".join(days) + "\n", encoding="utf-8")


def _write_all_txt(qlib_dir: Path, symbols: list[str]) -> None:
    inst = qlib_dir / "instruments"
    inst.mkdir(parents=True, exist_ok=True)
    lines = [f"{s}\t2020-01-02\t2026-09-08" for s in symbols]
    (inst / "all.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_close_bin(qlib_dir: Path, symbol: str, calendar_days: list[str], values: list[float]) -> None:
    """写最小 close.day.bin：start_index=0，后接 float32 值。"""
    import numpy as np

    feat = qlib_dir / "features" / symbol.lower()
    feat.mkdir(parents=True, exist_ok=True)
    assert len(values) == len(calendar_days)
    arr = np.zeros(len(values) + 1, dtype="<f")
    arr[0] = 0.0  # start index
    arr[1:] = np.asarray(values, dtype="<f")
    arr.tofile(feat / "close.day.bin")


def test_gate_calendar_vs_lake_ok(tmp_path):
    import pandas as pd

    qlib = tmp_path / "new"
    days = ["2026-03-02", "2026-03-03", "2026-03-04"]
    _write_calendar(qlib, days)
    lake_days = pd.DatetimeIndex(pd.to_datetime(days + ["2026-03-05"]))
    report = gate_calendar_vs_lake(qlib, tmp_path / "lake", lake_days=lake_days)
    assert report["missing_count"] == 0


def test_gate_calendar_vs_lake_beyond_requires_flag(tmp_path):
    import pandas as pd

    qlib = tmp_path / "new"
    _write_calendar(qlib, ["2026-09-10", "2026-09-11", "2026-09-14"])
    lake_days = pd.DatetimeIndex(pd.to_datetime(["2026-09-10", "2026-09-11"]))
    with pytest.raises(RefreshError, match="比湖"):
        gate_calendar_vs_lake(qlib, tmp_path / "lake", lake_days=lake_days)
    report = gate_calendar_vs_lake(
        qlib, tmp_path / "lake", lake_days=lake_days, allow_beyond_lake=True
    )
    assert report["beyond_lake"] == ["2026-09-14"]
    assert report["missing_count"] == 1


def test_gate_calendar_vs_lake_historical_hole_not_saved_by_beyond_flag(tmp_path):
    import pandas as pd

    qlib = tmp_path / "new"
    _write_calendar(qlib, ["2026-09-10", "2026-09-11", "2026-09-14"])
    lake_days = pd.DatetimeIndex(pd.to_datetime(["2026-09-10", "2026-09-14"]))  # 缺 09-11
    with pytest.raises(RefreshError, match="缺"):
        gate_calendar_vs_lake(
            qlib, tmp_path / "lake", lake_days=lake_days, allow_beyond_lake=True
        )


def test_gate_no_indices_detects_leak(tmp_path):
    qlib = tmp_path / "new"
    _write_all_txt(qlib, ["SH600000", "SH000300", "SZ300190"])
    with pytest.raises(RefreshError, match="门禁3"):
        gate_no_indices_in_all(qlib)
    _write_all_txt(qlib, ["SH600000", "SZ300190"])
    assert gate_no_indices_in_all(qlib)["index_leak"] == []


def test_gate_universe_diff_requires_force(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write_all_txt(old, [f"SH60000{i}" for i in range(5)])
    _write_all_txt(new, ["SH600000", "SH600001"])  # removed 3
    with pytest.raises(RefreshError, match="门禁4"):
        gate_universe_diff(old, new, expected_delist_max=2, force=False)
    report = gate_universe_diff(old, new, expected_delist_max=2, force=True)
    assert report["removed_count"] == 3
    assert report["added_count"] == 0


def test_pick_sample_skips_late_listed(tmp_path):
    qlib = tmp_path / "new"
    _write_calendar(qlib, ["2020-01-02", "2026-09-14"])
    inst = qlib / "instruments"
    inst.mkdir(parents=True, exist_ok=True)
    (inst / "all.txt").write_text(
        "BJ920000\t2020-11-16\t2026-09-14\n"
        "SH600000\t2020-01-02\t2026-09-14\n"
        "SZ000001\t2020-01-02\t2026-09-14\n"
        "SH600519\t2020-01-02\t2026-09-14\n",
        encoding="utf-8",
    )
    assert pick_sample_symbols(qlib, 3) == ["SH600000", "SZ000001", "SH600519"]


def test_gate_sample_values_mismatch(tmp_path):
    import pandas as pd

    qlib = tmp_path / "new"
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    days = ["2026-03-02", "2026-03-03"]
    _write_calendar(qlib, days)
    _write_all_txt(qlib, ["SH600000"])
    _write_close_bin(qlib, "SH600000", days, [10.0, 11.0])
    # CSV 末日故意写错
    (csv_dir / "SH600000.csv").write_text(
        "date,close\n2026-03-02,10.0\n2026-03-03,99.0\n", encoding="utf-8"
    )
    with pytest.raises(RefreshError, match="门禁2"):
        gate_sample_values(qlib, csv_dir, symbols=["SH600000"])


def test_gate_sample_values_ok_with_injected_source(tmp_path):
    qlib = tmp_path / "new"
    days = ["2026-03-02", "2026-03-03"]
    _write_calendar(qlib, days)
    _write_all_txt(qlib, ["SH600000", "SZ000001", "SH600519"])
    for sym, vals in (
        ("SH600000", [1.0, 2.0]),
        ("SZ000001", [3.0, 4.0]),
        ("SH600519", [5.0, 6.0]),
    ):
        _write_close_bin(qlib, sym, days, vals)

    def src(sym, day):
        table = {
            ("SH600000", "2026-03-02"): 1.0,
            ("SH600000", "2026-03-03"): 2.0,
            ("SZ000001", "2026-03-02"): 3.0,
            ("SZ000001", "2026-03-03"): 4.0,
            ("SH600519", "2026-03-02"): 5.0,
            ("SH600519", "2026-03-03"): 6.0,
        }
        return table[(sym, str(day.date()))]

    report = gate_sample_values(
        qlib, tmp_path / "csv", symbols=["SH600000", "SZ000001", "SH600519"], source_close_fn=src
    )
    assert len(report["checked"]) == 6


def test_atomic_swap_and_rollback(tmp_path):
    target = tmp_path / "my_data"
    new = tmp_path / "my_data_new"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    new.mkdir()
    (new / "new.txt").write_text("new", encoding="utf-8")
    backup = atomic_swap(target, new, today=date(2026, 9, 13))
    assert backup.name == "my_data_backup_20260913_pre_refresh"
    assert (target / "new.txt").read_text(encoding="utf-8") == "new"
    assert (backup / "old.txt").read_text(encoding="utf-8") == "old"
    assert not new.exists()

    # 失败回滚：renamer 在第二次调用时抛错
    target2 = tmp_path / "t2"
    new2 = tmp_path / "n2"
    target2.mkdir()
    (target2 / "a").write_text("a", encoding="utf-8")
    new2.mkdir()
    (new2 / "b").write_text("b", encoding="utf-8")
    calls = {"n": 0}

    def bad_rename(a: Path, b: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("boom")
        a.rename(b)

    with pytest.raises(RefreshError, match="swap 失败"):
        atomic_swap(target2, new2, today=date(2026, 9, 14), renamer=bad_rename)
    # 回滚后目标应恢复
    assert target2.exists()
    assert (target2 / "a").read_text(encoding="utf-8") == "a"


def test_backup_name_increments_on_same_day(tmp_path):
    qlib = tmp_path / "my_data"
    qlib.mkdir()
    first = backup_name(qlib, date(2026, 9, 15))
    assert first.name == "my_data_backup_20260915_pre_refresh"
    first.mkdir()
    second = backup_name(qlib, date(2026, 9, 15))
    assert second.name == "my_data_backup_20260915_pre_refresh_2"
    second.mkdir()
    third = backup_name(qlib, date(2026, 9, 15))
    assert third.name == "my_data_backup_20260915_pre_refresh_3"


def test_run_integrity_gates_aborts_before_swap_contract(tmp_path):
    """门禁失败时 run_integrity_gates 抛错——main 不会走到 atomic_swap。"""
    import pandas as pd

    new = tmp_path / "new"
    old_dir = tmp_path / "old"
    days = ["2026-03-02", "2026-03-03"]
    _write_calendar(new, days)
    # 3 只股票 + 指数泄漏：gate1/2 过，gate3 拦
    syms = ["SH600000", "SZ000001", "SH600519", "SH000300"]
    _write_all_txt(new, syms)
    _write_all_txt(old_dir, ["SH600000", "SZ000001", "SH600519"])
    for sym, vals in (
        ("SH600000", [1.0, 2.0]),
        ("SZ000001", [3.0, 4.0]),
        ("SH600519", [5.0, 6.0]),
    ):
        _write_close_bin(new, sym, days, vals)
    cfg = _cfg(
        qlib_dir=old_dir,
        new_qlib_dir=new,
        csv_dir=tmp_path / "csv",
        lake_index_root=tmp_path / "lake",
        sample_symbols=("SH600000", "SZ000001", "SH600519"),
    )
    lake_days = pd.DatetimeIndex(pd.to_datetime(days))

    def src(sym, day):
        return {"SH600000": {days[0]: 1.0, days[1]: 2.0},
                "SZ000001": {days[0]: 3.0, days[1]: 4.0},
                "SH600519": {days[0]: 5.0, days[1]: 6.0}}[sym][str(day.date())]

    with pytest.raises(RefreshError, match="门禁3"):
        run_integrity_gates(cfg, lake_days=lake_days, source_close_fn=src)


def test_load_lake_trading_days_utc_ms(tmp_path):
    import pandas as pd
    from refresh_mydata import load_lake_trading_days

    # 2026-03-03 00:30 上海 = 前一日 UTC 下午；必须转上海日期
    ms = pd.Timestamp("2026-03-03 00:30", tz="Asia/Shanghai").value // 10**6

    def reader(_path):
        return pd.DataFrame({"time": [ms]})

    days = load_lake_trading_days(tmp_path, "000001_SH", reader=reader)
    assert list(days.strftime("%Y-%m-%d")) == ["2026-03-03"]


# ----- M1-C：archive / offsite -----

from refresh_mydata import (  # noqa: E402
    archive_qlib_dir,
    discover_7z,
    md5_file,
    offsite_copy_and_verify,
)


def test_discover_7z_respects_explicit(tmp_path):
    fake = tmp_path / "7z"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    assert discover_7z(fake) == fake


def test_archive_qlib_dir_missing_7z_clear_error(tmp_path, monkeypatch):
    qlib = tmp_path / "my_data"
    qlib.mkdir()
    (qlib / "x").write_text("1", encoding="utf-8")
    monkeypatch.setattr("refresh_mydata.discover_7z", lambda explicit=None: None)
    with pytest.raises(RefreshError, match="未找到 7-Zip"):
        archive_qlib_dir(qlib, today=date(2026, 9, 13), seven_zip=None)


def test_archive_qlib_dir_mocked_runner(tmp_path):
    qlib = tmp_path / "my_data"
    qlib.mkdir()
    (qlib / "x").write_text("1", encoding="utf-8")
    fake7z = tmp_path / "7z.exe"
    fake7z.write_text("x", encoding="utf-8")
    calls = {}

    class FakeProc:
        returncode = 0

    def runner(argv, cwd=None, check=False):
        calls["argv"] = argv
        calls["cwd"] = cwd
        # 模拟 7z 写出归档
        out = Path(cwd) / "my_data_20260913_full.7z"
        out.write_bytes(b"7z-fake-bytes")
        return FakeProc()

    path = archive_qlib_dir(
        qlib, today=date(2026, 9, 13), seven_zip=fake7z, out_dir=tmp_path, runner=runner
    )
    assert path.name == "my_data_20260913_full.7z"
    assert path.is_file()
    assert "a" in calls["argv"]
    assert calls["argv"][0] == str(fake7z)


def test_offsite_copy_md5_three_way(tmp_path):
    archive = tmp_path / "my_data_20260913_full.7z"
    archive.write_bytes(b"payload-abc")
    f_root = tmp_path / "F"
    g_root = tmp_path / "G"
    f_root.mkdir()
    g_root.mkdir()
    report = offsite_copy_and_verify(archive, [f_root, g_root])
    assert report["source_md5"] == md5_file(archive)
    assert len(report["copies"]) == 2
    assert report["mismatched"] == []
    assert (f_root / archive.name).read_bytes() == b"payload-abc"
    assert (g_root / archive.name).read_bytes() == b"payload-abc"


def test_offsite_all_missing_roots_errors(tmp_path):
    archive = tmp_path / "my_data_20260913_full.7z"
    archive.write_bytes(b"x")
    with pytest.raises(RefreshError, match="offsite 根目录都不存在"):
        offsite_copy_and_verify(archive, [tmp_path / "noF", tmp_path / "noG"])


def test_offsite_partial_missing_ok(tmp_path):
    archive = tmp_path / "my_data_20260913_full.7z"
    archive.write_bytes(b"x")
    ok = tmp_path / "G"
    ok.mkdir()
    report = offsite_copy_and_verify(archive, [tmp_path / "noF", ok])
    assert len(report["copies"]) == 1
    assert report["missing"] == [str(tmp_path / "noF")]


def test_offsite_md5_mismatch(tmp_path):
    archive = tmp_path / "my_data_20260913_full.7z"
    archive.write_bytes(b"good")
    root = tmp_path / "F"
    root.mkdir()

    def bad_copy(src, dst):
        Path(dst).write_bytes(b"tampered")

    with pytest.raises(RefreshError, match="MD5"):
        offsite_copy_and_verify(archive, [root], copy_fn=bad_copy)


# ----- day_future 重建（2026-09-13 回测末日越界事故的编排器修复） -----

from refresh_mydata import (  # noqa: E402
    next_weekdays_after,
    refresh_day_future_calendar,
)


def test_next_weekdays_after_skips_weekend():
    import pandas as pd

    days = next_weekdays_after(pd.Timestamp("2026-09-08"), 5)  # 周二
    assert [d.strftime("%Y-%m-%d") for d in days] == [
        "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15",
    ]
    # 数据末日落在周五：下一天须跳过周末
    days_fri = next_weekdays_after(pd.Timestamp("2026-04-10"), 5)
    assert days_fri[0].strftime("%Y-%m-%d") == "2026-04-13"


def test_refresh_day_future_extends_past_calendar_end(tmp_path):
    qlib_dir = tmp_path / "my_data"
    _write_calendar(qlib_dir, ["2020-01-02", "2026-09-07", "2026-09-08"])
    out = refresh_day_future_calendar(qlib_dir)
    lines = out.read_text(encoding="ascii").splitlines()
    assert lines[:3] == ["2020-01-02", "2026-09-07", "2026-09-08"]
    assert lines[3] == "2026-09-09"  # 数据末日 + 1：回测末日不越界的硬要求
    assert len(lines) == 3 + 5
    # 幂等：重跑结果一致
    out2 = refresh_day_future_calendar(qlib_dir)
    assert out2.read_text(encoding="ascii") == out.read_text(encoding="ascii")


def test_refresh_day_future_requires_calendar(tmp_path):
    with pytest.raises(RefreshError, match="日历不存在"):
        refresh_day_future_calendar(tmp_path / "empty")
