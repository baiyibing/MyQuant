"""Pin validator failures independently of the bundle's outer checksum."""

import hashlib
from copy import deepcopy
from typing import Any

import pytest
from myquant_infra.contracts.signal_bundle import (
    build_signal_bundle,
    canonical_json_bytes,
    validate_signal_bundle,
)

pytestmark = pytest.mark.usefixtures("infra_signal_bundle")


@pytest.fixture
def valid_bundle() -> dict[str, Any]:
    # Keep rows unsorted so validation must preserve their supplied order.
    rows = [
        {
            "signal_asof": asof,
            "target_session": target,
            "pool_file": target.replace("-", "") + ".csv",
            "pool_md5": "a" * 32,
            "pool_sha256": "b" * 64,
        }
        for asof, target in (
            ("2026-03-05", "2026-03-09"),
            ("2026-03-02", "2026-03-05"),
        )
    ]
    return build_signal_bundle(
        rows,
        availability="declared",
        available_at="2026-03-02T15:00:00+08:00",
    )


def _rehash_bundle(bundle: dict[str, Any]) -> None:
    payload = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def test_invalid_signal_asof_policy(valid_bundle: dict[str, Any]) -> None:
    valid_bundle["signal_asof_policy"] = "previous_session"
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match="^invalid signal_asof_policy:"):
        validate_signal_bundle(valid_bundle)


def test_invalid_price_domain(valid_bundle: dict[str, Any]) -> None:
    valid_bundle["price_domain"] = "adjusted"
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match="^invalid price_domain$"):
        validate_signal_bundle(valid_bundle)


@pytest.mark.parametrize("price_domain", ["unspecified", "none", "front", "back"])
def test_allowed_price_domain(
    valid_bundle: dict[str, Any], price_domain: str,
) -> None:
    valid_bundle["price_domain"] = price_domain
    _rehash_bundle(valid_bundle)
    assert validate_signal_bundle(valid_bundle) is None


def test_invalid_availability(valid_bundle: dict[str, Any]) -> None:
    valid_bundle["availability"] = "estimated"
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match="^invalid availability$"):
        validate_signal_bundle(valid_bundle)


def test_extra_top_level_field(valid_bundle: dict[str, Any]) -> None:
    valid_bundle["unexpected"] = "extra"
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match="^bundle must contain exactly:"):
        validate_signal_bundle(valid_bundle)


@pytest.mark.parametrize("field", [
    "schema", "signal_asof_policy", "availability", "available_at",
    "calendar_id", "price_domain", "rows", "bundle_sha256",
])
def test_missing_top_level_field(valid_bundle: dict[str, Any], field: str) -> None:
    del valid_bundle[field]
    with pytest.raises(ValueError, match="^bundle must contain exactly:"):
        validate_signal_bundle(valid_bundle)


@pytest.mark.parametrize("rows", [None, (), "[]"], ids=["null", "tuple", "string"])
def test_rows_must_be_list(valid_bundle: dict[str, Any], rows: Any) -> None:
    valid_bundle["rows"] = rows
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match="^rows must be a list$"):
        validate_signal_bundle(valid_bundle)


def test_duplicate_pool_file(valid_bundle: dict[str, Any]) -> None:
    valid_bundle["rows"].append(deepcopy(valid_bundle["rows"][0]))
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match=r"^duplicate pool_file: 20260309\.csv$"):
        validate_signal_bundle(valid_bundle)


def test_pool_file_must_match_target_session(valid_bundle: dict[str, Any]) -> None:
    valid_bundle["rows"][0]["pool_file"] = "20260310.csv"
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match=r"^pool_file must be target_session as YYYYMMDD\.csv$"):
        validate_signal_bundle(valid_bundle)


def test_calendar_id_must_match_sessions(valid_bundle: dict[str, Any]) -> None:
    incomplete_calendar = [valid_bundle["rows"][0]["target_session"]]
    valid_bundle["calendar_id"] = hashlib.sha256(
        canonical_json_bytes(incomplete_calendar),
    ).hexdigest()
    _rehash_bundle(valid_bundle)
    with pytest.raises(ValueError, match="^calendar_id mismatch$"):
        validate_signal_bundle(valid_bundle)


def test_validate_does_not_mutate_input(valid_bundle: dict[str, Any]) -> None:
    before = deepcopy(valid_bundle)
    validate_signal_bundle(valid_bundle)
    assert valid_bundle == before
