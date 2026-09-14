"""Project-level single-file cache for Alpha158CostKDJ after handler_init.

Why pickle, not fetch()→parquet (perf archive N1):
- custom_train_backtest already forbids diagnostic fetch: qlib fetch copies the
  whole ~5 GiB processed frame (2026-09-14 MemoryError).
- qlib Serializable.to_pickle(dump_all=True) already dumps _infer/_learn in one
  sequential file. dump_all is mandatory: default dump drops ``_`` attrs, so a
  pickle without it is config-only and cannot skip Loading.

Hit path: Alpha158CostKDJ.load(pkl). Miss: build then atomic write.
Key = config_hash of windows / feature flags / 闸门 / calendar fingerprint
(data refresh changes calendar_last → miss).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from run_manifest import canonical_json, config_hash

_CACHE_DIR_ENV = "OSKH_HANDLER_CACHE_DIR"
_DEFAULT_PROVIDER = "~/.qlib/qlib_data/my_data"


def resolve_qlib_kernels() -> int:
    raw = str(os.environ.get("QLIB_KERNELS", "1") or "1").strip() or "1"
    return int(raw)


def resolve_handler_cache_dir() -> Path:
    raw = str(os.environ.get(_CACHE_DIR_ENV) or "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".cache" / "qlib_handler_cache"


def make_handler_cache_payload(
    *,
    start_time: str,
    end_time: str,
    fit_start_time: str,
    fit_end_time: str,
    segments: Mapping[str, Any],
    include_alpha158: bool,
    include_cost_kdj: bool,
    include_signal: bool,
    include_lz: bool,
    drop_raw: bool,
    exclude_filter_on: bool,
    limit_up_filter_on: bool,
    tradable_universe_on: bool,
    cost_window: int = 250,
    provider_uri: str = _DEFAULT_PROVIDER,
    handler_class: str = "Alpha158CostKDJ",
) -> dict[str, Any]:
    """Serializable key material. Strategy-only flags (buy-state, limit_threshold) stay out."""
    return {
        "handler_class": handler_class,
        "start_time": str(start_time),
        "end_time": str(end_time),
        "fit_start_time": str(fit_start_time),
        "fit_end_time": str(fit_end_time),
        "segments": {
            name: (str(seg[0]), str(seg[1])) if isinstance(seg, (tuple, list)) and len(seg) == 2 else seg
            for name, seg in segments.items()
        },
        "include_alpha158": bool(include_alpha158),
        "include_cost_kdj": bool(include_cost_kdj),
        "include_signal": bool(include_signal),
        "include_lz": bool(include_lz),
        "drop_raw": bool(drop_raw),
        "exclude_filter_on": bool(exclude_filter_on),
        "limit_up_filter_on": bool(limit_up_filter_on),
        "tradable_universe_on": bool(tradable_universe_on),
        "cost_window": int(cost_window),
        "provider_uri": str(provider_uri),
    }


def attach_calendar_fingerprint(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bind cache to the live qlib calendar so a my_data refresh cannot reuse stale pkl."""
    out = dict(payload)
    try:
        import pandas as pd
        from qlib.data import D

        cal = D.calendar()
        out["calendar_first"] = str(pd.Timestamp(cal[0]).date())
        out["calendar_last"] = str(pd.Timestamp(cal[-1]).date())
        out["calendar_days"] = int(len(cal))
    except Exception as exc:
        out["calendar_error"] = f"{type(exc).__name__}: {exc}"
    return out


def handler_cache_digest(payload: Mapping[str, Any]) -> str:
    return config_hash(payload)


def cache_paths(digest: str, cache_dir: Optional[Path] = None) -> tuple[Path, Path]:
    root = cache_dir if cache_dir is not None else resolve_handler_cache_dir()
    stem = f"handler_{digest[:16]}"
    return root / f"{stem}.pkl", root / f"{stem}.meta.json"


def try_load_handler(digest: str, cache_dir: Optional[Path] = None) -> Any:
    pkl, _meta = cache_paths(digest, cache_dir)
    if not pkl.is_file():
        return None
    from custom_handler import Alpha158CostKDJ

    try:
        return Alpha158CostKDJ.load(str(pkl))
    except Exception as exc:
        print(f"[handler-cache] load failed ({type(exc).__name__}: {exc}); rebuild", flush=True)
        return None


def save_handler(
    handler: Any,
    digest: str,
    payload: Mapping[str, Any],
    cache_dir: Optional[Path] = None,
) -> Path:
    pkl, meta = cache_paths(digest, cache_dir)
    pkl.parent.mkdir(parents=True, exist_ok=True)
    tmp = pkl.with_suffix(".pkl.tmp")
    if tmp.exists():
        tmp.unlink()
    handler.to_pickle(str(tmp), dump_all=True)
    tmp.replace(pkl)
    nbytes = pkl.stat().st_size
    meta.write_text(
        canonical_json(
            {
                "digest": digest,
                "bytes": nbytes,
                "payload": dict(payload),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"[handler-cache] wrote {pkl} ({nbytes / (1024 ** 3):.2f} GiB) digest={digest[:16]}",
        flush=True,
    )
    return pkl


def load_or_build_handler(
    *,
    payload: Mapping[str, Any],
    builder: Callable[[], Any],
    enabled: bool,
    cache_dir: Optional[Path] = None,
) -> tuple[Any, bool, str]:
    """Return (handler, cache_hit, digest). When disabled, just builder()."""
    digest = handler_cache_digest(payload)
    if enabled:
        hit = try_load_handler(digest, cache_dir)
        if hit is not None:
            pkl, _ = cache_paths(digest, cache_dir)
            print(f"[handler-cache] HIT {pkl} digest={digest[:16]}", flush=True)
            return hit, True, digest
        print(f"[handler-cache] MISS digest={digest[:16]}", flush=True)
    handler = builder()
    if enabled:
        save_handler(handler, digest, payload, cache_dir)
    return handler, False, digest
