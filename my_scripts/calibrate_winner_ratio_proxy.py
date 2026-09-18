"""校准 盈筹率 Quantile 近似 vs QMT 真值（vendor_qmt_winner_chips）。

代理口径（buy_eligibility 当前实现）：$close(后复权) 低于过去 250 日 $close 的 10% 分位
视为 盈筹率<10%。本脚本在 QMT 覆盖的日期上对比两者：
- 连续一致性：代理分位（close 在过去 250 日的分位秩，时间无权） vs QMT winner_ratio 的相关
- 阈值一致性：<10% 判定的混淆矩阵（精确率/召回率）
结论写收益诊断报告 §开关①。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from data_root import resolve_source_parquet

QLIB_DIR = Path.home() / ".qlib" / "qlib_data" / "my_data"
TRUTH_PATH = resolve_source_parquet("vendor_qmt_winner_chips.parquet")


def main() -> int:
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    from handler_frame_cache import resolve_qlib_kernels

    _kernels = resolve_qlib_kernels()
    print(f"[qlib] kernels={_kernels} (QLIB_KERNELS, default 1)", flush=True)
    qlib.init(provider_uri=str(QLIB_DIR), region=REG_CN, kernels=_kernels)

    df = pd.read_parquet(TRUTH_PATH)
    df["d"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df["wr"] = pd.to_numeric(df["winner_ratio"], errors="coerce")
    n_bad = int(((df.wr < 0) | (df.wr > 1)).sum())
    df = df[df.wr.between(0, 1)].dropna(subset=["wr"])
    print(f"QMT 真值: 越界剔除 {n_bad} 行, 保留 {len(df)} 行, 日期 {sorted(df.d.dt.strftime('%m-%d').unique())}")

    def to_qlib(code: str) -> str:
        sym, _, exch = code.partition(".")
        return f"{exch}{sym}"

    codes = sorted({to_qlib(c) for c in df.stock_code.unique()})
    d_min, d_max = df.d.min(), df.d.max()
    # 代理特征：现价与其过去 250 日分位秩（时间无权盈筹率的连续形式）= close 在窗口的百分位
    # qlib 无直接百分位算子，用 Quantile 插值近似两档：P10/Q25/Q50/Q75/P90 + close，重构秩
    fields = [
        "$adjclose",
        "Quantile($adjclose, 250, 0.10)",
        "Quantile($adjclose, 250, 0.25)",
        "Quantile($adjclose, 250, 0.50)",
        "Quantile($adjclose, 250, 0.75)",
        "Quantile($adjclose, 250, 0.90)",
    ]
    fdf = D.features(codes, fields, start_time=d_min, end_time=d_max)
    fdf.columns = ["close", "p10", "p25", "p50", "p75", "p90"]
    fdf = fdf.reset_index()  # datetime, instrument, ...
    print(f"代理特征: {len(fdf)} 行, 日期 {fdf.datetime.min():%m-%d}~{fdf.datetime.max():%m-%d}")
    fdf["code"] = fdf["instrument"]

    def proxy_rank(close, qs) -> float:
        grid = [0.10, 0.25, 0.50, 0.75, 0.90]
        if any(pd.isna(v) for v in qs) or pd.isna(close):
            return np.nan
        if qs[0] <= 0:
            return np.nan
        if close <= qs[0]:
            return 0.10 * max(0.0, min(1.0, close / qs[0]))
        for i in range(len(qs) - 1):
            if qs[i] <= close <= qs[i + 1]:
                span = qs[i + 1] - qs[i]
                return grid[i] + (0.0 if span == 0 else (close - qs[i]) / span * (grid[i + 1] - grid[i]))
        return 1.0 if close > qs[-1] else 0.90

    qs_arr = fdf[["p10", "p25", "p50", "p75", "p90"]].to_numpy()
    close_arr = fdf["close"].to_numpy()
    fdf["proxy"] = [proxy_rank(c, q) for c, q in zip(close_arr, qs_arr)]

    df["code"] = df["stock_code"].map(to_qlib)
    ev = df.merge(fdf[["datetime", "code", "close", "proxy"]], left_on=["d", "code"], right_on=["datetime", "code"], how="inner")
    ev = ev.rename(columns={"wr": "wr_qmt"})[["d", "code", "wr_qmt", "close", "proxy"]].dropna()
    print(f"配对样本: {len(ev)}")
    corr_p = ev.wr_qmt.corr(ev.proxy)
    corr_s = ev.wr_qmt.corr(ev.proxy, method="spearman")
    mae = (ev.wr_qmt - ev.proxy).abs().mean()
    print(f"连续一致: Pearson={corr_p:.3f} Spearman={corr_s:.3f} MAE={mae:.3f}")

    # 阈值 <10% 混淆矩阵（真值 winner_ratio<0.10 vs 代理 proxy<0.10）
    t = ev.wr_qmt < 0.10
    p = ev.proxy < 0.10
    tp = int((t & p).sum()); fp = int((~t & p).sum()); fn = int((t & ~p).sum()); tn = int((~t & ~p).sum())
    prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
    print(f"阈值<10% 混淆: TP={tp} FP={fp} FN={fn} TN={tn}  精确率={prec:.3f} 召回率={rec:.3f} 一致率={(tp+tn)/len(ev):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
