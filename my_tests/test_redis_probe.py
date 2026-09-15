# -*- coding: utf-8 -*-
"""eng-perf P1-2: Redis degrade-visible probe (no live Redis required)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MY_SCRIPTS = _ROOT / "my_scripts"
if str(_MY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MY_SCRIPTS))

from redis_probe import (  # noqa: E402
    format_redis_probe_line,
    log_qlib_redis_probe,
    probe_qlib_redis,
)


def test_probe_ok_mocked():
    client = MagicMock()
    client.ping.return_value = True
    with patch("redis.Redis", return_value=client) as redis_cls:
        result = probe_qlib_redis("127.0.0.1", 6379, password="secret", db=1)
    redis_cls.assert_called_once()
    kwargs = redis_cls.call_args.kwargs
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 6379
    assert kwargs["db"] == 1
    assert kwargs["password"] == "secret"
    assert result["ok"] is True
    assert result["mode"] == "ok"
    assert result["host"] == "127.0.0.1"
    assert result["port"] == 6379
    assert result["db"] == 1
    # password must never appear in returned detail
    assert "secret" not in str(result)


def test_probe_degraded_on_connection_error():
    with patch("redis.Redis", side_effect=ConnectionError("refused")):
        result = probe_qlib_redis("10.0.0.1", 6380, password=None, db=2)
    assert result["ok"] is False
    assert result["mode"] == "degraded"
    assert "ConnectionError" in result["detail"]
    assert result["host"] == "10.0.0.1"
    assert result["port"] == 6380
    assert result["db"] == 2


def test_probe_degraded_redacts_password_in_detail():
    pwd = "super-secret-pw"
    with patch("redis.Redis", side_effect=Exception(f"AUTH failed for {pwd}")):
        result = probe_qlib_redis("127.0.0.1", 6379, password=pwd, db=1)
    assert result["mode"] == "degraded"
    assert pwd not in result["detail"]
    assert "***" in result["detail"]


def test_probe_skipped_when_redis_py_missing():
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "redis" or name.startswith("redis."):
            raise ImportError("No module named redis")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_fake_import):
        result = probe_qlib_redis("127.0.0.1", 6379, db=1)
    assert result["ok"] is False
    assert result["mode"] == "skipped"
    assert "redis-py" in result["detail"].lower() or "unavailable" in result["detail"].lower()


def test_format_lines_never_include_password():
    ok_line = format_redis_probe_line(
        {"ok": True, "mode": "ok", "detail": "PING", "host": "127.0.0.1", "port": 6379, "db": 1}
    )
    assert ok_line == "[redis] ok host=127.0.0.1:6379 db=1"
    assert "password" not in ok_line.lower()

    deg_line = format_redis_probe_line(
        {
            "ok": False,
            "mode": "degraded",
            "detail": "ConnectionError: refused",
            "host": "127.0.0.1",
            "port": 6379,
            "db": 1,
        }
    )
    assert deg_line.startswith("[redis] degraded host=127.0.0.1:6379 db=1")
    assert "expr-cache locks unavailable" in deg_line
    assert "handler-cache pickle unaffected" in deg_line


def test_log_ok_line(capsys):
    fake = {
        "ok": True,
        "mode": "ok",
        "detail": "PING",
        "host": "127.0.0.1",
        "port": 6379,
        "db": 1,
    }
    out = log_qlib_redis_probe(
        "127.0.0.1", 6379, password="x", db=1, expr_cache=False, result=fake
    )
    captured = capsys.readouterr().out
    assert "[redis] ok host=127.0.0.1:6379 db=1" in captured
    assert "WARN" not in captured
    assert out["mode"] == "ok"


def test_log_degraded_warns_when_expr_cache(capsys):
    fake = {
        "ok": False,
        "mode": "degraded",
        "detail": "ConnectionError: x",
        "host": "127.0.0.1",
        "port": 6379,
        "db": 1,
    }
    log_qlib_redis_probe(
        "127.0.0.1", 6379, db=1, expr_cache=True, result=fake
    )
    captured = capsys.readouterr().out
    assert "[redis] degraded" in captured
    assert "[redis] WARN" in captured
    assert "--expr-cache" in captured


def test_log_degraded_no_warn_without_expr_cache(capsys):
    fake = {
        "ok": False,
        "mode": "degraded",
        "detail": "ConnectionError: x",
        "host": "127.0.0.1",
        "port": 6379,
        "db": 1,
    }
    log_qlib_redis_probe(
        "127.0.0.1", 6379, db=1, expr_cache=False, result=fake
    )
    captured = capsys.readouterr().out
    assert "[redis] degraded" in captured
    assert "WARN" not in captured


def test_custom_train_wires_probe():
    src = (_MY_SCRIPTS / "custom_train_backtest.py").read_text(encoding="utf-8")
    assert "from redis_probe import log_qlib_redis_probe" in src
    assert "log_qlib_redis_probe(" in src
    # Probe must run after qlib.init
    init_pos = src.index("qlib.init(")
    probe_pos = src.index("log_qlib_redis_probe(")
    assert probe_pos > init_pos
    # Must pass expr_cache flag through
    assert "expr_cache=bool(cli_args.expr_cache)" in src
