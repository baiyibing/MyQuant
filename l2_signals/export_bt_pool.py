"""把 l2_signals 信号明细导出为 MyQuant-backtrader 名单池（YYYYMMDD.csv 逐日文件）。

契约（docs/backtest/pool-csv-contract.md）：
- 文件名 = 买入日 T（信号日 = 尾盘买入日，same-day close fill）
- 裸六位码、headerless、LF、UTF-8 无 BOM、无名称列
- 只写 exports/ 树，拒绝任何 stock_pool 路径（is_repo_stock_pool 同款护栏）

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/export_bt_pool.py                 # 全量池
    D:/anaconda3/envs/vanna312/python.exe l2_signals/export_bt_pool.py --min-n 3       # N>=3 门槛池
"""
import argparse
import os
import re
import sys

import pandas as pd

BT_REPO = os.environ.get("MYQUANT_BT_REPO")  # 显式指定；不再默认写死另一仓树
DEFAULT_CSV = "E:/stock_data/l2_research/signals/stab_low_trend_2026.csv"


def to_bare(code: str) -> str:
    m = re.match(r"^(\d{6})\.(SH|SZ|BJ)$", code)
    if not m:
        raise ValueError(f"非法代码格式: {code}")
    return m.group(1)


def check_coverage(bare_codes):
    """预检信号股在 BT path-SSOT 日线树的覆盖，返回缺失清单。"""
    root = os.path.join(os.environ.get("OSKH_SOURCE_PARQUET_ROOT", "E:/stock_data"),
                        "stock", "period=1d", "dividend_type=none")
    if not os.path.isdir(root):
        print(f"[coverage] 日线根不存在，跳过预检: {root}")
        return []
    missing = []
    for bare in sorted(bare_codes):
        if bare[0] in "69" and bare[:3] in ("688", "689"):
            suffix = "SH"
        elif bare[:3] in ("920", "430", "830", "870", "880"):
            suffix = "BJ"
        elif bare[0] == "6":
            suffix = "SH"
        else:
            suffix = "SZ"
        if not os.path.isdir(os.path.join(root, f"symbol={bare}_{suffix}")):
            missing.append(f"{bare}.{suffix}")
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV, help="信号明细 CSV（export_signal.py 产物）")
    ap.add_argument("--bt-repo", default=BT_REPO,
                    help="目标 BT 仓根（或 env MYQUANT_BT_REPO）；不再默认写死路径")
    ap.add_argument("--min-n", type=int, default=0, help="当日信号数 <N 则跳过该日（0=全量）")
    ap.add_argument("--tag", default=None, help="池目录标签（默认 stab_low_trend[_nN]）")
    args = ap.parse_args()

    if not args.bt_repo:
        ap.error("需要 --bt-repo 或 env MYQUANT_BT_REPO（写入另一仓树必须显式指定）")
    df = pd.read_csv(args.csv, parse_dates=["d"])
    day_counts = df.groupby("d")["stock_code"].agg(["count", "unique"])
    if args.min_n > 0:
        day_counts = day_counts[day_counts["count"] >= args.min_n]
    days_kept = len(day_counts)
    sig_kept = int(day_counts["count"].sum())

    tag = args.tag or ("stab_low_trend" if args.min_n <= 0 else f"stab_low_trend_n{args.min_n}")
    start, end = day_counts.index.min(), day_counts.index.max()
    out_dir = os.path.join(args.bt_repo, "exports", f"{tag}_{start:%Y%m%d}_{end:%Y%m%d}")
    if re.search(r"(^|[\\/])stock_pool([\\/]|$)", out_dir):
        raise SystemExit(f"拒绝写入 stock_pool 路径: {out_dir}")
    os.makedirs(out_dir, exist_ok=True)

    bare_all = sorted({to_bare(c) for c in df["stock_code"]})
    missing = check_coverage(bare_all)
    for d, row in day_counts.iterrows():
        codes = sorted(to_bare(c) for c in row["unique"])
        with open(os.path.join(out_dir, f"{d:%Y%m%d}.csv"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(codes) + "\n")

    print(f"[pool] {tag}: {days_kept} 日 / {sig_kept} 信号 → {out_dir}")
    print(f"[pool] 信号股 {len(bare_all)} 支，行情缺失 {len(missing)} 支" + (f": {missing}" if missing else ""))
    if days_kept < len(df.groupby('d')):
        print(f"[pool] 门槛 min_n={args.min_n} 剔除 {len(df.groupby('d')) - days_kept} 日 / {len(df) - sig_kept} 信号")


if __name__ == "__main__":
    sys.exit(main())
