import hashlib
import json
from pathlib import Path

import pytest

from myquant_contract import build_signal_bundle, canonical_json_bytes, validate_signal_bundle


def _row(asof="2026-03-02", target="2026-03-05"):
    payload = b"000001\n"
    return {
        "signal_asof": asof,
        "target_session": target,
        "pool_file": target.replace("-", "") + ".csv",
        "pool_md5": hashlib.md5(payload).hexdigest(),
        "pool_sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_pred_minus_one_omits_nothing_and_rejects_equal_dates():
    rows = [_row(), _row("2026-03-05", "2026-03-09")]
    bundle = build_signal_bundle(rows)
    assert bundle["rows"] == rows
    assert bundle["rows"][0] is not rows[0]
    validate_signal_bundle(bundle)
    for target in ("2026-03-02", "2026-03-01"):
        with pytest.raises(ValueError, match="target_session > signal_asof"):
            build_signal_bundle([_row(target=target)])


def test_identity_requires_equal_dates():
    bundle = build_signal_bundle([_row(target="2026-03-02")], signal_asof_policy="identity")
    validate_signal_bundle(bundle)
    with pytest.raises(ValueError, match="target_session == signal_asof"):
        build_signal_bundle([_row()], signal_asof_policy="identity")


def test_unproven_requires_null_available_at():
    bundle = build_signal_bundle([_row()])
    assert bundle["availability"] == "unproven"
    assert bundle["available_at"] is None
    with pytest.raises(ValueError, match="requires null"):
        build_signal_bundle([_row()], available_at="2026-03-02T15:00:00+08:00")


def test_declared_rejects_available_at_after_target_session():
    with pytest.raises(ValueError, match="available_at is after target_session"):
        build_signal_bundle(
            [_row()], availability="declared", available_at="2026-03-06T00:00:00+08:00",
        )
    bundle = build_signal_bundle(
        [_row(), _row("2026-03-05", "2026-03-09")],
        availability="declared", available_at="2026-03-02T15:00:00+08:00",
    )
    validate_signal_bundle(bundle)


@pytest.mark.parametrize("field,value", [
    ("schema", "unknown/1"), ("bundle_sha256", "0" * 64),
    ("bundle_sha256", "A" * 64), ("calendar_id", "0" * 64),
    ("signal_asof_policy", "weekday"), ("price_domain", "auto"),
    ("availability", "inferred"), ("rows", {}),
])
def test_unknown_schema_and_bad_hash_raise(field, value):
    bundle = build_signal_bundle([_row()])
    bundle[field] = value
    with pytest.raises(ValueError):
        validate_signal_bundle(bundle)


def test_calendar_id_stable_for_same_sessions():
    rows = [_row(), _row("2026-03-05", "2026-03-09")]
    bundle = build_signal_bundle(rows)
    assert bundle["calendar_id"] == build_signal_bundle(rows[::-1])["calendar_id"]
    assert bundle["calendar_id"] == hashlib.sha256(
        b'["2026-03-05","2026-03-09"]\n',
    ).hexdigest()
    payload = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    assert bundle["bundle_sha256"] == hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def test_package_source_has_no_sys_path_insert():
    package = Path(__file__).resolve().parents[1] / "myquant_contract"
    for source in package.rglob("*.py"):
        assert "sys.path" not in source.read_text(encoding="utf-8")


def test_canonical_json_is_utf8_without_bom():
    payload = canonical_json_bytes({"z": "信号", "a": None})
    assert payload == '{"a":null,"z":"信号"}\n'.encode("utf-8")
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert json.loads(payload) == {"z": "信号", "a": None}
    with pytest.raises(ValueError):
        canonical_json_bytes(float("nan"))


@pytest.mark.parametrize("stamp", [
    None, "2026-03-02T15:00:00Z", "2026-03-02T15:00:00+00:00",
    "2026-03-02T15:00:00.1+08:00", "2026-03-02T24:00:00+08:00",
    "2026-02-30T15:00:00+08:00",
])
def test_declared_requires_valid_seconds_and_offset(stamp):
    with pytest.raises(ValueError, match="available_at"):
        build_signal_bundle([_row()], availability="declared", available_at=stamp)


@pytest.mark.parametrize("field,value", [
    ("signal_asof", "2026-02-30"), ("target_session", "20260305"),
    ("pool_file", "../20260305.csv"), ("pool_file", "20260306.csv"),
    ("pool_md5", "A" * 32), ("pool_sha256", "a" * 63),
])
def test_invalid_row_rejected(field, value):
    row = _row()
    row[field] = value
    with pytest.raises(ValueError):
        build_signal_bundle([row])


def test_one_row_per_file_and_empty_bundle():
    with pytest.raises(ValueError, match="duplicate pool_file"):
        build_signal_bundle([_row(), _row()])
    bundle = build_signal_bundle([])
    assert bundle["rows"] == []
    validate_signal_bundle(bundle)
