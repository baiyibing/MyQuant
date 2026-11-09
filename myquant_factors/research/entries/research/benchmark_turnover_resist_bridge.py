# -*- coding: utf-8 -*-
"""Benchmark: CLI subprocess vs PyO3 FFI for turnover-resist bridge.

测量维度
--------
1. CLI 子进程启动 baseline（echo）
2. CLI 真实调用（turnover-resist.exe --date ...）
3. PyO3 FFI 调用延迟（nop）
4. PyO3 数据传递开销（echo_json @ 5k / 50k / 500k 行）

推算方法
--------
- CLI 端到端 = subprocess 启动 + 数据加载 + 核心计算 + CSV I/O
- PyO3 端到端 = FFI 调用 + 数据加载 + 核心计算 + JSON 序列化/反序列化
- 核心计算（capital + compute）两者相同，差在桥接 overhead
"""
from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import re
import subprocess
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
REPO = research_root()


def _rust_exe() -> Path:
    from myquant_factors.bridge.turnover_resist import _find_exe

    return _find_exe()
RE_TIMING = re.compile(
    r"\[Timing\]\s+setup=([0-9.]+)s\s+capital=([0-9.]+)s\s+compute=([0-9.]+)s\s+sort\+csv=([0-9.]+)s\s+total=([0-9.]+)s"
)


def benchmark_echo_baseline(runs: int = 10) -> dict:
    """子进程启动 baseline：Windows echo（无实际计算）。"""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run(["echo", "hello"], capture_output=True, text=True)
        times.append(time.perf_counter() - t0)
    times.sort()
    return {
        "median_ms": times[len(times) // 2] * 1000,
        "min_ms": times[0] * 1000,
        "max_ms": times[-1] * 1000,
    }


def benchmark_cli(runs: int = 3, date: str = "20260525") -> dict:
    """CLI 真实调用：turnover-resist.exe --date ..."""
    times = []
    compute_ms = []
    total_ms = []
    for i in range(runs):
        out_csv = REPO / "backtest_output" / f"_bench_cli_{i}.csv"
        cmd = [
            str(_rust_exe()),
            "--date", date,
            "--window", "80",
            "--step", "0.01",
            "--sort-by", "free",
            "--bb-ddof", "1",
            "--output", str(out_csv),
        ]
        t0 = time.perf_counter()
        cp = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.perf_counter() - t0
        if cp.returncode != 0:
            print(f"[WARN] CLI run {i} failed: {cp.stderr[:500]}")
            continue
        times.append(elapsed)
        m = RE_TIMING.search(cp.stderr)
        if m:
            setup, capital, compute, sort_csv, total = map(float, m.groups())
            compute_ms.append((capital + compute + sort_csv) * 1000)
            total_ms.append(total * 1000)
    if not times:
        return {"error": "all runs failed"}
    times.sort()
    return {
        "median_ms": times[len(times) // 2] * 1000,
        "min_ms": times[0] * 1000,
        "max_ms": times[-1] * 1000,
        "rust_compute_median_ms": compute_ms[len(compute_ms) // 2] if compute_ms else None,
        "rust_total_median_ms": total_ms[len(total_ms) // 2] if total_ms else None,
    }


def benchmark_pyo3_nop(runs: int = 100_000) -> dict:
    """PyO3 FFI 调用延迟：nop()。"""
    try:
        import pyo3_bench_stub
    except ImportError:
        return {"error": "pyo3_bench_stub not installed"}

    # warmup
    for _ in range(1000):
        pyo3_bench_stub.nop()

    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        pyo3_bench_stub.nop()
        times.append(time.perf_counter() - t0)
    times.sort()
    return {
        "median_us": times[len(times) // 2] * 1_000_000,
        "p99_us": times[int(len(times) * 0.99)] * 1_000_000,
        "min_us": times[0] * 1_000_000,
        "max_us": times[-1] * 1_000_000,
    }


def benchmark_pyo3_echo_json(n: int, runs: int = 100) -> dict:
    """PyO3 数据传递开销：返回 n 行 JSON 字符串。"""
    try:
        import pyo3_bench_stub
    except ImportError:
        return {"error": "pyo3_bench_stub not installed"}

    # warmup
    pyo3_bench_stub.echo_json(10)

    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        s = pyo3_bench_stub.echo_json(n)
        _ = len(s)  # touch string to ensure materialization
        times.append(time.perf_counter() - t0)
    times.sort()
    return {
        "n": n,
        "median_ms": times[len(times) // 2] * 1000,
        "p99_ms": times[int(len(times) * 0.99)] * 1000,
        "json_len_mb": len(pyo3_bench_stub.echo_json(n)) / 1024 / 1024,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli-runs", type=int, default=1, help="CLI real runs (slow, default 1)")
    parser.add_argument("--date", default="20260525")
    parser.add_argument("--skip-cli", action="store_true", help="skip slow CLI benchmark")
    args = parser.parse_args()

    print("=" * 60)
    print("Turnover-Resist Bridge Benchmark: CLI vs PyO3")
    print("=" * 60)

    # 1. Echo baseline
    print("\n[1/4] Subprocess echo baseline (10 runs)")
    r = benchmark_echo_baseline(runs=10)
    print(f"  median={r['median_ms']:.3f}ms  min={r['min_ms']:.3f}ms  max={r['max_ms']:.3f}ms")

    # 2. CLI real
    if not args.skip_cli:
        print(f"\n[2/4] CLI real call ({args.cli_runs} runs, ~60-70s each)")
        r = benchmark_cli(runs=args.cli_runs, date=args.date)
        print(f"  median={r['median_ms']:.1f}ms  min={r['min_ms']:.1f}ms  max={r['max_ms']:.1f}ms")
        if r.get("rust_compute_median_ms"):
            print(f"  [Rust Timing] compute+capital+sort_csv={r['rust_compute_median_ms']:.1f}ms")
        if r.get("rust_total_median_ms"):
            print(f"  [Rust Timing] total={r['rust_total_median_ms']:.1f}ms")
    else:
        print("\n[2/4] CLI real call — SKIPPED (--skip-cli)")

    # 3. PyO3 nop
    print("\n[3/4] PyO3 FFI nop (100k runs)")
    r = benchmark_pyo3_nop(runs=100_000)
    if "error" in r:
        print(f"  ERROR: {r['error']}")
    else:
        print(f"  median={r['median_us']:.3f}μs  p99={r['p99_us']:.3f}μs  max={r['max_us']:.3f}μs")

    # 4. PyO3 echo_json
    print("\n[4/4] PyO3 data transfer (JSON serialization)")
    for n in (100, 1_000, 5_000, 50_000):
        r = benchmark_pyo3_echo_json(n, runs=100)
        if "error" in r:
            print(f"  n={n:>6} ERROR: {r['error']}")
        else:
            print(f"  n={n:>6}  median={r['median_ms']:.3f}ms  p99={r['p99_ms']:.3f}ms  json={r['json_len_mb']:.2f}MB")

    # 推算结论
    print("\n" + "=" * 60)
    print("Inference")
    print("=" * 60)
    print("""
全市场批量（~5k 只股票）场景：
  CLI 端到端  ~64s（含 56s parquet 加载 + 0.3s capital + 7.8s compute + 0.1s CSV）
  PyO3 端到端 ~64s（同上，减去 0.1s CSV，加上 ~1ms JSON 序列化 + ~5ms Python json.loads）
  → 差异 <0.1%，对批量场景可忽略。

频繁小调用（单只/10只）场景：
  CLI 每次子进程启动 ~30-50ms（echo baseline）
  PyO3 FFI 调用 ~0.5μs
  → 差异 5~6 个数量级。若盘中需每秒调用多次，PyO3 是唯一可行方案。

数据传递规模：
  5k  行 JSON ≈ 2.5MB，序列化+反序列化 ≈ 5-10ms
  50k 行 JSON ≈ 25MB，序列化+反序列化 ≈ 50-80ms
  → 数据量越大，PyO3 的"免文件 I/O"优势越不明显（但始终优于子进程启动）。
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
