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
