#!/usr/bin/env python3
"""赢筹偏差诊断 — 发布前自动门禁。

读取 config/chip_diagnosis.yaml，逐项检查：
1. float_shares.parquet 覆盖率 >= 阈值
2. 日线 front 复权数据存在且非空
3. 分钟线 none 数据存在且非空
4. 样本量 >= 最小截面点要求
5. config YAML SHA-256 已写入报告元数据
6. 任一失败退出非零码，阻断发布

用法：
    python scripts/research/preflight_chip_diagnosis.py
    python scripts/research/preflight_chip_diagnosis.py --config config/chip_diagnosis.yaml
"""
from __future__ import annotations

from myquant_factors._runtime import research_root, resolve_source_parquet

import argparse
import hashlib
import json
import os

from myquant_factors._runtime import resolve_parquet_container, resolve_period_root, resolve_source_parquet
import sys
from pathlib import Path

import pandas as pd
import yaml


_HERE = Path(__file__).resolve()
PROJECT_ROOT = research_root()
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "chip_diagnosis.yaml"
STOCK_DATA = resolve_parquet_container()
REPORT_DIR = PROJECT_ROOT / "docs" / "investigation_reports"

# 标准 bootstrap（scripts/_script_bootstrap.py；裸 sys.path.insert 被
# verify_no_new_scripts_sys_path_insert 拦截，统一走 ensure_repo_on_syspath）
from myquant_factors._runtime import ensure_repo_on_syspath
ensure_repo_on_syspath(__file__)

from myquant_factors._runtime import resolve_period_root  # noqa: E402


def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        raw = f.read()
    cfg = yaml.safe_load(raw)
    cfg["_sha256"] = hashlib.sha256(raw).hexdigest()
    cfg["_path"] = str(path)
    return cfg


def check_float_shares(cfg: dict) -> tuple[bool, str]:
    """检查 float_shares.parquet 覆盖率."""
    threshold = cfg["preflight"]["checks"]["float_shares_coverage"]
    pq_path = resolve_source_parquet("float_shares.parquet")

    if not pq_path.exists():
        return False, f"float_shares.parquet 不存在: {pq_path}"

    df = pd.read_parquet(pq_path, engine="pyarrow")
    covered = len(df)

    # 分母：period=1d/dividend_type=front 目录下有有效 parquet 的标的数
    daily_dir = resolve_period_root("1d") / "dividend_type=front"
    if daily_dir.exists():
        total = sum(
            1 for d in os.listdir(daily_dir)
            if d.startswith("symbol=") and (Path(daily_dir) / d / "data.parquet").exists()
        )
    else:
        return False, f"日线 front 目录不存在: {daily_dir}"

    if total == 0:
        return False, "日线 front 目录为空，无法计算覆盖率"

    ratio = covered / total
    if ratio < threshold:
        return False, f"float_shares 覆盖率 {ratio:.2%} < {threshold:.0%}（{covered}/{total}）"

    return True, f"float_shares 覆盖率 {ratio:.2%} >= {threshold:.0%}（{covered}/{total}）"


def check_daily_data(cfg: dict) -> tuple[bool, str]:
    """检查日线 front 复权数据存在且非空."""
    daily_dir = resolve_period_root("1d") / "dividend_type=front"
    if not daily_dir.exists():
        return False, f"日线 front 目录不存在: {daily_dir}"

    symbols = [d for d in os.listdir(daily_dir) if d.startswith("symbol=")]
    if not symbols:
        return False, "日线 front 目录无 symbol= 子目录"

    max_missing_ratio = float(cfg["preflight"]["checks"].get("max_data_missing_ratio", 0.05))
    sample_limit = int(cfg["preflight"]["checks"].get("data_file_sample_limit", 0) or 0)
    check_symbols = symbols if sample_limit <= 0 else symbols[:sample_limit]

    empty_count = 0
    for d in check_symbols:
        pq = daily_dir / d / "data.parquet"
        if not pq.exists() or pq.stat().st_size == 0:
            empty_count += 1

    checked = len(check_symbols)
    missing_ratio = (empty_count / checked) if checked > 0 else 1.0
    if missing_ratio > max_missing_ratio:
        return False, (
            f"日线 front 空/缺失比例 {missing_ratio:.2%} > {max_missing_ratio:.2%} "
            f"（{empty_count}/{checked}）"
        )

    return True, (
        f"日线 front 数据存在（总 {len(symbols)} 只，检查 {checked} 只，"
        f"空/缺失 {empty_count}，比例 {missing_ratio:.2%}）"
    )


def check_minute_data(cfg: dict) -> tuple[bool, str]:
    """检查分钟线 none 数据存在且非空."""
    minute_dir = resolve_period_root("1m") / "dividend_type=none"
    if not minute_dir.exists():
        return False, f"分钟线 none 目录不存在: {minute_dir}"

    symbols = [d for d in os.listdir(minute_dir) if d.startswith("symbol=")]
    if not symbols:
        return False, "分钟线 none 目录无 symbol= 子目录"

    max_missing_ratio = float(cfg["preflight"]["checks"].get("max_data_missing_ratio", 0.05))
    sample_limit = int(cfg["preflight"]["checks"].get("data_file_sample_limit", 0) or 0)
    check_symbols = symbols if sample_limit <= 0 else symbols[:sample_limit]

    empty_count = 0
    for d in check_symbols:
        pq = minute_dir / d / "data.parquet"
        if not pq.exists() or pq.stat().st_size == 0:
            empty_count += 1

    checked = len(check_symbols)
    missing_ratio = (empty_count / checked) if checked > 0 else 1.0
    if missing_ratio > max_missing_ratio:
        return False, (
            f"分钟线 none 空/缺失比例 {missing_ratio:.2%} > {max_missing_ratio:.2%} "
            f"（{empty_count}/{checked}）"
        )

    return True, (
        f"分钟线 none 数据存在（总 {len(symbols)} 只，检查 {checked} 只，"
        f"空/缺失 {empty_count}，比例 {missing_ratio:.2%}）"
    )


def check_sample_size(cfg: dict) -> tuple[bool, str]:
    """检查样本量是否达到最小截面点要求."""
    min_cross = cfg["preflight"]["checks"]["min_sample_cross_sections"]

    # 从 config 推断最小截面点：每类样本数 × 每只日期数
    grouping = cfg.get("sample_comparison", {}).get("grouping", {})
    stocks_per_group = sum(grouping.values())
    dates_per_stock = cfg.get("sample_comparison", {}).get("dates_per_stock", 3)
    expected_cross = stocks_per_group * dates_per_stock

    if expected_cross < min_cross:
        return False, (
            f"样本配置截面点不足: {expected_cross} < {min_cross} "
            f"（{stocks_per_group} 只 × {dates_per_stock} 日期）"
        )

    return True, f"样本配置截面点 {expected_cross} >= {min_cross}"


def check_config_hash_in_report(cfg: dict) -> tuple[bool, str]:
    """检查 config YAML SHA-256 是否已写入报告元数据."""
    config_hash = cfg["_sha256"]

    # 查找最新的报告元数据文件
    metadata_files = sorted(REPORT_DIR.glob("**/metadata*.json"), key=os.path.getmtime, reverse=True)
    if not metadata_files:
        return False, "未找到报告元数据文件（metadata.json），请先执行诊断并写入 config 哈希"

    latest = metadata_files[0]
    try:
        meta = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return False, f"报告元数据文件无法解析: {latest}"

    recorded_hash = meta.get("config_sha256") or meta.get("config_hash")
    if recorded_hash != config_hash:
        return False, (
            f"报告元数据中的 config 哈希不匹配: "
            f"report={recorded_hash[:12]}... vs config={config_hash[:12]}..."
        )

    return True, f"config SHA-256 已写入报告元数据: {latest.name}"


def main() -> int:
    parser = argparse.ArgumentParser(description="赢筹偏差诊断 — 发布前自动门禁")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[FATAL] 配置文件不存在: {config_path}")
        return 1

    cfg = load_config(config_path)
    print(f"Config: {config_path} (SHA-256: {cfg['_sha256'][:16]}...)")
    print()

    checks = [
        ("float_shares 覆盖率", check_float_shares),
        ("日线 front 数据", check_daily_data),
        ("分钟线 none 数据", check_minute_data),
        ("样本截面点数量", check_sample_size),
        ("config 哈希报告绑定", check_config_hash_in_report),
    ]

    failed = 0
    for label, fn in checks:
        ok, msg = fn(cfg)
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} {label}: {msg}")
        if not ok:
            failed += 1

    print()
    if failed == 0:
        print("Preflight PASSED — 可以发布")
        return 0
    else:
        print(f"Preflight FAILED — {failed} 项未通过，禁止发布")
        return 1


if __name__ == "__main__":
    sys.exit(main())
