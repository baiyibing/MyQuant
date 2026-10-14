# -*- coding: utf-8 -*-
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_scripts.build_etf_qlib import (  # noqa: E402
    REQUIRED_WORKERS,
    SURVIVORSHIP_NOTE,
    BuildConfig,
    BuildEtfError,
    dump_argv,
    execute,
    is_etf_full,
    summarize_ratios,
)


def _cfg(tmp_path: Path, **kwargs) -> tuple[BuildConfig, Path]:
    protected = tmp_path / "qlib_data" / "my_data"
    minute = tmp_path / "qlib_data" / "my_data_1min"
    protected.mkdir(parents=True)
    minute.mkdir()
    (protected / "KEEP").write_text("x", encoding="utf-8")
    cfg = BuildConfig(
        lake_root=tmp_path / "front",
        staging_dir=tmp_path / "staging",
        qlib_dir=tmp_path / "qlib_data" / "my_data_etf",
        meta_dir=tmp_path / "meta",
        protected=(protected, minute),
        dry_run=True,
        verify=False,
    )
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return cfg, protected


def _spies():
    calls = {"wipe": [], "stage": 0, "dump": 0}

    def wipe(path: Path) -> None:
        calls["wipe"].append(path)

    def stage(_cfg: BuildConfig) -> None:
        calls["stage"] += 1

    def dump(_cfg: BuildConfig) -> None:
        calls["dump"] += 1

    return calls, wipe, stage, dump


def test_refuses_protected_paths_before_wipe(tmp_path: Path):
    cfg, protected = _cfg(tmp_path, wipe_qlib_dir=True, dry_run=False)
    calls, wipe, stage, dump = _spies()
    targets = [
        protected,
        protected / "features",
        protected.parent,
        protected.parent / "my_data_1min",
    ]
    link = tmp_path / "alias_my_data"
    subprocess.check_call(["cmd", "/c", "mklink", "/J", str(link), str(protected)])
    targets.append(link)
    for target in targets:
        cfg.qlib_dir = target
        with pytest.raises(BuildEtfError):
            execute(cfg, stage_fn=stage, dump_fn=dump, wipe_fn=wipe)
    assert calls == {"wipe": [], "stage": 0, "dump": 0}
    assert (protected / "KEEP").read_text(encoding="utf-8") == "x"


def test_etf_dir_is_not_a_prefix_of_my_data(tmp_path: Path):
    cfg, _protected = _cfg(tmp_path)
    calls, wipe, stage, dump = _spies()
    assert execute(cfg, stage_fn=stage, dump_fn=dump, wipe_fn=wipe) == 0
    assert calls == {"wipe": [], "stage": 0, "dump": 0}


def test_workers_must_be_eight(tmp_path: Path):
    cfg, _protected = _cfg(tmp_path, max_workers=16, wipe_qlib_dir=True, dry_run=False)
    calls, wipe, stage, dump = _spies()
    with pytest.raises(BuildEtfError):
        execute(cfg, stage_fn=stage, dump_fn=dump, wipe_fn=wipe)
    assert calls["wipe"] == []
    assert calls["dump"] == 0


def _write_symbol(path: Path, dates: list[str], *, close: float = 10.0, vwap: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    price = close
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "symbol": "SH510300",
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 100,
            "amount": price * 100 * 100,
            "vwap": price if vwap is None else vwap,
        }
    )
    frame.to_parquet(path, index=False)


def test_extra_calendar_date_stops_before_dump(tmp_path: Path):
    cfg, _protected = _cfg(tmp_path, dry_run=False)
    staging = cfg.staging_dir
    _write_symbol(staging / "sh510300.parquet", ["2020-01-02", "2026-10-13"])
    _write_symbol(staging / "sz159915.parquet", ["2020-01-02", "2020-01-04"])
    calls, wipe, stage, dump = _spies()
    with pytest.raises(BuildEtfError, match="510300"):
        execute(cfg, stage_fn=stage, dump_fn=dump, wipe_fn=wipe)
    assert calls["dump"] == 0
    assert calls["wipe"] == []


def test_weekend_in_reference_calendar_stops_before_dump(tmp_path: Path):
    cfg, _protected = _cfg(tmp_path, dry_run=False)
    _write_symbol(cfg.staging_dir / "sh510300.parquet", ["2020-01-02", "2020-01-04", "2026-10-13"])
    calls, wipe, stage, dump = _spies()
    with pytest.raises(BuildEtfError, match="非交易日"):
        execute(cfg, stage_fn=stage, dump_fn=dump, wipe_fn=wipe)
    assert calls["dump"] == 0


def test_vwap_drift_stops_before_dump(tmp_path: Path):
    cfg, _protected = _cfg(tmp_path, dry_run=False)
    _write_symbol(cfg.staging_dir / "sh510300.parquet", ["2020-01-02", "2026-10-13"], close=10.0, vwap=9.0)
    calls, wipe, stage, dump = _spies()
    with pytest.raises(BuildEtfError, match="VWAP"):
        execute(cfg, stage_fn=stage, dump_fn=dump, wipe_fn=wipe)
    assert calls["dump"] == 0


def test_dump_argv_is_dump_all_with_eight_workers(tmp_path: Path):
    cfg, _protected = _cfg(tmp_path)
    argv = dump_argv(cfg)
    assert "dump_all" in argv
    assert "dump_update" not in argv
    assert f"--max_workers={REQUIRED_WORKERS}" in argv
    assert "--exclude_fields=symbol" in argv


def test_etf_full_allows_gaps_and_drops_early_end():
    assert is_etf_full({"start": "2021-06-01", "end": "2026-10-13", "bars": 800})
    assert not is_etf_full({"start": "2020-01-02", "end": "2026-09-04", "bars": 1539})
    assert not is_etf_full({"start": "2023-01-04", "end": "2026-10-13", "bars": 900})
    assert not is_etf_full({"start": "2020-01-02", "end": "2026-10-13", "bars": 400})
    summary = summarize_ratios([0.0, 0.1, 0.2])
    assert summary["n"] == 3
    assert abs(summary["max"] - 0.2) < 1e-9
    assert "幸存者偏差" in SURVIVORSHIP_NOTE
