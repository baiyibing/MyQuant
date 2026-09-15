# -*- coding: utf-8 -*-
"""Explicit Redis reachability probe for qlib init (eng-perf P1-2).

qlib silently degrades when Redis is unreachable (expr-cache locks drop).
This module PING-probes host:port/db and logs a one-line visible signal so
operators can tell ``ok`` vs ``degraded`` without relying on qlib internals.
Password is never printed.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

_DEGRADED_HINT = "expr-cache locks unavailable; handler-cache pickle unaffected"


def probe_qlib_redis(
    host: str,
    port: int,
    password: Optional[str] = None,
    db: int = 1,
    *,
    socket_timeout: float = 1.0,
) -> dict[str, Any]:
    """Try Redis PING; return ``{ok, mode, detail}`` without logging secrets.

    Modes:
    - ``ok``: PING succeeded
    - ``degraded``: connection/auth/PING failed (qlib will silently drop Redis use)
    - ``skipped``: redis-py not importable (probe aborted; caller still logs)
    """
    host_s = str(host or "").strip() or "127.0.0.1"
    port_i = int(port)
    db_i = int(db)
    try:
        import redis  # type: ignore
    except ImportError as exc:
        return {
            "ok": False,
            "mode": "skipped",
            "detail": f"redis-py unavailable: {exc}",
            "host": host_s,
            "port": port_i,
            "db": db_i,
        }

    client = None
    try:
        # redis-py 4+/5+/8 accept password=None as no-auth.
        client = redis.Redis(
            host=host_s,
            port=port_i,
            db=db_i,
            password=password,
            socket_connect_timeout=socket_timeout,
            socket_timeout=socket_timeout,
        )
        pong = client.ping()
        if pong:
            return {
                "ok": True,
                "mode": "ok",
                "detail": "PING",
                "host": host_s,
                "port": port_i,
                "db": db_i,
            }
        return {
            "ok": False,
            "mode": "degraded",
            "detail": f"PING returned {pong!r}",
            "host": host_s,
            "port": port_i,
            "db": db_i,
        }
    except Exception as exc:  # noqa: BLE001 — probe must never raise into train
        # Class name only; str(exc) can embed auth failure text but not the password
        # we passed (redis-py does not echo it). Still avoid dumping full repr.
        detail = f"{type(exc).__name__}: {exc}"
        if password and password in detail:
            detail = detail.replace(password, "***")
        return {
            "ok": False,
            "mode": "degraded",
            "detail": detail,
            "host": host_s,
            "port": port_i,
            "db": db_i,
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass


def format_redis_probe_line(result: Mapping[str, Any]) -> str:
    """One-line log; never includes password."""
    host = result.get("host", "?")
    port = result.get("port", "?")
    db = result.get("db", "?")
    mode = str(result.get("mode", "degraded"))
    if mode == "ok":
        return f"[redis] ok host={host}:{port} db={db}"
    detail = str(result.get("detail") or "unknown")
    if mode == "skipped":
        return (
            f"[redis] skipped host={host}:{port} db={db} detail={detail} "
            f"({_DEGRADED_HINT})"
        )
    return (
        f"[redis] degraded host={host}:{port} db={db} detail={detail} "
        f"({_DEGRADED_HINT})"
    )


def log_qlib_redis_probe(
    host: str,
    port: int,
    password: Optional[str] = None,
    db: int = 1,
    *,
    expr_cache: bool = False,
    result: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Probe (unless ``result`` given), print the visibility line, optional WARN.

    When ``expr_cache`` is True and mode is not ``ok``, print an extra WARN that
    DiskExpressionCache locks will be unavailable.
    """
    probe = dict(result) if result is not None else probe_qlib_redis(
        host, port, password=password, db=db
    )
    # Ensure host/port/db present for formatting even if caller passed a partial mock
    probe.setdefault("host", str(host))
    probe.setdefault("port", int(port))
    probe.setdefault("db", int(db))
    print(format_redis_probe_line(probe), flush=True)
    mode = str(probe.get("mode", "degraded"))
    if expr_cache and mode != "ok":
        print(
            f"[redis] WARN --expr-cache requested but Redis mode={mode}; "
            f"DiskExpressionCache locks unavailable (qlib may drop expression_cache)",
            flush=True,
        )
    return probe
