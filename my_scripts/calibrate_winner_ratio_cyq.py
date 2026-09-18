"""校准 CYQ parquet vs QMT 真值，并打印 Rust 锚点残差。"""
from __future__ import annotations

import pandas as pd

from data_root import resolve_source_parquet
ANCHORS = {
    "SH688366": 0.0690,  # 昊海生科 rust cyqk_T 2026-09-08（流通股本）
    "SZ002007": 0.2608,  # 华兰生物
}


def to_qlib(code: str) -> str:
    if "." in str(code):
        sym, _, exch = str(code).partition(".")
        return f"{exch}{sym}".upper()
    return str(code).upper()


def main() -> int:
    cyq_path = resolve_source_parquet("cyq_winner_ratio_daily_2026.parquet")
    qmt_path = resolve_source_parquet("vendor_qmt_winner_chips.parquet")
    cyq = pd.read_parquet(cyq_path)
    cyq["code"] = cyq.stock_code.astype(str).str.upper()
    cyq["d"] = pd.to_datetime(cyq.date)
    print(f"CYQ: rows={len(cyq)} stocks={cyq.code.nunique()} {cyq.d.min().date()}~{cyq.d.max().date()}")

    d_anchor = pd.Timestamp("2026-09-08")
    print("Rust 锚点（流通股本 cyqk_T；本产物默认自由流通，残差属预期）:")
    for inst, rust_v in ANCHORS.items():
        row = cyq[(cyq.code == inst) & (cyq.d == d_anchor)]
        ours = float(row.winner_ratio.iloc[0]) if len(row) else float("nan")
        print(f"  {inst} ours={ours:.4f} rust={rust_v:.4f} diff={ours - rust_v:+.4f}")

    qmt = pd.read_parquet(qmt_path)
    qmt["d"] = pd.to_datetime(qmt["trade_date"], format="%Y%m%d")
    qmt["wr"] = pd.to_numeric(qmt["winner_ratio"], errors="coerce")
    n_bad = int(((qmt.wr < 0) | (qmt.wr > 1)).sum())
    qmt = qmt[qmt.wr.between(0, 1)].dropna(subset=["wr"])
    qmt["code"] = qmt["stock_code"].map(to_qlib)
    ev = qmt.merge(cyq[["d", "code", "winner_ratio"]].rename(columns={"winner_ratio": "wr_cyq"}), on=["d", "code"])
    ev = ev.dropna(subset=["wr", "wr_cyq"])
    print(f"QMT 越界剔除 {n_bad}，配对 {len(ev)}")
    if len(ev) < 10:
        return 2
    pear = ev.wr.corr(ev.wr_cyq)
    spear = ev.wr.corr(ev.wr_cyq, method="spearman")
    mae = (ev.wr - ev.wr_cyq).abs().mean()
    t = ev.wr < 0.10
    p = ev.wr_cyq < 0.10
    tp = int((t & p).sum())
    fp = int((~t & p).sum())
    fn = int((t & ~p).sum())
    tn = int((~t & ~p).sum())
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    print(f"连续一致: Pearson={pear:.3f} Spearman={spear:.3f} MAE={mae:.3f}")
    print(
        f"阈值<10% 混淆: TP={tp} FP={fp} FN={fn} TN={tn}  "
        f"精确率={prec:.3f} 召回率={rec:.3f} 一致率={(tp + tn) / len(ev):.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
