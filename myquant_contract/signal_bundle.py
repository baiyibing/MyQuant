"""Build and validate the stdlib-only ``myquant.signal-bundle/1`` contract.

Canonical JSON uses sorted keys, compact separators, UTF-8 and one trailing
LF, including when hashing. Dates are ISO calendar dates. No sessions are
inferred and no input rows are omitted by the builder.

The single declared ``available_at`` supplies a +08:00 clock applied to each
row's signal_asof date. Producers anchor it to the earliest emitted as-of
date. Its literal calendar date must also be <= every target_session; this
module never silently repairs a future timestamp.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

SCHEMA = "myquant.signal-bundle/1"
_FIELDS = {
    "schema", "signal_asof_policy", "availability", "available_at", "calendar_id",
    "price_domain", "rows", "bundle_sha256",
}
_ROW_FIELDS = {"signal_asof", "target_session", "pool_file", "pool_md5", "pool_sha256"}


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically, without a BOM or non-finite numbers."""
    return (json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ) + "\n").encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _match(value: Any, pattern: str, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(f"invalid {name}: {value!r}")


def _date(value: Any, name: str) -> date:
    _match(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}", name)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {name}: {value!r}") from exc


def _fields(value: Any, expected: set[str], name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{name} must contain exactly: {', '.join(sorted(expected))}")


def validate_signal_bundle(bundle: Mapping[str, Any]) -> None:
    """Raise ValueError for invalid shape, dates, policy, or internal hashes.

    File digest syntax is checked here; the consumer verifies actual CSV bytes.
    Validation does not mutate the supplied bundle.
    """
    _fields(bundle, _FIELDS, "bundle")
    if bundle["schema"] != SCHEMA:
        raise ValueError(f"unknown schema: {bundle['schema']!r}")
    policy = bundle["signal_asof_policy"]
    if policy not in ("pred_minus_one", "identity"):
        raise ValueError(f"invalid signal_asof_policy: {policy!r}")
    if bundle["price_domain"] not in ("unspecified", "none", "front", "back"):
        raise ValueError("invalid price_domain")
    availability = bundle["availability"]
    available_at = bundle["available_at"]
    timestamp = None
    if availability == "unproven":
        if available_at is not None:
            raise ValueError("unproven availability requires null available_at")
    elif availability == "declared":
        _match(
            available_at,
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+08:00",
            "available_at",
        )
        try:
            timestamp = datetime.fromisoformat(available_at)
        except ValueError as exc:
            raise ValueError("invalid available_at") from exc
    else:
        raise ValueError("invalid availability")

    rows = bundle["rows"]
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")  # noqa: TRY004 - contract failures use ValueError
    sessions = set()
    pool_files = set()
    for row in rows:
        _fields(row, _ROW_FIELDS, "row")
        asof = _date(row["signal_asof"], "signal_asof")
        target = _date(row["target_session"], "target_session")
        if policy == "pred_minus_one" and target <= asof:
            raise ValueError("pred_minus_one requires target_session > signal_asof")
        if policy == "identity" and target != asof:
            raise ValueError("identity requires target_session == signal_asof")
        if timestamp is not None and timestamp.date() > target:
            raise ValueError("available_at is after target_session")
        expected_file = row["target_session"].replace("-", "") + ".csv"
        if row["pool_file"] != expected_file:
            raise ValueError("pool_file must be target_session as YYYYMMDD.csv")
        if expected_file in pool_files:
            raise ValueError(f"duplicate pool_file: {expected_file}")
        pool_files.add(expected_file)
        sessions.add(row["target_session"])
        _match(row["pool_md5"], r"[0-9a-f]{32}", "pool_md5")
        _match(row["pool_sha256"], r"[0-9a-f]{64}", "pool_sha256")

    _match(bundle["calendar_id"], r"[0-9a-f]{64}", "calendar_id")
    if bundle["calendar_id"] != _sha256(sorted(sessions)):
        raise ValueError("calendar_id mismatch")
    _match(bundle["bundle_sha256"], r"[0-9a-f]{64}", "bundle_sha256")
    payload = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    if bundle["bundle_sha256"] != _sha256(payload):
        raise ValueError("bundle_sha256 mismatch")


def build_signal_bundle(
    rows: Sequence[Mapping[str, Any]],
    *,
    signal_asof_policy: str = "pred_minus_one",
    availability: str = "unproven",
    available_at: str | None = None,
    price_domain: str = "unspecified",
) -> dict[str, Any]:
    """Copy every supplied row, add calendar/bundle digests, and validate.

    The producer supplies the already resolved sessions and CSV digests. It
    must omit predictions lacking a next panel date before calling this API.
    """
    copied = []
    for row in rows:
        _fields(row, _ROW_FIELDS, "row")
        _date(row["target_session"], "target_session")
        copied.append(dict(row))
    bundle = {
        "schema": SCHEMA,
        "signal_asof_policy": signal_asof_policy,
        "availability": availability,
        "available_at": available_at,
        "calendar_id": _sha256(sorted({row["target_session"] for row in copied})),
        "price_domain": price_domain,
        "rows": copied,
    }
    bundle["bundle_sha256"] = _sha256(bundle)
    validate_signal_bundle(bundle)
    return bundle
