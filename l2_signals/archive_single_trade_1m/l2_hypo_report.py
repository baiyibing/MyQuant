"""猜想验证统计器：大单放量 2x + 成交额>3000万 + 主动买入额>=大单额 → T+1 收盘涨跌。

归档自 grok-bot-ops `scripts/ops/l2_hypo_report.py`（删于 022f820）。
用法:
  python l2_hypo_report.py <agg_csv>          # agg_csv 来自 l2_agg_daily_metrics.py
性能埋点：CSV 加载+窗口表构建、各统计块分别计时，收尾输出汇总。
报告内容（与 ops docs/ops/l2-bigorder-signal-verify-20261030.md 的数字一一对应）：
  0. 样本池与无条件基线
  1. 猜想字面判定（C1+C2）
  2. C2 筛选力（通过率、大单额占成交额比）
  3/4. C2 严格解读变体（大单内主动买占比 >=50% / =100%）
  5. 仅 C1 对照
  6. 特大单（>=500万）阈值敏感性
  7. 放量倍数分桶
  8. 逐月分布
  9. 大单主动买占比分桶
"""
import argparse
from datetime import date
from pathlib import Path
import time
import duckdb

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("csv", nargs="?", default="agg_v2.csv", type=Path)
ap.add_argument("--start", default="2026-01-01", type=lambda v: date.fromisoformat(v).isoformat())
ap.add_argument("--end", default="2026-12-31", type=lambda v: date.fromisoformat(v).isoformat())
args = ap.parse_args()
if args.start > args.end:
    ap.error("start must be <= end")
csv_sql = "'" + args.csv.as_posix().replace("'", "''") + "'"
t0 = time.time()
con = duckdb.connect()
con.execute(f"""
    CREATE TABLE f AS
    WITH t AS (
      SELECT CAST(d AS DATE) d, * EXCLUDE (d),
             lead(close_px) OVER w AS close_t1, lead(d) OVER w AS d_t1,
             lag(big1_vol) OVER w AS b1v_tm1, lag(big5_vol) OVER w AS b5v_tm1, lag(d) OVER w AS d_tm1
      FROM read_csv({csv_sql}, header=true)
      WINDOW w AS (PARTITION BY stock_code ORDER BY d)
    )
    SELECT *, (close_t1 - close_px)/close_px AS ret1 FROM t
""")

t_load = time.time() - t0
print(f"[perf] load+build table: {t_load:.2f}s", flush=True)


def show(title, sql, n=25):
    ts = time.time()
    print(f"\n===== {title} =====")
    cur = con.execute(sql)
    print(" | ".join(c[0] for c in cur.description))
    rows = 0
    for i, r in enumerate(cur.fetchall()):
        if i >= n:
            break
        print(" | ".join("NULL" if v is None else str(v) for v in r))
        rows += 1
    print(f"[perf] {time.time()-ts:.3f}s", flush=True)


DATE_RANGE = f"d BETWEEN DATE '{args.start}' AND DATE '{args.end}'"
UNI = f"{DATE_RANGE} AND close_t1 IS NOT NULL AND b1v_tm1>0 AND total_amt>3e7"
SIGNAL = "big1_vol>=2*b1v_tm1 AND buy_amt>=big1_amt"
print("口径: 单笔成交额>=100万元；T±1为该票相邻有成交观测日；不代表订单聚合>10万SSOT。")

show("0. 样本池与无条件基线", f"""
    SELECT count(*) n_stockdays,
           sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END) up,
           round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           round(avg(ret1)*100,3) avg_ret_pct
    FROM f WHERE {UNI}
""")

show("1. 猜想字面判定: C1(大单量>=2x前日 且 成交额>3000万) 且 C2(全天主动买入额>=大单额)", f"""
    SELECT count(*) n, sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END) up,
           round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           sum(CASE WHEN close_t1<close_px THEN 1 ELSE 0 END) down, sum(CASE WHEN close_t1=close_px THEN 1 ELSE 0 END) flat,
           round(avg(ret1)*100,3) avg_ret_pct, round(median(ret1)*100,3) med_ret_pct
    FROM f WHERE {UNI} AND big1_vol>=2*b1v_tm1 AND buy_amt>=big1_amt
""")

show("1b. 同一母池的信号/互补对照（直接输出精确上涨计数与比例）", f"""
    SELECT CASE WHEN {SIGNAL} THEN 'signal' ELSE 'control' END grp,
           count(*) n,
           sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END) up,
           100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0) win_pct,
           avg(ret1)*100 avg_ret_pct
    FROM f WHERE {UNI} GROUP BY 1 ORDER BY 1
""")

show("1c. 两比例差（独立样本近似，未按股票/日期聚类）", f"""
    WITH labeled AS (
        SELECT ({SIGNAL}) sig, (close_t1>close_px)::INTEGER up FROM f WHERE {UNI}
    ), counts AS (
        SELECT count(*) FILTER (WHERE sig) ns, count(*) FILTER (WHERE NOT sig) nc,
               coalesce(sum(up) FILTER (WHERE sig),0) us,
               coalesce(sum(up) FILTER (WHERE NOT sig),0) uc FROM labeled
    ), rates AS (
        SELECT *,us*1.0/nullif(ns,0) ps,uc*1.0/nullif(nc,0) pc,
               (us+uc)*1.0/nullif(ns+nc,0) pooled FROM counts
    ) SELECT ns,us,nc,uc,100*ps signal_win_pct,100*pc control_win_pct,
             100*(ps-pc) diff_pp,
             (ps-pc)/nullif(sqrt(pooled*(1-pooled)*(1.0/nullif(ns,0)+1.0/nullif(nc,0))),0) z_independent
      FROM rates
""")

show("2. C2 筛选力: 全天主动买入额>=大单额 的通过率", f"""
    SELECT count(*) total, sum(CASE WHEN buy_amt>=big1_amt THEN 1 ELSE 0 END) pass,
           round(100.0*sum(CASE WHEN buy_amt>=big1_amt THEN 1 ELSE 0 END)/nullif(count(*),0),1) pass_pct,
           round(avg(big1_amt/NULLIF(total_amt,0))*100,1) avg_big_share_pct
    FROM f WHERE {UNI}
""")

show("3. C2 变体A: 大单内主动买额 >= 大单额*0.5", f"""
    SELECT count(*) n, sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END) up,
           round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           round(avg(ret1)*100,3) avg_ret_pct, round(median(ret1)*100,3) med_ret_pct
    FROM f WHERE {UNI} AND big1_vol>=2*b1v_tm1 AND big1_buy_amt>=0.5*big1_amt
""")

show("4. C2 变体B: 大单内主动买额 >= 大单额 (全部大单都是主动买)", f"""
    SELECT count(*) n, sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END) up,
           round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           round(avg(ret1)*100,3) avg_ret_pct, round(median(ret1)*100,3) med_ret_pct
    FROM f WHERE {UNI} AND big1_vol>=2*b1v_tm1 AND big1_buy_amt>=1.0*big1_amt
""")

show("5. 对照: 仅C1", f"""
    SELECT count(*) n, sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END) up,
           round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           round(avg(ret1)*100,3) avg_ret_pct
    FROM f WHERE {UNI} AND big1_vol>=2*b1v_tm1
""")

show("6. 阈值敏感性: 特大单(>=500万)", f"""
    SELECT count(*) n, sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END) up,
           round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           round(avg(ret1)*100,3) avg_ret_pct
    FROM f WHERE {DATE_RANGE} AND close_t1 IS NOT NULL AND b5v_tm1>0 AND total_amt>3e7
      AND big5_vol>=2*b5v_tm1 AND buy_amt>=big5_amt
""")

show("7. 放量倍数分桶 (C1满足后)", f"""
    SELECT CASE WHEN big1_vol>=5*b1v_tm1 THEN 'd>=5x' WHEN big1_vol>=3*b1v_tm1 THEN 'd:3-5x' ELSE 'd:2-3x' END grp,
           count(*) n, round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           round(avg(ret1)*100,3) avg_ret_pct
    FROM f WHERE {UNI} AND big1_vol>=2*b1v_tm1
    GROUP BY 1 ORDER BY 1
""")

show("8. 逐月 (字面判定)", f"""
    SELECT strftime(d,'%Y-%m') ym, count(*) n,
           round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),1) win_pct,
           round(avg(ret1)*100,2) avg_ret
    FROM f WHERE {UNI} AND big1_vol>=2*b1v_tm1 AND buy_amt>=big1_amt
    GROUP BY 1 ORDER BY 1
""")

show("9. 大单主动买占比分桶 (C1满足后)", f"""
    SELECT CASE WHEN big1_buy_amt>=1.0*big1_amt THEN 'a:100%'
                WHEN big1_buy_amt>=0.75*big1_amt THEN 'b:75-100%'
                WHEN big1_buy_amt>=0.5*big1_amt THEN 'c:50-75%'
                WHEN big1_buy_amt>=0.25*big1_amt THEN 'd:25-50%'
                ELSE 'e:<25%' END grp,
           count(*) n, round(100.0*sum(CASE WHEN close_t1>close_px THEN 1 ELSE 0 END)/nullif(count(*),0),2) win_pct,
           round(avg(ret1)*100,3) avg_ret
    FROM f WHERE {UNI} AND big1_vol>=2*b1v_tm1 AND big1_amt>0
    GROUP BY 1 ORDER BY 1
""")

print(f"\n[perf] total wall: {time.time()-t0:.2f}s (load {t_load:.2f}s + queries)", flush=True)
