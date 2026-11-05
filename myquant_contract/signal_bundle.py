"""Host facade for the shared ``myquant.signal-bundle/1`` contract.

The optional infra pin owns building, validation and canonical bytes (sorted
keys, compact JSON, UTF-8, one trailing LF). Imports remain usable without
infra; calling a contract operation requires ``requirements-infra.txt``.
Session and signal selection remain the producer's responsibility.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Any

SCHEMA = "myquant.signal-bundle/1"
_PACKAGE = "myquant_infra.contracts.signal_bundle"


def _infra():
    try:
        return import_module(_PACKAGE)
    except ModuleNotFoundError as exc:
        if exc.name and (_PACKAGE == exc.name or _PACKAGE.startswith(exc.name + ".")):
            raise ModuleNotFoundError(
                "Signal bundle operations require the optional myquant-infra pin; "
                "install it with python -m pip install -r requirements-infra.txt",
                name=exc.name,
            ) from exc
        raise


def canonical_json_bytes(value: Any) -> bytes:
    """Return the shared v1 canonical bytes, including their trailing LF."""
    return _infra().canonical_json_bytes(value)


def validate_signal_bundle(bundle: Mapping[str, Any]) -> None:
    """Validate shape, dates and hashes; the consumer verifies CSV bytes."""
    return _infra().validate_signal_bundle(bundle)


def build_signal_bundle(
    rows: Sequence[Mapping[str, Any]],
    *,
    signal_asof_policy: str = "pred_minus_one",
    availability: str = "unproven",
    available_at: str | None = None,
    price_domain: str = "unspecified",
) -> dict[str, Any]:
    """Delegate all supplied rows unchanged to the shared v1 builder."""
    return _infra().build_signal_bundle(
        rows,
        signal_asof_policy=signal_asof_policy,
        availability=availability,
        available_at=available_at,
        price_domain=price_domain,
    )
