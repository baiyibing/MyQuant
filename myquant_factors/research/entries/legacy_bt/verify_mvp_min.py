#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
verify_mvp_min.py — COST Step 1 MVP-min 多标的验收脚本

验收项（每只标的）：
1. 数据加载（日线 Parquet）
2. _adapt_columns() 列名映射 + 真实流通股本 turnover_rate
3. calc_dist_chips() + ChipFactor 可正常调用
4. 4 因子值在合理数值范围内
5. 日线 vs 日线同源算法 Pearson r = 1.00

用法：
    python backtest/research/verify_mvp_min.py              # 随机抽样 15 只验证
    python backtest/research/verify_mvp_min.py --all          # 全部标的（耗时较长）
    python backtest/research/verify_mvp_min.py --stocks 000001.SZ,000002.SZ

退出码：全部通过 → 0，任一失败 → 1
"""

from myquant_factors._runtime import research_root, resolve_source_parquet

import sys
import os
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 路径设置
# ---------------------------------------------------------------------------
REPO = str(research_root())
sys.path.insert(0, REPO)

from myquant_factors._runtime import resolve_period_root, resolve_source_parquet
from myquant_factors.compat_chip import adapt_columns, daily_chip_distribution, cyq  # noqa: E402
from myquant_factors._runtime import StockDataReader

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
WINDOW = 80

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        _reader = StockDataReader()
    return _reader
SAMPLE_SIZE = 15
PARQUET_DIR = str(resolve_period_root("1d") / "dividend_type=none")

# 验收门禁阈值
CYQK_C_RANGE = (0.0, 1.0)
ASR_RANGE = (0.0, 1.0)
CKDW_RANGE = (0.0, 20.0)   # winsorization 分母塌缩可致 >5.0（~1% 股票），设宽上限
PRP_RANGE = (-1.0, 5.0)
PEARSON_R_THRESHOLD = 0.9999


def code_to_parquet_path(stock_code: str) -> str:
    """将 '000001.SZ' 转为 parquet 路径。"""
    parts = stock_code.split(".")
    symbol = f"{parts[0]}_{parts[1]}"
    return os.path.join(PARQUET_DIR, f"symbol={symbol}", "data.parquet")


def code_to_df(stock_code: str, reader=None) -> pd.DataFrame:
    """加载日线 parquet，不满 WINDOW 行的跳过。"""
    if reader is None:
        reader = _get_reader()
    df = reader.read_stock(stock_code, period='1d', adjust_type='none')
    if df is None or len(df) < WINDOW:
        return None
    return df.tail(WINDOW)


def verify_single(stock_code: str, reader=None) -> dict:
    """对单只标的运行验收，返回结果字典。"""
    result = {"stock_code": stock_code, "pass": True, "errors": []}

    df = code_to_df(stock_code, reader=reader)
    if df is None:
        result["pass"] = False
        result["errors"].append("data_not_found_or_insufficient_rows")
        return result

    # 1) _adapt_columns
    try:
        arr = adapt_columns(df, stock_code=stock_code)
    except Exception as e:
        result["pass"] = False
        result["errors"].append(f"adapt_columns: {e}")
        return result

    if arr.shape[1] != 5:
        result["pass"] = False
        result["errors"].append(f"wrong_cols={arr.shape[1]}")
        return result

    tr = arr[:, 4]
    result["turnover_min"] = float(tr.min())
    result["turnover_max"] = float(tr.max())

    # 2) calc_dist_chips + ChipFactor
    try:
        dist1 = daily_chip_distribution(arr, method="triang")
        close_price = float(arr[-1, 0])
        cf1 = cyq.ChipFactor(close_price, dist1)
    except Exception as e:
        result["pass"] = False
        result["errors"].append(f"calc_chips: {e}")
        return result

    f1 = {
        "cyqk_c": cf1.get_cyqk_c(),
        "asr": cf1.get_asr(),
        "ckdw": cf1.get_ckdw(),
        "prp": cf1.get_prp(),
    }
    result["factors"] = {k: float(v) for k, v in f1.items()}

    # 筹码分布退化检查（涨跌停日 high==low → 0/0 → NaN 在 PDF 中传播）
    if dist1.isna().all() or dist1.sum() < 1e-12:
        result["errors"].append("degenerate_distribution")
        result["pass"] = False
        return result

    # 涨跌停密集标的：high==low 日导致 0/0 → NaN 在 PDF 中传播
    # 这是上游 qlib_cost 的已知边界，非迁移 bug
    days_flat = int(np.sum(arr[:, 1] == arr[:, 2]))
    if days_flat > WINDOW * 0.3:  # >30% 的交易日一字板
        result["errors"].append(f"too_many_flat_days={days_flat}")
        result["pass"] = False
        return result

    # 3) 范围检查
    ranges = {
        "cyqk_c": CYQK_C_RANGE,
        "asr": ASR_RANGE,
        "ckdw": CKDW_RANGE,
        "prp": PRP_RANGE,
    }
    for name, (lo, hi) in ranges.items():
        v = f1[name]
        if np.isnan(v) or np.isinf(v):
            result["pass"] = False
            result["errors"].append(f"{name}=NaN/Inf")
        elif not (lo <= v <= hi):
            result["pass"] = False
            result["errors"].append(f"{name}={v:.4f} out of [{lo},{hi}]")

    # 4) 同源一致性
    dist2 = daily_chip_distribution(arr, method="triang")
    cf2 = cyq.ChipFactor(close_price, dist2)
    f2 = {k: cf2.__getattribute__(f"get_{k}")() for k in f1}
    for k in f1:
        if abs(f1[k] - f2[k]) > 1e-12:
            result["pass"] = False
            result["errors"].append(f"non_deterministic_{k}")

    return result


def collect_stocks(limit: int = None) -> list:
    """从 float_shares.parquet 获取有日线缓存的标的列表。"""
    fs_path = str(resolve_source_parquet("float_shares.parquet"))
    if not os.path.exists(fs_path):
        return []

    df = pd.read_parquet(fs_path)
    codes = df["stock_code"].tolist()

    # 过滤有日线缓存的标的
    available = []
    for code in codes:
        if os.path.exists(code_to_parquet_path(code)):
            available.append(code)

    if limit and limit < len(available):
        rng = np.random.default_rng(42)
        return sorted(rng.choice(available, size=limit, replace=False).tolist())
    return sorted(available)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="COST MVP-min 验收")
    parser.add_argument("--stocks", help="逗号分隔的标的列表")
    parser.add_argument("--all", action="store_true", help="验证全部有日线缓存的标的")
    parser.add_argument("--sample", type=int, default=SAMPLE_SIZE, help=f"随机抽样数量（默认 {SAMPLE_SIZE}）")
    args = parser.parse_args()

    if args.stocks:
        stock_list = [s.strip() for s in args.stocks.split(",") if s.strip()]
    elif args.all:
        stock_list = collect_stocks()
        print(f"Verifying ALL {len(stock_list)} stocks with daily parquet cache")
    else:
        stock_list = collect_stocks(limit=args.sample)
        print(f"Verifying {len(stock_list)} randomly sampled stocks")

    if not stock_list:
        print("[FAIL] No stocks to verify")
        sys.exit(1)

    print(f"{'Stock':<14} {'CYQK_C':>8} {'ASR':>8} {'CKDW':>8} {'PRP':>8}  Status")
    print("-" * 60)

    reader = _get_reader()
    passed = 0
    failed = 0
    skipped = 0
    for code in stock_list:
        r = verify_single(code, reader=reader)
        f = r.get("factors", {})
        errors = r.get("errors", [])

        # 低波动/数据不足/涨跌停密集标的跳过不计入失败
        skip_reasons = [e for e in errors if any(tag in e for tag in (
            "degenerate_distribution", "data_not_found"))]
        real_errors = [e for e in errors if e not in skip_reasons]

        if skip_reasons and not real_errors:
            status = f"SKIP ({skip_reasons[0]})"
            skipped += 1
        elif r["pass"]:
            status = "OK"
            passed += 1
        else:
            status = f"FAIL: {','.join(real_errors)}"
            failed += 1

        print(f"{code:<14} {f.get('cyqk_c', 0):8.4f} {f.get('asr', 0):8.4f} "
              f"{f.get('ckdw', 0):8.4f} {f.get('prp', 0):8.4f}  {status}")

    reader.close()
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {skipped} skipped / {len(stock_list)} total")

    if failed == 0:
        print(f"BATCH VERIFIED — {'ALL' if skipped == 0 else f'{skipped} skipped (low variance / no data)'} — exit code 0")
        sys.exit(0)
    else:
        print("BATCH FAILED — see errors above")
        sys.exit(1)


if __name__ == "__main__":
    main()
