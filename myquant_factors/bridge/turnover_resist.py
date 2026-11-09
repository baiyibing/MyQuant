# -*- coding: utf-8 -*-
"""Turnover-resist Rust 桥接：PyO3 FFI 主通道，CLI 子进程 fallback。

plan-main v22 Phase A1 交付项：替代 CLI subprocess.run 调用，
消除 39ms 子进程启动开销和临时 CSV 文件读写。

用法::

    from myquant_factors.bridge.turnover_resist import compute_turnover_resist

    results = compute_turnover_resist(
        date="20260606",
        # data_dir 默认 resolve_parquet_container()；DuckDB 仍在工作区
    )
    # returns list[dict] with keys: stock_code, stock_name, date, close,
    #   cyqk_T, cyqk_T_1, profit_chip_diff, turnover, turnover_resistance,
    #   turnover_free, turnover_resistance_free, circulating_capital,
    #   freeFloatCapital, bb_upper, bb_middle, bb_lower, bb_position, bb_width
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from myquant_factors._runtime import get_logger

_log = get_logger("turnover_resist_bridge")

# ---------------------------------------------------------------------------
# PyO3 FFI (primary path)
# ---------------------------------------------------------------------------

_FFI_MODULE: Any = None
_FFI_LOAD_ERROR: Optional[str] = None


def _load_ffi_module() -> Any:
    """Lazy-load the PyO3 extension module 'turnover_resist'.

    Returns the module on success, None if not installed (caller should
    fall back to CLI subprocess).
    """
    global _FFI_MODULE, _FFI_LOAD_ERROR
    if _FFI_MODULE is not None:
        return _FFI_MODULE
    if _FFI_LOAD_ERROR:
        return None
    try:
        import turnover_resist as mod  # type: ignore[import-not-found]

        _FFI_MODULE = mod
        _log.info("turnover_resist PyO3 FFI loaded")
        return mod
    except ImportError as exc:
        _FFI_LOAD_ERROR = str(exc)
        _log.warning(
            "turnover_resist PyO3 not installed; falling back to CLI subprocess (%s)",
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def circulating_capital_asof(stock_code: str, dates, *, history=None):
    """Daily backward-asof circulating_capital; never fall back to a snapshot.

    Missing/nonpositive per-day values stay NaN for Rust's window-local failure
    contract. A missing file or malformed table fails visibly. ``history`` is
    an optional preloaded free_float_shares table for batch research callers.
    """
    import numpy as np
    import pandas as pd

    from myquant_factors._runtime import resolve_source_parquet

    if dates is None:
        raise ValueError("explicit asof dates are required; date=None is forbidden")
    if history is None:
        history = pd.read_parquet(resolve_source_parquet("free_float_shares.parquet"))
    required = {"stock_code", "m_timetag", "circulating_capital"}
    if not required.issubset(history.columns):
        raise ValueError(f"free_float_shares missing columns: {sorted(required - set(history.columns))}")
    # Normalize both merge keys to datetime64[ns] so CI pandas (strict ms vs us)
    # does not raise MergeError on free_float history vs caller dates.
    target = pd.DataFrame({
        "day": pd.to_datetime(pd.DatetimeIndex(dates).normalize()).astype("datetime64[ns]"),
    })
    if target["day"].isna().any():
        raise ValueError("asof dates must not contain NaT")
    target["order"] = np.arange(len(target))
    subset = history.loc[history["stock_code"] == stock_code,
                         ["m_timetag", "circulating_capital"]].copy()
    if subset.empty or target.empty:
        return np.full(len(target), np.nan)
    subset["day"] = pd.to_datetime(subset.pop("m_timetag")).dt.normalize().astype("datetime64[ns]")
    if subset["day"].isna().any():
        raise ValueError("free_float_shares m_timetag contains NaT")
    subset = subset.sort_values("day", kind="stable").drop_duplicates("day", keep="last")
    merged = pd.merge_asof(target.sort_values("day"), subset, on="day", direction="backward")
    values = pd.to_numeric(merged.sort_values("order")["circulating_capital"],
                           errors="raise").to_numpy(dtype=float, copy=True)
    values[~np.isfinite(values) | (values <= 0)] = np.nan
    return values


def compute_turnover_resist(
    date: str,
    *,
    data_dir: str = "",
    window: int = 1000,
    step: float = 0.01,
    sort_by: str = "circulating",
    free_float_policy: str = "warn-zero",
    target_date_policy: str = "strict",
    bb_ddof: int = 1,
    max_grid_points: int = 250_000,
    prefer_ffi: bool = True,
) -> List[Dict[str, Any]]:
    """Compute turnover resistance for all stocks on *date*.

    Parameters match the Rust CLI arguments (see ``turnover-resist --help``).
    Returns a list of dicts (one per stock), sorted by |turnover_resistance|
    descending.

    *prefer_ffi* (default True): try PyO3 FFI first, fall back to CLI
    subprocess if the extension module is not installed.
    """
    if not data_dir:
        data_dir = _default_data_dir()

    if prefer_ffi:
        results = _ffi_compute(
            date=date,
            data_dir=data_dir,
            window=window,
            step=step,
            sort_by=sort_by,
            free_float_policy=free_float_policy,
            target_date_policy=target_date_policy,
            bb_ddof=bb_ddof,
            max_grid_points=max_grid_points,
        )
        if results is not None:
            return results

    return _cli_compute(
        date=date,
        data_dir=data_dir,
        window=window,
        step=step,
        sort_by=sort_by,
        free_float_policy=free_float_policy,
        target_date_policy=target_date_policy,
        bb_ddof=bb_ddof,
        max_grid_points=max_grid_points,
    )


# ---------------------------------------------------------------------------
# Internal: PyO3 FFI path
# ---------------------------------------------------------------------------

def _ffi_compute(**kwargs: Any) -> Optional[List[Dict[str, Any]]]:
    mod = _load_ffi_module()
    if mod is None:
        return None
    try:
        json_str: str = mod.compute_turnover_resist(
            kwargs["date"],
            kwargs["window"],
            kwargs["step"],
            kwargs["data_dir"],
            kwargs["sort_by"],
            kwargs["free_float_policy"],
            kwargs["target_date_policy"],
            kwargs["bb_ddof"],
            kwargs["max_grid_points"],
        )
        results: List[Dict[str, Any]] = json.loads(json_str)
        return results
    except Exception as exc:
        _log.error("PyO3 FFI compute failed: %s; falling back to CLI", exc)
        return None


# ---------------------------------------------------------------------------
# Internal: CLI subprocess fallback
# ---------------------------------------------------------------------------

def _cli_compute(**kwargs: Any) -> List[Dict[str, Any]]:
    date = kwargs["date"]
    data_dir = kwargs["data_dir"]
    output_path = Path(data_dir) / f"_turnover_resist_{date}.csv"
    exe = _find_exe()

    cmd: List[str] = [
        str(exe),
        "--date", date,
        "--data-dir", data_dir,
        "--window", str(kwargs["window"]),
        "--step", str(kwargs["step"]),
        "--sort-by", kwargs["sort_by"],
        "--free-float-policy", kwargs["free_float_policy"],
        "--target-date-policy", kwargs["target_date_policy"],
        "--bb-ddof", str(kwargs["bb_ddof"]),
        "--max-grid-points", str(kwargs["max_grid_points"]),
        "--output", str(output_path),
    ]

    _log.info("Running CLI: %s", " ".join(cmd))
    # Force UTF-8 pipes on Windows (default locale may be gbk and blow up on CLI logs).
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"turnover-resist CLI failed (exit {proc.returncode}):\n"
            f"  stdout: {proc.stdout}\n  stderr: {proc.stderr}"
        )

    import csv

    results: List[Dict[str, Any]] = []
    # Rust CLI writes UTF-8 BOM CSV; utf-8-sig strips BOM so fieldnames stay "stock_code"
    # (plain utf-8 yields "\ufeffstock_code" → normalize_ffi_row raises "FFI row missing stock_code").
    with open(output_path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            # Defense-in-depth: strip any residual BOM on keys.
            if any(isinstance(k, str) and k.startswith("\ufeff") for k in row):
                row = {
                    (k.lstrip("\ufeff") if isinstance(k, str) else k): v
                    for k, v in row.items()
                }
            for key in (
                "close", "cyqk_T", "cyqk_T_1", "profit_chip_diff",
                "turnover", "turnover_resistance", "turnover_free",
                "turnover_resistance_free", "circulating_capital",
                "freeFloatCapital",
                "bb_upper", "bb_middle", "bb_lower", "bb_position", "bb_width",
            ):
                try:
                    row[key] = float(row[key])
                except (KeyError, ValueError):
                    continue  # field missing or non-numeric; skip conversion
            results.append(row)
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_exe() -> Path:
    """Locate the turnover-resist.exe binary.

    Checks (in order):
      1. TURNOVER_RESIST_EXE (an invalid explicit override fails immediately)
      2. CARGO_TARGET_DIR / release[-fast] / turnover-resist.exe
      3. MyQuant package ``rust/turnover-resist/target/release[-fast]``
    """
    import os

    env = os.getenv("TURNOVER_RESIST_EXE")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise FileNotFoundError(f"TURNOVER_RESIST_EXE does not name an existing file: {p}")
    from myquant_factors._runtime import rust_source_root
    project = rust_source_root()
    names = ("turnover-resist.exe", "turnover-resist")
    roots: list[Path] = []
    cargo_target = str(os.getenv("CARGO_TARGET_DIR") or "").strip()
    if cargo_target:
        roots.append(Path(cargo_target))
    roots.append(project / "target")
    for root in roots:
        for profile in ("release", "release-fast"):
            for name in names:
                p = root / profile / name
                if p.is_file():
                    return p
    raise FileNotFoundError(
        "turnover-resist.exe not found. Set TURNOVER_RESIST_EXE or CARGO_TARGET_DIR, "
        "or build with: cd myquant_factors/rust/turnover-resist && cargo build --release"
    )


def _default_data_dir() -> str:
    from myquant_factors._runtime import resolve_turnover_resist_parquet_root

    return str(resolve_turnover_resist_parquet_root())


# ---------------------------------------------------------------------------
# Module-level availability check
# ---------------------------------------------------------------------------

def is_ffi_available() -> bool:
    """Return True if the PyO3 extension module can be loaded."""
    return _load_ffi_module() is not None


def bridge_mode() -> str:
    """Return the active bridge mode: 'pyo3_ffi' or 'cli_fallback'."""
    return "pyo3_ffi" if is_ffi_available() else "cli_fallback"
