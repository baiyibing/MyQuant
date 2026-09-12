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


# ----- M1-B：门禁 + 原子 swap -----

from refresh_mydata import (  # noqa: E402
    INDEX_CODE_RE,
    atomic_swap,
    gate_calendar_vs_lake,
    gate_no_indices_in_all,
    gate_sample_values,
    gate_universe_diff,
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


def test_gate_calendar_vs_lake_missing_aborts(tmp_path):
    import pandas as pd

    qlib = tmp_path / "new"
    _write_calendar(qlib, ["2026-03-02", "2026-03-03", "2026-03-04"])
    lake_days = pd.DatetimeIndex(pd.to_datetime(["2026-03-02", "2026-03-04"]))  # 缺 03-03
    with pytest.raises(RefreshError, match="门禁1"):
        gate_calendar_vs_lake(qlib, tmp_path / "lake", lake_days=lake_days)


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
