"""handler_frame_cache: key isolation + pickle round-trip (no live qlib bins)."""

from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from handler_frame_cache import (  # noqa: E402
    cache_paths,
    handler_cache_digest,
    load_or_build_handler,
    make_handler_cache_payload,
    resolve_qlib_kernels,
    save_handler,
)


def _payload(**overrides):
    base = dict(
        start_time="2020-01-01",
        end_time="2026-09-08",
        fit_start_time="2020-01-01",
        fit_end_time="2024-12-31",
        segments={
            "train": ("2020-01-01", "2024-12-31"),
            "valid": ("2025-01-01", "2025-12-31"),
            "test": ("2026-01-01", "2026-09-08"),
        },
        include_alpha158=True,
        include_cost_kdj=True,
        include_signal=False,
        include_lz=True,
        drop_raw=True,
        exclude_filter_on=False,
        limit_up_filter_on=True,
        tradable_universe_on=False,
    )
    base.update(overrides)
    return make_handler_cache_payload(**base)


def test_digest_stable_and_isolated():
    a = _payload()
    b = _payload()
    assert handler_cache_digest(a) == handler_cache_digest(b)
    assert handler_cache_digest(_payload(limit_up_filter_on=False)) != handler_cache_digest(a)
    assert handler_cache_digest(_payload(end_time="2025-12-31")) != handler_cache_digest(a)
    assert handler_cache_digest(_payload(include_lz=False)) != handler_cache_digest(a)
    assert handler_cache_digest(_payload(tradable_universe_on=True)) != handler_cache_digest(a)


def test_resolve_qlib_kernels_default_one(monkeypatch):
    monkeypatch.delenv("QLIB_KERNELS", raising=False)
    assert resolve_qlib_kernels() == 1
    monkeypatch.setenv("QLIB_KERNELS", "8")
    assert resolve_qlib_kernels() == 8


class _DummyHandler:
    def __init__(self, n: int):
        self.n = n

    def to_pickle(self, path, dump_all=True):
        assert dump_all is True
        Path(path).write_bytes(pickle.dumps(self))


def test_load_or_build_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("OSKH_HANDLER_CACHE_DIR", str(tmp_path))
    payload = _payload()
    digest = handler_cache_digest(payload)
    builds = []

    def _build():
        builds.append(1)
        return _DummyHandler(7)

    h1, hit1, d1 = load_or_build_handler(
        payload=payload, builder=_build, enabled=True, cache_dir=tmp_path
    )
    assert hit1 is False and d1 == digest and h1.n == 7 and len(builds) == 1
    pkl, meta = cache_paths(digest, tmp_path)
    assert pkl.is_file() and meta.is_file()

    # Second call would use Alpha158CostKDJ.load; dummy pickle is not that type.
    # Cover save + miss-on-bad-load rebuild:
    h2, hit2, _ = load_or_build_handler(
        payload=payload, builder=_build, enabled=True, cache_dir=tmp_path
    )
    assert hit2 is False and h2.n == 7 and len(builds) == 2


def test_cache_hit_skips_builder(tmp_path, monkeypatch):
    cached = _DummyHandler(9)
    monkeypatch.setattr(
        "handler_frame_cache.try_load_handler",
        lambda digest, cache_dir=None: cached,
    )
    builds: list[int] = []
    h, hit, _ = load_or_build_handler(
        payload=_payload(),
        builder=lambda: builds.append(1) or _DummyHandler(0),
        enabled=True,
        cache_dir=tmp_path,
    )
    assert hit is True and h.n == 9 and builds == []


def test_save_dummy_and_disabled_skips_disk(tmp_path):
    payload = _payload()
    digest = handler_cache_digest(payload)
    h, hit, _ = load_or_build_handler(
        payload=payload,
        builder=lambda: _DummyHandler(1),
        enabled=False,
        cache_dir=tmp_path,
    )
    assert hit is False and h.n == 1
    pkl, _ = cache_paths(digest, tmp_path)
    assert not pkl.exists()
    save_handler(_DummyHandler(3), digest, payload, tmp_path)
    assert pkl.is_file()
