"""Project-level single-file cache for Alpha158CostKDJ after handler_init.

Why pickle, not fetch()→parquet (perf archive N1):
- custom_train_backtest already forbids diagnostic fetch: qlib fetch copies the
  whole ~5 GiB processed frame (2026-09-14 MemoryError).
- qlib Serializable.to_pickle(dump_all=True) already dumps _infer/_learn in one
  sequential file. dump_all is mandatory: default dump drops ``_`` attrs, so a
  pickle without it is config-only and cannot skip Loading.

Hit path: Alpha158CostKDJ.load(pkl). Miss: build then atomic write.
Key = config_hash of windows / feature flags / 闸门 / calendar fingerprint
+ custom_ops/custom_handler source sha256 (data refresh changes calendar_last → miss;
changing ops/handler source → miss).

eng-perf P1-4: after write, if pickle size_mb exceeds OSKH_HANDLER_CACHE_WARN_MB
(default 4096; Win tiers 4096 default / 8192 high-RAM), stdout WARN but still keep
the file (warn-only; no fatal). obs may include peak_rss_mb (resource/psutil; None
if unavailable).
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from run_manifest import canonical_json, config_hash


def _call_builder(builder: Callable[[], Any]) -> Any:
    """Run handler __init__ (Loading + processors).

    qlib ProcessInf → datetime_groupby_apply(n_jobs=-1) ships a nested
    ``process_inf`` through joblib loky. On Windows that raises PicklingError
    after a successful Loading (~8 min wasted). Threading keeps the month
    split without pickling. HIT path never enters here.
    """
    if os.name == "nt":
        from joblib import parallel_backend

        with parallel_backend("threading"):
            return builder()
    return builder()

_CACHE_DIR_ENV = "OSKH_HANDLER_CACHE_DIR"
_WARN_MB_ENV = "OSKH_HANDLER_CACHE_WARN_MB"
# Win pickle-size tiers (MiB): 4096 default hosts; 8192 high-RAM (~64 GiB commit).
# Warn-only for now (eng-perf P1-4); fatal deferred until Win RSS curves stabilize.
DEFAULT_HANDLER_CACHE_WARN_MB = 4096
_DEFAULT_PROVIDER = "~/.qlib/qlib_data/my_data"
_SOURCE_MISSING_SENTINEL = "missing"


def resolve_qlib_kernels() -> int:
    """Feature-engine process pool size for qlib.init(kernels=...). Default 1 (Win-safe).

    Independent of dump max_workers and LGB num_threads (eng-perf P1-1 three knobs).
    Override: QLIB_KERNELS.
    """
    raw = str(os.environ.get("QLIB_KERNELS", "1") or "1").strip() or "1"
    return int(raw)


# Align with qlib_scripts/refresh_mydata.DEFAULT_MAX_WORKERS (dump_all pin; forbid 16).
DEFAULT_DUMP_MAX_WORKERS = 8
DEFAULT_LGB_NUM_THREADS = 20


def resolve_dump_max_workers() -> int:
    """CSV→bin dump_all worker count. Default 8; independent of qlib kernels.

    Override: QLIB_DUMP_MAX_WORKERS. Value 16 is rejected (refresh discipline) → default.
    Invalid / non-positive → default with warning.
    """
    raw = str(os.environ.get("QLIB_DUMP_MAX_WORKERS", str(DEFAULT_DUMP_MAX_WORKERS)) or "").strip()
    if not raw:
        return DEFAULT_DUMP_MAX_WORKERS
    try:
        val = int(raw)
    except ValueError:
        print(
            f"[parallelism] QLIB_DUMP_MAX_WORKERS={raw!r} invalid; using {DEFAULT_DUMP_MAX_WORKERS}",
            flush=True,
        )
        return DEFAULT_DUMP_MAX_WORKERS
    if val == 16:
        print(
            f"[parallelism] QLIB_DUMP_MAX_WORKERS=16 forbidden (refresh dump_all pin); "
            f"using {DEFAULT_DUMP_MAX_WORKERS}",
            flush=True,
        )
        return DEFAULT_DUMP_MAX_WORKERS
    if val < 1:
        print(
            f"[parallelism] QLIB_DUMP_MAX_WORKERS={val} invalid; using {DEFAULT_DUMP_MAX_WORKERS}",
            flush=True,
        )
        return DEFAULT_DUMP_MAX_WORKERS
    return val


def resolve_lgb_num_threads() -> int:
    """LightGBM in-tree thread count. Default 20 (production); does not change training effect unless overridden.

    Override: LGB_NUM_THREADS. Independent of kernels and dump max_workers.
    """
    raw = str(os.environ.get("LGB_NUM_THREADS", str(DEFAULT_LGB_NUM_THREADS)) or "").strip()
    if not raw:
        return DEFAULT_LGB_NUM_THREADS
    try:
        val = int(raw)
    except ValueError:
        print(
            f"[parallelism] LGB_NUM_THREADS={raw!r} invalid; using {DEFAULT_LGB_NUM_THREADS}",
            flush=True,
        )
        return DEFAULT_LGB_NUM_THREADS
    if val < 1:
        print(
            f"[parallelism] LGB_NUM_THREADS={val} invalid; using {DEFAULT_LGB_NUM_THREADS}",
            flush=True,
        )
        return DEFAULT_LGB_NUM_THREADS
    return val


def log_parallelism_knobs(
    *,
    kernels: int | None = None,
    dump_max_workers: int | None = None,
    lgb_num_threads: int | None = None,
) -> dict[str, int]:
    """One-line log making the three independent knobs explicit (eng-perf P1-1)."""
    k = resolve_qlib_kernels() if kernels is None else int(kernels)
    d = resolve_dump_max_workers() if dump_max_workers is None else int(dump_max_workers)
    t = resolve_lgb_num_threads() if lgb_num_threads is None else int(lgb_num_threads)
    print(
        f"[parallelism] kernels={k} (QLIB_KERNELS) "
        f"dump_max_workers={d} (QLIB_DUMP_MAX_WORKERS) "
        f"lgb_num_threads={t} (LGB_NUM_THREADS)",
        flush=True,
    )
    return {"kernels": k, "dump_max_workers": d, "lgb_num_threads": t}


def resolve_handler_cache_dir() -> Path:
    raw = str(os.environ.get(_CACHE_DIR_ENV) or "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".cache" / "qlib_handler_cache"


def resolve_handler_cache_warn_mb() -> float:
    """Pickle size WARN threshold in MiB (OSKH_HANDLER_CACHE_WARN_MB).

    Default 4096. Win host tiers (document only; override via env):
    - 4096 — default / typical Win commit budget
    - 8192 — high-RAM hosts (~64 GiB pagefile/commit)
    Invalid / non-positive → default.
    """
    raw = str(os.environ.get(_WARN_MB_ENV, str(DEFAULT_HANDLER_CACHE_WARN_MB)) or "").strip()
    if not raw:
        return float(DEFAULT_HANDLER_CACHE_WARN_MB)
    try:
        val = float(raw)
    except ValueError:
        print(
            f"[handler-cache] {_WARN_MB_ENV}={raw!r} invalid; using {DEFAULT_HANDLER_CACHE_WARN_MB}",
            flush=True,
        )
        return float(DEFAULT_HANDLER_CACHE_WARN_MB)
    if val <= 0:
        print(
            f"[handler-cache] {_WARN_MB_ENV}={val} invalid; using {DEFAULT_HANDLER_CACHE_WARN_MB}",
            flush=True,
        )
        return float(DEFAULT_HANDLER_CACHE_WARN_MB)
    return val


def sample_peak_rss_mb() -> float | None:
    """Best-effort peak RSS in MiB; None when unavailable (never blocks cache I/O).

    Linux/macOS: ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` (Linux KiB, Darwin bytes).
    Else optional ``psutil`` (peak_wset on Win, else rss). Not a hard dependency.
    """
    try:
        import resource

        rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            return rss / (1024.0 ** 2)
        # Linux (and most Unix): KiB
        return rss / 1024.0
    except Exception:
        pass
    try:
        import psutil  # type: ignore

        mi = psutil.Process().memory_info()
        peak = getattr(mi, "peak_wset", None)
        if peak is not None:
            return float(peak) / (1024.0 ** 2)
        return float(mi.rss) / (1024.0 ** 2)
    except Exception:
        return None


def source_file_paths() -> tuple[Path, Path]:
    """Paths to custom_ops.py / custom_handler.py (same dir as this module)."""
    root = Path(__file__).resolve().parent
    return root / "custom_ops.py", root / "custom_handler.py"


def file_sha256(path: Path | str) -> str:
    """sha256 hex of file bytes; fixed sentinel when path is missing."""
    p = Path(path)
    if not p.is_file():
        return _SOURCE_MISSING_SENTINEL
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def attach_source_hashes(
    payload: Mapping[str, Any],
    *,
    ops_path: Path | str | None = None,
    handler_path: Path | str | None = None,
) -> dict[str, Any]:
    """Bind cache key to custom_ops / custom_handler source fingerprints."""
    default_ops, default_handler = source_file_paths()
    out = dict(payload)
    out["ops_source_hash"] = file_sha256(ops_path if ops_path is not None else default_ops)
    out["handler_source_hash"] = file_sha256(
        handler_path if handler_path is not None else default_handler
    )
    return out


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
    drop_limit_up_learn_on: bool = False,
    cost_window: int = 250,
    provider_uri: str = _DEFAULT_PROVIDER,
    handler_class: str = "Alpha158CostKDJ",
    ops_path: Path | str | None = None,
    handler_path: Path | str | None = None,
) -> dict[str, Any]:
    """Serializable key material. Strategy-only flags (buy-state, limit_threshold) stay out."""
    base = {
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
        "drop_limit_up_learn_on": bool(drop_limit_up_learn_on),
        "cost_window": int(cost_window),
        "provider_uri": str(provider_uri),
    }
    return attach_source_hashes(base, ops_path=ops_path, handler_path=handler_path)


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


def _size_mb(path: Path) -> float:
    return float(path.stat().st_size) / (1024.0 ** 2)


def _feature_cols_hash(handler: Any) -> str | None:
    """Short hash of sorted feature/learn columns for meta.json (not digest)."""
    try:
        frame = getattr(handler, "_learn", None)
        if frame is None:
            frame = getattr(handler, "_infer", None)
        if frame is None or not hasattr(frame, "columns"):
            return None
        cols = tuple(sorted(str(c) for c in frame.columns))
        return hashlib.sha256(",".join(cols).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


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
    size_mb = float(nbytes) / (1024.0 ** 2)
    meta_body: dict[str, Any] = {
        "digest": digest,
        "bytes": nbytes,
        "payload": dict(payload),
    }
    cols_hash = _feature_cols_hash(handler)
    if cols_hash is not None:
        meta_body["feature_cols_hash"] = cols_hash
    meta.write_text(
        canonical_json(meta_body) + "\n",
        encoding="utf-8",
    )
    print(
        f"[handler-cache] wrote {pkl} ({nbytes / (1024 ** 3):.2f} GiB) digest={digest[:16]}",
        flush=True,
    )
    warn_mb = resolve_handler_cache_warn_mb()
    if size_mb > warn_mb:
        print(
            f"[handler-cache] WARN size_mb={size_mb:.4f} exceeds "
            f"{_WARN_MB_ENV}={warn_mb:g} "
            f"(Win tiers: 4096 default / 8192 high-RAM; warn-only, still wrote)",
            flush=True,
        )
    return pkl


def _obs(
    *,
    cache_hit: bool,
    digest: str,
    path: str | None,
    size_mb: float | None,
    miss_reason: str | None,
    peak_rss_mb: float | None = None,
) -> dict[str, Any]:
    return {
        "cache_hit": bool(cache_hit),
        "digest": digest,
        "path": path,
        "size_mb": size_mb,
        "miss_reason": miss_reason,
        "peak_rss_mb": peak_rss_mb,
    }


def _log_cache_line(kind: str, info: Mapping[str, Any]) -> None:
    digest = str(info.get("digest") or "")
    path = info.get("path")
    size_mb = info.get("size_mb")
    reason = info.get("miss_reason")
    size_s = f"{float(size_mb):.4f}" if size_mb is not None else "None"
    print(
        f"HANDLER_CACHE {kind} key={digest[:16]} path={path} size_mb={size_s} reason={reason}",
        flush=True,
    )


def load_or_build_handler(
    *,
    payload: Mapping[str, Any],
    builder: Callable[[], Any],
    enabled: bool,
    cache_dir: Optional[Path] = None,
) -> tuple[Any, bool, dict[str, Any]]:
    """Return (handler, cache_hit, obs).

    ``obs`` keys: cache_hit, digest, path, size_mb, miss_reason, peak_rss_mb
    (miss_reason: ``disabled`` / ``missing`` / ``load_failed`` / None on HIT;
    peak_rss_mb may be None when sampling is unavailable).
    """
    digest = handler_cache_digest(payload)
    if not enabled:
        handler = _call_builder(builder)
        info = _obs(
            cache_hit=False,
            digest=digest,
            path=None,
            size_mb=None,
            miss_reason="disabled",
            peak_rss_mb=sample_peak_rss_mb(),
        )
        _log_cache_line("MISS", info)
        return handler, False, info

    pkl, _meta = cache_paths(digest, cache_dir)
    if not pkl.is_file():
        miss_reason = "missing"
        hit = None
    else:
        hit = try_load_handler(digest, cache_dir)
        miss_reason = None if hit is not None else "load_failed"

    if hit is not None:
        info = _obs(
            cache_hit=True,
            digest=digest,
            path=str(pkl),
            size_mb=_size_mb(pkl),
            miss_reason=None,
            peak_rss_mb=sample_peak_rss_mb(),
        )
        _log_cache_line("HIT", info)
        return hit, True, info

    print(f"[handler-cache] MISS digest={digest[:16]} reason={miss_reason}", flush=True)
    handler = _call_builder(builder)
    written = save_handler(handler, digest, payload, cache_dir)
    info = _obs(
        cache_hit=False,
        digest=digest,
        path=str(written),
        size_mb=_size_mb(written),
        miss_reason=miss_reason,
        peak_rss_mb=sample_peak_rss_mb(),
    )
    _log_cache_line("MISS", info)
    return handler, False, info
