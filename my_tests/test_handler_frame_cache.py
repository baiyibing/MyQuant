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
    attach_source_hashes,
    cache_paths,
    file_sha256,
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
    assert "ops_source_hash" in a and "handler_source_hash" in a
    assert a["ops_source_hash"] != "missing"
    assert a["handler_source_hash"] != "missing"
    assert handler_cache_digest(_payload(limit_up_filter_on=False)) != handler_cache_digest(a)
    assert handler_cache_digest(_payload(end_time="2025-12-31")) != handler_cache_digest(a)
    assert handler_cache_digest(_payload(include_lz=False)) != handler_cache_digest(a)
    assert handler_cache_digest(_payload(tradable_universe_on=True)) != handler_cache_digest(a)


def test_ops_source_hash_changes_digest(tmp_path):
    ops_a = tmp_path / "ops_a.py"
    ops_b = tmp_path / "ops_b.py"
    handler = tmp_path / "handler.py"
    ops_a.write_text("X = 1\n", encoding="utf-8")
    ops_b.write_text("X = 2\n", encoding="utf-8")
    handler.write_text("class H: pass\n", encoding="utf-8")
    d1 = handler_cache_digest(_payload(ops_path=ops_a, handler_path=handler))
    d2 = handler_cache_digest(_payload(ops_path=ops_b, handler_path=handler))
    assert d1 != d2
    # Missing file → fixed sentinel, still keyable
    missing = attach_source_hashes({}, ops_path=tmp_path / "nope.py", handler_path=handler)
    assert missing["ops_source_hash"] == "missing"
    assert missing["handler_source_hash"] == file_sha256(handler)


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


def test_load_or_build_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OSKH_HANDLER_CACHE_DIR", str(tmp_path))
    payload = _payload()
    digest = handler_cache_digest(payload)
    builds = []

    def _build():
        builds.append(1)
        return _DummyHandler(7)

    h1, hit1, obs1 = load_or_build_handler(
        payload=payload, builder=_build, enabled=True, cache_dir=tmp_path
    )
    assert hit1 is False and obs1["digest"] == digest and h1.n == 7 and len(builds) == 1
    assert obs1["cache_hit"] is False
    assert obs1["miss_reason"] == "missing"
    assert obs1["path"] is not None and Path(obs1["path"]).is_file()
    assert obs1["size_mb"] is not None and obs1["size_mb"] > 0
    pkl, meta = cache_paths(digest, tmp_path)
    assert pkl.is_file() and meta.is_file()
    out1 = capsys.readouterr().out
    assert "HANDLER_CACHE MISS" in out1 and f"key={digest[:16]}" in out1

    # Second call would use Alpha158CostKDJ.load; dummy pickle is not that type.
    # Cover save + miss-on-bad-load rebuild:
    h2, hit2, obs2 = load_or_build_handler(
        payload=payload, builder=_build, enabled=True, cache_dir=tmp_path
    )
    assert hit2 is False and h2.n == 7 and len(builds) == 2
    assert obs2["miss_reason"] == "load_failed"
    assert obs2["cache_hit"] is False
    out2 = capsys.readouterr().out
    assert "HANDLER_CACHE MISS" in out2 and "reason=load_failed" in out2


def test_cache_hit_skips_builder(tmp_path, monkeypatch, capsys):
    cached = _DummyHandler(9)
    monkeypatch.setattr(
        "handler_frame_cache.try_load_handler",
        lambda digest, cache_dir=None: cached,
    )
    # Pretend the pkl exists so load path is taken as HIT (not missing).
    payload = _payload()
    digest = handler_cache_digest(payload)
    pkl, _ = cache_paths(digest, tmp_path)
    pkl.parent.mkdir(parents=True, exist_ok=True)
    pkl.write_bytes(b"dummy")

    builds: list[int] = []
    h, hit, obs = load_or_build_handler(
        payload=payload,
        builder=lambda: builds.append(1) or _DummyHandler(0),
        enabled=True,
        cache_dir=tmp_path,
    )
    assert hit is True and h.n == 9 and builds == []
    assert obs["cache_hit"] is True
    assert obs["digest"] == digest
    assert obs["miss_reason"] is None
    assert obs["path"] == str(pkl)
    assert obs["size_mb"] is not None
    out = capsys.readouterr().out
    assert "HANDLER_CACHE HIT" in out and f"key={digest[:16]}" in out and "reason=None" in out


def test_save_dummy_and_disabled_skips_disk(tmp_path, capsys):
    payload = _payload()
    digest = handler_cache_digest(payload)
    h, hit, obs = load_or_build_handler(
        payload=payload,
        builder=lambda: _DummyHandler(1),
        enabled=False,
        cache_dir=tmp_path,
    )
    assert hit is False and h.n == 1
    assert obs["miss_reason"] == "disabled"
    assert obs["path"] is None and obs["size_mb"] is None
    assert obs["digest"] == digest
    pkl, _ = cache_paths(digest, tmp_path)
    assert not pkl.exists()
    out = capsys.readouterr().out
    assert "HANDLER_CACHE MISS" in out and "reason=disabled" in out
    save_handler(_DummyHandler(3), digest, payload, tmp_path)
    assert pkl.is_file()
