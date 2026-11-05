# -*- coding: utf-8 -*-
"""000801.SZ 2026-05-08..05-21 三个因子条件的手工计算对照（含与 alpha158 产物的对拍）。"""
import duckdb
import numpy as np
import pandas as pd

con = duckdb.connect()
bars = con.execute("""
    SELECT CAST(d AS DATE) d, close_px, low_px
    FROM read_parquet('J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet', hive_partitioning=false)
    WHERE stock_code='000801.SZ' AND d >= DATE '2026-03-01' AND d <= DATE '2026-05-21'
    ORDER BY d""").fetchdf()
bars["d"] = pd.to_datetime(bars["d"]).dt.date

fact = pd.read_parquet("E:/stock_data/l2_research/alpha158_daily.parquet",
                       filters=[("stock_code", "=", "000801.SZ")])
fact["d"] = pd.to_datetime(fact["d"]).dt.date

C1_DAYS = {"2026-05-08", "2026-05-21"}
TH_IMIN, TH_QTLD, TH_RSQR = 0.2, 1.007836, 0.766425

idx = bars.index[bars["d"] >= pd.to_datetime("2026-05-08").date()]
assert len(idx) == 10, len(idx)

lines = []
def P(s=""):
    lines.append(s)

P("=" * 78)
P("000801.SZ  STAB_LOW_TREND 三条件手工计算对照")
P("窗口: 2026-05-08 .. 2026-05-21（10 个交易日；05-08 与 05-21 为 C1 大单阶跃日 ✦）")
P("阈值(冻结): IMIN10 <= 0.2 | QTLD30 >= 1.007836 | RSQR5 >= 0.766425")
P("=" * 78)

for j in idx:
    d = bars.loc[j, "d"]
    c, l = bars["close_px"], bars["low_px"]

    # ---------- IMIN10 ----------
    lows10 = l.loc[j - 9: j].to_numpy()
    pos = int(np.argmin(lows10)) + 1          # 1 基
    imin10 = pos / 10
    lows_str = " ".join(f"{v:.2f}" for v in lows10)

    # ---------- QTLD30 ----------
    closes30 = c.loc[j - 29: j].to_numpy()
    close_t = closes30[-1]
    s = np.sort(closes30)
    h = 0.2 * (30 - 1)                        # 5.8
    lo_i, frac = int(h), h - int(h)           # 5, 0.8
    q20 = s[lo_i] + frac * (s[lo_i + 1] - s[lo_i])
    qtld30 = q20 / close_t

    # ---------- RSQR5 ----------
    y = c.loc[j - 4: j].to_numpy()
    i = np.arange(5.0)
    sy, syy, siy = y.sum(), (y * y).sum(), (i * y).sum()
    si = i.sum()
    b = (5 * siy - si * sy) / (5 * (i * i).sum() - si * si)
    a = sy / 5 - b * si / 5
    fit = a + b * i
    ss_res = ((y - fit) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    rsqr5 = 1 - ss_res / ss_tot

    # ---------- 对拍 ----------
    row = fact[fact["d"] == d]
    ref = (float(row["IMIN10"].iloc[0]), float(row["QTLD30"].iloc[0]), float(row["RSQR5"].iloc[0]))
    ok = (abs(imin10 - ref[0]) < 1e-5 and abs(qtld30 - ref[1]) < 5e-5 and abs(rsqr5 - ref[2]) < 5e-5)

    mark = " ✦C1" if str(d) in C1_DAYS else ""
    P(f"\n──── {d}{mark}   收盘 {close_t:.2f} ────")
    P(f"[1] IMIN10（近10日最低价出现位置/10）")
    P(f"    10日最低价序列(旧→新): {lows_str}")
    P(f"    最低 {lows10.min():.2f} 出现在第 {pos} 天 → IMIN10 = {pos}/10 = {imin10:.1f}"
      f"   {('✅ ≤0.2' if imin10 <= TH_IMIN else '❌ >0.2')}")
    P(f"[2] QTLD30（30日收盘价 q20 分位 / 现价）")
    P(f"    30日收盘(旧→新): {closes30[0]:.2f} ... {closes30[-1]:.2f}（区间 {closes30.min():.2f}~{closes30.max():.2f}）")
    P(f"    升序第6/第7个: s[5]={s[5]:.2f}, s[6]={s[6]:.2f};  h=0.2×29=5.8")
    P(f"    q20 = {s[5]:.2f} + 0.8×({s[6]:.2f}-{s[5]:.2f}) = {q20:.4f}")
    P(f"    QTLD30 = {q20:.4f}/{close_t:.2f} = {qtld30:.6f}"
      f"   {('✅ ≥1.007836' if qtld30 >= TH_QTLD else '❌ <1.007836')}")
    P(f"[3] RSQR5（近5日收盘对时间回归 R²，i=0..4）")
    P(f"    5日收盘: {' '.join(f'{v:.2f}' for v in y)}")
    P(f"    Σy={sy:.3f} Σy²={syy:.3f} Σ(i·y)={siy:.3f} → 斜率 b={b:.5f} 截距 a={a:.4f}")
    P(f"    拟合值: {' '.join(f'{v:.3f}' for v in fit)}")
    P(f"    SS_res={ss_res:.5f} SS_tot={ss_tot:.5f} → R² = 1-{ss_res:.5f}/{ss_tot:.5f} = {rsqr5:.6f}"
      f"   {('✅ ≥0.766425' if rsqr5 >= TH_RSQR else '❌ <0.766425')}")
    P(f"    对拍 alpha158 产物: IMIN10={ref[0]:.1f} QTLD30={ref[1]:.6f} RSQR5={ref[2]:.6f}"
      f"   {'✔一致' if ok else '✘不一致!'}")

P("\n" + "=" * 78)
P("汇总（10 日 × 3 条件）")
P(f"{'日期':<12}{'收盘':>7}{'IMIN10':>8}{'条件①':>6}{'QTLD30':>10}{'条件②':>6}{'RSQR5':>9}{'条件③':>6}  C1")
for j in idx:
    d = bars.loc[j, "d"]
    row = fact[fact["d"] == d].iloc[0]
    im, qt, rs = float(row["IMIN10"]), float(row["QTLD30"]), float(row["RSQR5"])
    eps = 1e-6  # float32 边界容差（如 IMIN10=0.2 存为 0.2000000030）
    c1 = "✦" if str(d) in C1_DAYS else ""
    P(f"{str(d):<12}{bars.loc[j,'close_px']:>7.2f}{im:>8.1f}{'✅' if im<=TH_IMIN+eps else '❌':>5}"
      f"{qt:>10.4f}{'✅' if qt>=TH_QTLD-eps else '❌':>5}{rs:>9.4f}{'✅' if rs>=TH_RSQR-eps else '❌':>5}  {c1}")

out = "E:/stock_data/l2_research/signals/manual_check_000801_202605.txt"
open(out, "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
print(f"\n[saved] {out}")
