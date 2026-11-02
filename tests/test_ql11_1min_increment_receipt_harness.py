# -*- coding: utf-8 -*-
"""QL11 offline 1min-increment receipt harness — schema pin, data-free.

Two paths per the QL11 knife:

- qlib-free (always runs, incl. the CI ``data-staging`` job with only
  pytest/numpy/pandas/pyarrow): schema validation, day.txt sha stability, and a
  SIMULATED increment (one calendar line + one bin float appended by hand).
- qlib-gated: the real ``append_new_1min_bars`` from
  ``qlib_scripts/refresh_mydata_1min.py`` drives the before/after measurements;
  ``pytest.importorskip`` keeps environments without qlib/tqdm green.

No ~/.qlib access, no lake reads, no M5 pulls — tmp_path fixtures only.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlib_scripts.qlib_1min_increment_receipt import (
    AUDIT_ID,
    RECEIPT_MODES,
    RECEIPT_SCHEMA_VERSION,
    REQUIRED_RECEIPT_FIELDS,
    build_receipt,
    count_minute_bars,
    read_receipt,
    sha256_file,
    snapshot_1min_state,
    validate_receipt,
    write_receipt,
)

EXPECTED_FIELDS = frozenset(
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

OLD_MINUTES = ["2026-09-18 09:30:00", "2026-09-18 09:31:00"]
NEW_MINUTE = "2026-09-18 09:32:00"


def _synthetic_receipt(**overrides) -> dict:
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "mode": "incremental",
        "qlib_1min_dir": "/tmp/my_data_1min",
        "daily_dir": "/tmp/my_data",
        "daily_day_txt_sha256_before": "a" * 64,
        "daily_day_txt_sha256_after": "a" * 64,
        "daily_day_txt_unchanged": True,
        "minute_calendar_len_before": 2,
        "minute_calendar_len_after": 3,
        "minute_calendar_last_before": OLD_MINUTES[-1],
        "minute_calendar_last_after": NEW_MINUTE,
        "minute_calendar_advanced": True,
        "bars_appended": 1,
        "symbols_touched": 1,
        "existing_minute_bars_preserved": True,
        "pred_pkl_untouched": True,
        "market_write_performed": False,
    }
    receipt.update(overrides)
    return receipt


def _make_daily(tmp_path: Path) -> tuple[Path, Path]:
    daily = tmp_path / "my_data"
    (daily / "calendars").mkdir(parents=True)
    day_txt = daily / "calendars" / "day.txt"
    day_txt.write_text("2026-09-15\n2026-09-16\n2026-09-18\n", encoding="utf-8")
    return daily, day_txt


def _make_1min_tree(tmp_path: Path, minutes: list[str]) -> Path:
    qlib_dir = tmp_path / "my_data_1min"
    (qlib_dir / "calendars").mkdir(parents=True, exist_ok=True)
    (qlib_dir / "calendars" / "1min.txt").write_text("\n".join(minutes) + "\n", encoding="utf-8")
    return qlib_dir


def _write_close_bin(bin_path: Path, start_index: float, values: list[float]) -> None:
    """qlib bin shape: header float (start index) + one float per bar."""
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path.write_bytes(struct.pack(f"<{len(values) + 1}f", start_index, *values))


def _write_stage_parquet(staging: Path, code: str, times: list[str], close: float) -> Path:
    staging.mkdir(parents=True, exist_ok=True)
    dest = staging / f"{code.lower()}.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(times),
            "symbol": code.upper(),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1,
            "amount": 10.0,
        }
    ).to_parquet(dest, index=False)
    return dest


def _build(daily: Path, qlib_dir: Path, *, sha_before: str, sha_after: str, before: dict, after: dict, **kw) -> dict:
    return build_receipt(
        qlib_1min_dir=qlib_dir,
        daily_dir=daily,
        daily_day_txt_sha256_before=sha_before,
        daily_day_txt_sha256_after=sha_after,
        state_before=before,
        state_after=after,
        **kw,
    )


# --- 1) schema pin -----------------------------------------------------------


def test_required_field_set_pinned():
    assert set(REQUIRED_RECEIPT_FIELDS) == EXPECTED_FIELDS
    assert RECEIPT_SCHEMA_VERSION == "ql11.1min.v1"
    assert AUDIT_ID == "QL11"
    assert RECEIPT_MODES == frozenset({"incremental", "rebuild", "noop"})


def test_validate_accepts_complete_receipt():
    for mode in sorted(RECEIPT_MODES):
        validate_receipt(_synthetic_receipt(mode=mode))


@pytest.mark.parametrize("field", sorted(EXPECTED_FIELDS))
def test_validate_rejects_each_missing_field(field):
    receipt = _synthetic_receipt()
    del receipt[field]
    with pytest.raises(ValueError, match="QL11 1min increment receipt invalid"):
        validate_receipt(receipt)


def test_validate_rejects_wrong_types_and_constants():
    wrong_types = (
        ("daily_day_txt_unchanged", 1),
        ("minute_calendar_advanced", "yes"),
        ("bars_appended", True),
        ("symbols_touched", "3"),
        ("minute_calendar_len_after", 3.0),
        ("qlib_1min_dir", Path("/tmp")),
        ("daily_dir", None),
        ("minute_calendar_last_after", 99),
    )
    for field, bad in wrong_types:
        with pytest.raises(ValueError, match=field):
            validate_receipt(_synthetic_receipt(**{field: bad}))
    wrong_constants = (
        ("schema_version", "ql11.1min.v2"),
        ("audit_id", "QL12"),
        ("mode", "partial"),
        ("mode", None),
    )
    for field, bad in wrong_constants:
        with pytest.raises(ValueError, match=field):
            validate_receipt(_synthetic_receipt(**{field: bad}))


# --- 2) day.txt hash stability -----------------------------------------------


def test_day_txt_sha_stable_when_untouched(tmp_path: Path):
    daily, day_txt = _make_daily(tmp_path)
    sha = sha256_file(day_txt)
    assert sha == hashlib.sha256(day_txt.read_bytes()).hexdigest()
    assert len(sha) == 64

    qlib_dir = _make_1min_tree(tmp_path, OLD_MINUTES)
    _write_close_bin(qlib_dir / "features" / "sz000001" / "close.1min.bin", 0.0, [10.0, 10.1])
    before = snapshot_1min_state(qlib_dir, probe_symbol="SZ000001")
    (qlib_dir / "calendars" / "1min.txt").write_text(
        "\n".join(OLD_MINUTES + [NEW_MINUTE]) + "\n", encoding="utf-8"
    )
    after = snapshot_1min_state(qlib_dir, probe_symbol="SZ000001")

    receipt = _build(
        daily,
        qlib_dir,
        sha_before=sha,
        sha_after=sha256_file(day_txt),
        before=before,
        after=after,
        mode="incremental",
        bars_appended=1,
        symbols_touched=1,
    )
    assert receipt["daily_day_txt_unchanged"] is True
    assert receipt["daily_day_txt_sha256_before"] == receipt["daily_day_txt_sha256_after"] == sha


def test_day_txt_rewrite_detected(tmp_path: Path):
    daily, day_txt = _make_daily(tmp_path)
    sha_before = sha256_file(day_txt)
    day_txt.write_text("2026-09-15\n2026-09-16\n2026-09-18\n2026-09-19\n", encoding="utf-8")
    sha_after = sha256_file(day_txt)
    assert sha_before != sha_after

    qlib_dir = _make_1min_tree(tmp_path, OLD_MINUTES)
    state = snapshot_1min_state(qlib_dir)
    receipt = _build(
        daily,
        qlib_dir,
        sha_before=sha_before,
        sha_after=sha_after,
        before=state,
        after=state,
        mode="incremental",
    )
    assert receipt["daily_day_txt_unchanged"] is False
    assert receipt["daily_day_txt_sha256_before"] != receipt["daily_day_txt_sha256_after"]
    validate_receipt(receipt)


def test_sha256_file_missing_is_empty_string(tmp_path: Path):
    assert sha256_file(tmp_path / "nope.txt") == ""


# --- 3) minute calendar advances + old bars preserved -------------------------


def test_simulated_increment_advances_calendar_and_preserves_bars(tmp_path: Path):
    """SIMULATED path (qlib-free): calendar line + bin float appended by hand.

    The real ``append_new_1min_bars`` path is covered by
    ``test_real_append_new_1min_bars_receipt`` below, gated on qlib availability.
    """
    daily, day_txt = _make_daily(tmp_path)
    qlib_dir = _make_1min_tree(tmp_path, OLD_MINUTES)
    bin_path = qlib_dir / "features" / "sz000001" / "close.1min.bin"
    _write_close_bin(bin_path, 0.0, [10.0, 10.1])
    _write_stage_parquet(tmp_path / "staging", "SZ000001", [NEW_MINUTE], 10.2)

    before = snapshot_1min_state(qlib_dir, probe_symbol="SZ000001")
    assert before["minute_calendar_len"] == 2
    assert before["probe_bars"] == 2

    (qlib_dir / "calendars" / "1min.txt").write_text(
        "\n".join(OLD_MINUTES + [NEW_MINUTE]) + "\n", encoding="utf-8"
    )
    with bin_path.open("ab") as fh:  # append-only: never truncate existing minutes
        fh.write(struct.pack("<f", 10.2))

    after = snapshot_1min_state(qlib_dir, probe_symbol="SZ000001")
    receipt = _build(
        daily,
        qlib_dir,
        sha_before=sha256_file(day_txt),
        sha_after=sha256_file(day_txt),
        before=before,
        after=after,
        mode="incremental",
        bars_appended=1,
        symbols_touched=1,
    )
    validate_receipt(receipt)
    assert receipt["minute_calendar_advanced"] is True
    assert receipt["minute_calendar_len_before"] == 2
    assert receipt["minute_calendar_len_after"] == 3
    assert receipt["minute_calendar_last_before"] == OLD_MINUTES[-1]
    assert receipt["minute_calendar_last_after"] == NEW_MINUTE
    assert receipt["existing_minute_bars_preserved"] is True
    assert receipt["probe_bars_before"] == 2
    assert receipt["probe_bars_after"] == 3
    assert receipt["bars_appended"] == 1
    assert count_minute_bars(qlib_dir, "SZ000001") == 3


def test_real_append_new_1min_bars_receipt(tmp_path: Path):
    """REAL path: ``append_new_1min_bars`` mutates the tree; receipt measures around it.

    Skipped wherever the qlib toolchain (qlib/tqdm/dump_bin) is absent — e.g. the
    CI ``data-staging`` job — so that job stays green on the qlib-free tests.
    """
    pytest.importorskip("qlib")
    pytest.importorskip("tqdm")
    scripts = ROOT / "qlib_scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from refresh_mydata_1min import append_new_1min_bars

    daily, day_txt = _make_daily(tmp_path)
    qlib_dir = _make_1min_tree(tmp_path, OLD_MINUTES)
    (qlib_dir / "instruments").mkdir()
    (qlib_dir / "instruments" / "all.txt").write_text(
        "SZ000001\t2026-09-18 09:30:00\t2026-09-18 09:31:00\n", encoding="utf-8"
    )
    _write_close_bin(qlib_dir / "features" / "sz000001" / "close.1min.bin", 0.0, [10.0, 10.1])
    staging_inc = tmp_path / "inc"
    staging_full = tmp_path / "full"
    staging_full.mkdir()
    _write_stage_parquet(staging_inc, "SZ000001", [NEW_MINUTE], 10.2)

    before = snapshot_1min_state(qlib_dir, probe_symbol="SZ000001")
    new_only = [pd.Timestamp(NEW_MINUTE)]
    full_cal = [pd.Timestamp(x) for x in OLD_MINUTES] + new_only
    n = append_new_1min_bars(staging_inc, staging_full, qlib_dir, new_only, full_cal)
    after = snapshot_1min_state(qlib_dir, probe_symbol="SZ000001")

    receipt = _build(
        daily,
        qlib_dir,
        sha_before=sha256_file(day_txt),
        sha_after=sha256_file(day_txt),
        before=before,
        after=after,
        mode="incremental",
        bars_appended=len(new_only),
        symbols_touched=n,
    )
    validate_receipt(receipt)
    assert n == 1
    assert receipt["minute_calendar_advanced"] is True
    assert receipt["minute_calendar_last_after"] == NEW_MINUTE
    assert receipt["existing_minute_bars_preserved"] is True
    assert receipt["probe_bars_before"] == 2
    assert receipt["probe_bars_after"] == 3
    assert receipt["bars_appended"] == 1
    assert receipt["symbols_touched"] == 1
    assert receipt["daily_day_txt_unchanged"] is True


def test_count_minute_bars_aliases_and_guards(tmp_path: Path):
    qlib_dir = _make_1min_tree(tmp_path, OLD_MINUTES)
    bin_path = qlib_dir / "features" / "sz000001" / "close.1min.bin"
    _write_close_bin(bin_path, 0.0, [10.0, 10.1])
    assert count_minute_bars(qlib_dir, "SZ000001") == 2
    assert count_minute_bars(qlib_dir, "000001.SZ") == 2
    assert count_minute_bars(qlib_dir, "sz000001") == 2
    assert count_minute_bars(qlib_dir, "SH600000") == 0
    bin_path.write_bytes(b"\x00\x00")  # unaligned
    with pytest.raises(ValueError, match="unaligned 1min bin"):
        count_minute_bars(qlib_dir, "SZ000001")


# --- 4) receipt round-trip ----------------------------------------------------


def test_write_read_roundtrip(tmp_path: Path):
    receipt = _synthetic_receipt()
    dest = write_receipt(tmp_path / "nested" / "receipt.json", receipt)
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert text.endswith("\n")
    loaded = json.loads(text)
    validate_receipt(loaded)
    for field in sorted(EXPECTED_FIELDS):
        assert loaded[field] == receipt[field]
    assert read_receipt(dest) == loaded


def test_write_receipt_refuses_invalid(tmp_path: Path):
    dest = tmp_path / "receipt.json"
    bad = _synthetic_receipt()
    del bad["mode"]
    with pytest.raises(ValueError, match="QL11 1min increment receipt invalid"):
        write_receipt(dest, bad)
    assert not dest.exists()


def test_build_receipt_rejects_unknown_mode(tmp_path: Path):
    daily, _ = _make_daily(tmp_path)
    qlib_dir = _make_1min_tree(tmp_path, OLD_MINUTES)
    state = snapshot_1min_state(qlib_dir)
    with pytest.raises(ValueError, match="unknown mode"):
        _build(
            daily,
            qlib_dir,
            sha_before="a" * 64,
            sha_after="a" * 64,
            before=state,
            after=state,
            mode="partial",
        )


# --- 5) no market write / no pred.pkl ----------------------------------------


def test_noop_receipt_no_market_write_no_pred_pkl(tmp_path: Path):
    daily, day_txt = _make_daily(tmp_path)
    qlib_dir = _make_1min_tree(tmp_path, OLD_MINUTES)
    state = snapshot_1min_state(qlib_dir, probe_symbol="SZ000001")
    receipt = _build(
        daily,
        qlib_dir,
        sha_before=sha256_file(day_txt),
        sha_after=sha256_file(day_txt),
        before=state,
        after=state,
        mode="noop",
    )
    validate_receipt(receipt)
    assert receipt["mode"] == "noop"
    assert receipt["market_write_performed"] is False
    assert receipt["pred_pkl_untouched"] is True
    assert receipt["bars_appended"] == 0
    assert receipt["minute_calendar_advanced"] is False
    assert receipt["existing_minute_bars_preserved"] is True
    assert list(tmp_path.rglob("pred.pkl")) == []
