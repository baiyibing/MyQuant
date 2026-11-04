"""导出指定信号组合的逐条明细 CSV（日期×股票 + 因子值 + 大单上下文 + 标签）。

阈值口径与 search_alpha158.py 完全一致：H1（2026-01-05..06-30）分位数。

用法：
    D:/anaconda3/envs/vanna312/python.exe l2_signals/export_signal.py            # 默认 QUIET_LOW_TREND
    D:/anaconda3/envs/vanna312/python.exe l2_signals/export_signal.py --list     # 列出已定义信号
"""
import argparse
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import search_alpha158 as S  # noqa: E402

OUT_DIR = "E:/stock_data/l2_research/signals"

# 信号定义：名字 → (条件列与分位切点, 输出文件名)
# 'ge'/'le' 后的数是 H1 分位数（如 0.8 = >=q80, 0.2 = <=q20）
SIGNALS = {
    "STAB_LOW_TREND": {
        "desc": "低位企稳趋势：IMIN10<=q20 & QTLD30>=q80 & RSQR5>=q80（可交易池 Top，两半最稳）",
        "conds": [("IMIN10", "le", 0.20), ("QTLD30", "ge", 0.80), ("RSQR5", "ge", 0.80)],
        "file": "stab_low_trend_2026.csv",
        "ctx_cols": ["c1x", "bs", "nfr", "ddxr", "pr", "nbam_m", "KMID", "ret_prev", "KLEN"],
    },
    "QUIET_LOW_TREND": {
        "desc": "[废弃-一字板污染] LOW0>=q80 & QTLU5<=q20 & RSQR5>=q80：76.9% 中 65% 是买不进的一字板，可交易部分仅 59.4%",
        "conds": [("LOW0", "ge", 0.80), ("QTLU5", "le", 0.20), ("RSQR5", "ge", 0.80)],
        "file": "quiet_low_trend_2026_deprecated.csv",
        "ctx_cols": ["c1x", "bs", "nfr", "ddxr", "pr", "nbam_m", "KMID", "ret_prev"],
        "deprecated": True,
    },
}

META_KEYS = ("d", "stock_code", "close_px", "t1_close", "ret1", "win", "h2")


def export(name: str, df: pd.DataFrame, out_dir: str):
    sig = SIGNALS[name]
    h1 = df[~df["h2"]]
    mask = pd.Series(True, index=df.index)
    thresholds = {}
    for col, op, q in sig["conds"]:
        th = float(h1[col].quantile(q))
        thresholds[f"{col}__{op}__q{int(q*100)}"] = round(th, 6)
        mask &= df[col] >= th if op == "ge" else df[col] <= th
    sub = df[mask].copy()
    sub["h2"] = sub["h2"].map({True: "H2", False: "H1"})

    cols = list(META_KEYS[:6]) + ["h2"] + [c for c, _, _ in sig["conds"]] + sig["ctx_cols"]
    sub = sub.sort_values("d")[cols]

    n = len(sub)
    wr = sub["win"].mean()
    avg = sub["ret1"].mean()
    h1s, h2s = sub[sub["h2"] == "H1"], sub[sub["h2"] == "H2"]
    stats = {
        "signal": name, "desc": sig["desc"], "n": int(n),
        "win_rate": round(float(wr), 4), "avg_ret": round(float(avg), 5),
        "n_h1": int(len(h1s)), "wr_h1": round(float(h1s["win"].mean()), 4),
        "n_h2": int(len(h2s)), "wr_h2": round(float(h2s["win"].mean()), 4),
        "thresholds_h1_quantiles": thresholds,
        "pool": "C1: 大单(10万档)量>=2x前日, 2026-01-05..10-30",
    }
    if sig.get("deprecated"):
        print(f"  [警告] 该信号已废弃：{sig['desc']}")
    elif stats["wr_h2"] <= 0.5:
        # explicit raise: `assert` vanishes under `python -O`
        raise ValueError(f"H2 验证失败（wr_h2={stats['wr_h2']:.4f}），不该导出: {name}")

    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, sig["file"])
    sub.to_csv(csv_path, index=False, encoding="utf-8-sig")
    meta_path = os.path.join(out_dir, sig["file"].replace(".csv", ".meta.json"))
    json.dump(stats, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"[{name}] {sig['desc']}")
    print(f"  n={n}  wr={wr*100:.1f}%  avg={avg*100:+.2f}%  |  H1 {len(h1s)} {h1s['win'].mean()*100:.1f}%  H2 {len(h2s)} {h2s['win'].mean()*100:.1f}%")
    print(f"  阈值(H1分位): " + ", ".join(f"{k}={v:g}" for k, v in thresholds.items()))
    print(f"  → {csv_path}")
    print(f"  → {meta_path}")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal", default=None, choices=sorted(SIGNALS),
                    help="必填（原默认 QUIET_LOW_TREND 已废弃，见 --list）")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for k, v in SIGNALS.items():
            print(f"{k}: {v['desc']}")
        return
    if args.signal is None:
        ap.error("--signal 必填（默认值已随 QUIET_LOW_TREND 废弃而移除；--list 看全部）")
    df = S.load_pool()
    export(args.signal, df, args.out_dir)


if __name__ == "__main__":
    main()
