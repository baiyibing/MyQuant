# -*- coding: utf-8 -*-
"""QL11 receipt schema for qlib 1-min incremental refresh (offline harness pin).

Stdlib only — no qlib / dump_bin / pandas / pyarrow imports here, so the
data-free CI job can validate the schema without the qlib toolchain.

The receipt freezes what a 核对 (audit) of a later real M5 host increment must
be able to read: daily day.txt fingerprint invariance, 1min calendar advance,
existing bar preservation, and "no market / pred.pkl write" guarantees from
``refresh_mydata_1min.py`` (see my_docs/提示词-qlib-1min-bin刷新.md).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Union

RECEIPT_SCHEMA_VERSION = "ql11.1min.v1"
AUDIT_ID = "QL11"
RECEIPT_MODES = frozenset({"incremental", "rebuild", "noop"})

REQUIRED_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "audit_id",
        "mode",
        "qlib_1min_dir",
        "daily_dir",
        "daily_day_txt_sha256_before",
        "daily_day_txt_sha256_after",
        "daily_day_txt_unchanged",
        "minute_calendar_len_before",
        "minute_calendar_len_after",
        "minute_calendar_last_before",
        "minute_calendar_last_after",
        "minute_calendar_advanced",
        "bars_appended",
        "symbols_touched",
        "existing_minute_bars_preserved",
        "pred_pkl_untouched",
        "market_write_performed",
    }
)

_BOOL_FIELDS = frozenset(
    {
        "daily_day_txt_unchanged",
        "minute_calendar_advanced",
        "existing_minute_bars_preserved",
        "pred_pkl_untouched",
        "market_write_performed",
    }
)
_INT_FIELDS = frozenset(
    {
        "minute_calendar_len_before",
        "minute_calendar_len_after",
        "bars_appended",
        "symbols_touched",
    }
)
_STR_FIELDS = frozenset(
    {
        "schema_version",
        "audit_id",
        "mode",
        "qlib_1min_dir",
        "daily_dir",
        "daily_day_txt_sha256_before",
        "daily_day_txt_sha256_after",
    }
)
_STR_OR_NONE_FIELDS = frozenset({"minute_calendar_last_before", "minute_calendar_last_after"})

_ERR_PREFIX = "QL11 1min increment receipt invalid:"

StateSnapshot = Mapping[str, Union[int, str, None]]


def sha256_file(path: Path | str) -> str:
    """Hex sha256 of file bytes, "" when missing — same sha half as daily_calendar_fingerprint."""
    p = Path(path)
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_minute_calendar(qlib_dir: Path | str) -> list[str]:
    path = Path(qlib_dir) / "calendars" / "1min.txt"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _feature_dir_name(symbol: str) -> str:
    """SZ000001 / 000001.SZ → sz000001 (qlib code_to_fname convention for A-shares)."""
    text = str(symbol).strip().upper()
    if "." in text:
        bare, exch = text.split(".", 1)
        text = f"{exch}{bare}"
    return text.lower()


def count_minute_bars(qlib_dir: Path | str, symbol: str) -> int:
    """Value-float count in features/<sym>/close.1min.bin (header index + values)."""
    path = Path(qlib_dir) / "features" / _feature_dir_name(symbol) / "close.1min.bin"
    if not path.exists():
        return 0
    size = path.stat().st_size
    if size % 4:
        raise ValueError(f"unaligned 1min bin (size {size}): {path}")
    return max(0, size // 4 - 1)


def snapshot_1min_state(qlib_dir: Path | str, probe_symbol: str | None = None) -> dict:
    """Measurable before/after state of a 1min qlib dir (calendar + optional probe bars)."""
    lines = read_minute_calendar(qlib_dir)
    return {
        "minute_calendar_len": len(lines),
        "minute_calendar_last": lines[-1] if lines else None,
        "probe_symbol": str(probe_symbol).strip().upper() if probe_symbol else None,
        "probe_bars": count_minute_bars(qlib_dir, probe_symbol) if probe_symbol else None,
    }


def build_receipt(
    *,
    mode: str,
    qlib_1min_dir: Path | str,
    daily_dir: Path | str,
    daily_day_txt_sha256_before: str,
    daily_day_txt_sha256_after: str,
    state_before: StateSnapshot,
    state_after: StateSnapshot,
    bars_appended: int | None = None,
    symbols_touched: int = 0,
    pred_pkl_untouched: bool = True,
    market_write_performed: bool = False,
) -> dict:
    """Assemble a receipt from explicit before/after measurements (pure, no fs reads).

    ``state_before`` / ``state_after`` come from :func:`snapshot_1min_state`;
    ``bars_appended`` defaults to net minute-calendar growth.
    """
    if mode not in RECEIPT_MODES:
        raise ValueError(f"{_ERR_PREFIX} unknown mode {mode!r}")
    len_before = int(state_before["minute_calendar_len"])
    len_after = int(state_after["minute_calendar_len"])
    sha_before = str(daily_day_txt_sha256_before)
    sha_after = str(daily_day_txt_sha256_after)
    bars_before = state_before.get("probe_bars")
    bars_after = state_after.get("probe_bars")
    preserved = True if bars_before is None else int(bars_after) >= int(bars_before)
    if bars_appended is None:
        bars_appended = max(0, len_after - len_before)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "qlib_1min_dir": str(qlib_1min_dir),
        "daily_dir": str(daily_dir),
        "daily_day_txt_sha256_before": sha_before,
        "daily_day_txt_sha256_after": sha_after,
        "daily_day_txt_unchanged": sha_after == sha_before,
        "minute_calendar_len_before": len_before,
        "minute_calendar_len_after": len_after,
        "minute_calendar_last_before": state_before.get("minute_calendar_last"),
        "minute_calendar_last_after": state_after.get("minute_calendar_last"),
        "minute_calendar_advanced": len_after > len_before,
        "bars_appended": int(bars_appended),
        "symbols_touched": int(symbols_touched),
        "probe_symbol": state_before.get("probe_symbol") or state_after.get("probe_symbol"),
        "probe_bars_before": None if bars_before is None else int(bars_before),
        "probe_bars_after": None if bars_after is None else int(bars_after),
        "existing_minute_bars_preserved": preserved,
        "pred_pkl_untouched": bool(pred_pkl_untouched),
        "market_write_performed": bool(market_write_performed),
    }
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: Mapping) -> None:
    """Raise ValueError (stable prefix) on any missing/mistyped required field."""
    if not isinstance(receipt, Mapping):
        raise ValueError(f"{_ERR_PREFIX} expected a mapping, got {type(receipt).__name__}")
    problems: list[str] = []
    for field in sorted(REQUIRED_RECEIPT_FIELDS):
        if field not in receipt:
            problems.append(f"{field}: missing")
            continue
        value = receipt[field]
        if field in _BOOL_FIELDS and not isinstance(value, bool):
            problems.append(f"{field}: expected bool, got {type(value).__name__}")
        elif field in _INT_FIELDS and (not isinstance(value, int) or isinstance(value, bool)):
            problems.append(f"{field}: expected int, got {type(value).__name__}")
        elif field in _STR_FIELDS and not isinstance(value, str):
            problems.append(f"{field}: expected str, got {type(value).__name__}")
        elif field in _STR_OR_NONE_FIELDS and value is not None and not isinstance(value, str):
            problems.append(f"{field}: expected str or None, got {type(value).__name__}")
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        problems.append(f"schema_version: expected {RECEIPT_SCHEMA_VERSION!r}, got {receipt.get('schema_version')!r}")
    if receipt.get("audit_id") != AUDIT_ID:
        problems.append(f"audit_id: expected {AUDIT_ID!r}, got {receipt.get('audit_id')!r}")
    if receipt.get("mode") not in RECEIPT_MODES:
        problems.append(f"mode: expected one of {sorted(RECEIPT_MODES)}, got {receipt.get('mode')!r}")
    if problems:
        raise ValueError(f"{_ERR_PREFIX} " + "; ".join(problems))


def write_receipt(path: Path | str, receipt: Mapping) -> Path:
    validate_receipt(receipt)
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def read_receipt(path: Path | str) -> dict:
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_receipt(receipt)
    return receipt
