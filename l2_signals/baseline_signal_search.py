# 存档自 grok-bot-ops PR #105（scripts/ops/signal_search.py），六信号族条件定义的原始出处。
# 后续研究以 search_alpha158.py 为准；本文件保留供对照复现。
# 运行: D:/anaconda3/envs/vanna312/python.exe l2_signals/baseline_signal_search.py
"""大单阶跃 C1 核心信号优化搜索：高胜率低频率，时间切分验证。"""
import duckdb, datetime, itertools, csv, os

con = duckdb.connect()
con.execute("SET threads=8")

ff = con.execute("SELECT stock_code, CAST(m_timetag AS DATE) d, freeFloatCapital FROM read_parquet('E:/stock_data/free_float_shares.parquet') WHERE freeFloatCapital>0 ORDER BY stock_code, d").fetchall()
ff_map = {}
for sc, d, v in ff: ff_map.setdefault(sc, []).append((d, v))

def get_float(sc, d):
    arr = ff_map.get(sc)
    if not arr: return None
    lo, hi = 0, len(arr)-1; result = None
    while lo <= hi:
        mid = (lo+hi)//2
        if arr[mid][0] <= d: result = arr[mid][1]; lo = mid+1
        else: hi = mid-1
    return result

closes = con.execute("""
    SELECT stock_code, CAST(d AS DATE) d, close_px, open_px, high_px, low_px, total_amt
    FROM read_parquet('J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/date=*/part.parquet', hive_partitioning=false)
    WHERE d >= DATE '2025-06-01' ORDER BY stock_code, d""").fetchall()
series = {}
for sc, d, c, o, h, l, ta in closes: series.setdefault(sc, []).append((d, c, o, h, l, ta))

bdata = con.execute("""
    SELECT CAST(d AS DATE) d, stock_code,
           buyord10w_vol, saleord10w_vol, buyord10w_amt, saleord10w_amt,
           buyord10w_active_amt, saleord10w_active_amt,
           lag(buyord10w_vol) OVER (PARTITION BY stock_code ORDER BY d) prev_bov
    FROM read_parquet('J:/l2_lake/rollup/bigorder_daily_2026.parquet')
    ORDER BY stock_code, d""").fetchall()
bmap = {}
for d, sc, bov, sov, bam, sam, baam, saam, pb in bdata:
    bmap.setdefault(sc, []).append((d, bov, sov, bam, sam, baam, saam, pb))

GAP = datetime.date(2026, 1, 5)
MID = datetime.date(2026, 7, 1)

sigs = []
for sc, arr in series.items():
    if len(arr) < 30: continue
    barr = bmap.get(sc)
    if not barr: continue
    bidx = {r[0]: r for r in barr}
    for j in range(25, len(arr)):
        d = arr[j][0]
        if d < GAP: continue
        t1 = arr[j+1][1] if j+1 < len(arr) else None
        if t1 is None: continue
        b = bidx.get(d)
        if b is None or b[7] is None or b[7] <= 0: continue
        bov, sov, bam, sam, baam, saam, pb = b[1], b[2], b[3], b[4], b[5], b[6], b[7]
        if bov < 2 * pb: continue

        close, open_px, high_px, low_px, tamt = arr[j][1], arr[j][2], arr[j][3], arr[j][4], arr[j][5]
        pc = arr[j-1][1]; ppc = arr[j-2][1] if j >= 2 else None
        ma5 = sum(arr[j-4+k][1] for k in range(5)) / 5
        ma10 = sum(arr[j-9+k][1] for k in range(10)) / 10
        ma20 = sum(arr[j-19+k][1] for k in range(20)) / 20
        ma60 = sum(arr[j-59+k][1] for k in range(60)) if j >= 59 else ma20

        r1d = (close - pc) / pc
        retp = (pc - ppc) / ppc if ppc and ppc > 0 else 0
        r3d = (close - arr[j-3][1]) / arr[j-3][1]
        amp = (high_px - low_px) / pc
        nbam = bam - sam
        ddx = baam - saam
        ddxr = ddx / nbam if nbam != 0 else 0
        bs = bam / tamt if tamt > 0 else 0
        ffv = get_float(sc, d)
        nfr = (nbam / ffv) / pc if ffv and ffv > 0 and pc > 0 else None

        sigs.append({
            'd': d, 'sc': sc, 'win': 1 if t1 > close else 0, 'ret1': (t1-close)/close,
            'above5': close > ma5, 'above10': close > ma10, 'above20': close > ma20, 'above60': close > ma60,
            'bull': close > open_px, 'bear': close < open_px, 'bull_p': pc > arr[j-1][2],
            'r1<0': r1d < 0, 'r1<2': r1d < 0.02, 'r1<5': r1d < 0.05,
            'rp<5': retp < 0.05, 'rp<2': retp < 0.02, 'rp<0': retp < 0,
            'r3<5': r3d < 0.05, 'r3<0': r3d < 0,
            'amp<5': amp < 0.05, 'amp<3': amp < 0.03,
            'b>s': bov > sov,
            'nb>200': nbam > 2e6, 'nb>1000': nbam > 1e7, 'nb>3000': nbam > 3e7, 'nb>5000': nbam > 5e7,
            'ddx<75': ddxr < 0.75, 'ddx<50': ddxr < 0.5, 'ddx>0': ddxr > 0,
            'bs<10': bs < 0.10, 'bs>10': bs > 0.10, 'bs>20': bs > 0.20, 'bs>30': bs > 0.30,
            'nfr>05': nfr is not None and nfr > 0.005,
            'nfr>1': nfr is not None and nfr > 0.01,
            'nfr>2': nfr is not None and nfr > 0.02,
        })

h1 = [s for s in sigs if s['d'] < MID]
h2 = [s for s in sigs if s['d'] >= MID]
print(f"C1池: {len(sigs):,}  H1: {len(h1):,}({100*sum(s['win'] for s in h1)/len(h1):.1f}%)  H2: {len(h2):,}({100*sum(s['win'] for s in h2)/len(h2):.1f}%)")

keys = [k for k in sigs[0].keys() if k not in ('d','sc','win','ret1')]

def ev(combo, data):
    sub = [s for s in data if all(s[k] for k in combo)]
    if not sub: return None
    wr = 100 * sum(s['win'] for s in sub) / len(sub)
    avg = 100 * sum(s['ret1'] for s in sub) / len(sub)
    return wr, len(sub), avg

results = []

for k in keys:
    r1 = ev([k], h1); r2 = ev([k], h2)
    if r1 is None or r2 is None or r2[1] < 10: continue
    n_all = r1[1] + r2[1]
    wr_all = (sum(1 for s in sigs if s[k] and s['win']==1)) / n_all * 100
    results.append((wr_all, r1[0], r2[0], n_all, (k,), (r1[2]+r2[2])/2))

ranked = sorted(results, key=lambda x: -x[0])
top12 = [x[4][0] for x in ranked[:12]]
for c in itertools.combinations(top12, 2):
    r1 = ev(list(c), h1); r2 = ev(list(c), h2)
    if r1 is None or r2 is None or r2[1] < 5: continue
    n_all = r1[1] + r2[1]
    if n_all < 20: continue
    wr_all = (sum(1 for s in sigs if all(s[k] for k in c) and s['win']==1)) / n_all * 100
    results.append((wr_all, r1[0], r2[0], n_all, c, (r1[2]+r2[2])/2))

pairs = sorted([x for x in results if len(x[4])==2 and x[0]>52], key=lambda x: -x[0])
pkeys = list(set(k for _,_,_,_,c,_ in pairs[:8] for k in c))
for c in itertools.combinations(pkeys, 3):
    r1 = ev(list(c), h1); r2 = ev(list(c), h2)
    if r1 is None or r2 is None or r2[1] < 3: continue
    n_all = r1[1] + r2[1]
    if n_all < 15: continue
    wr_all = (sum(1 for s in sigs if all(s[k] for k in c) and s['win']==1)) / n_all * 100
    results.append((wr_all, r1[0], r2[0], n_all, c, (r1[2]+r2[2])/2))

triples = sorted([x for x in results if len(x[4])==3 and x[0]>53], key=lambda x: -x[0])
tkeys = list(set(k for _,_,_,_,c,_ in triples[:5] for k in c))
for c in itertools.combinations(tkeys, 4):
    r1 = ev(list(c), h1); r2 = ev(list(c), h2)
    if r1 is None or r2 is None: continue
    n_all = r1[1] + r2[1]
    if n_all < 10: continue
    wr_all = (sum(1 for s in sigs if all(s[k] for k in c) and s['win']==1)) / n_all * 100
    results.append((wr_all, r1[0], r2[0], n_all, c, (r1[2]+r2[2])/2))

validated = [x for x in results if x[2] > 50 and x[3] >= 15]
validated.sort(key=lambda x: -x[0])

print(f"\n===== 通过 H2>50% 验证的 Top 20（按全年合并胜率排）=====")
print(f"{'条件组合':<60} {'n':>6} {'全年%':>6} {'H1%':>6} {'H2%':>6} {'收益':>7}")
print("-" * 95)
seen = set(); shown = 0
for wr_all, wr1, wr2, n, combo, avg in validated:
    desc = " + ".join(combo)
    if desc in seen: continue
    seen.add(desc); shown += 1
    if shown > 20: break
    print(f"{desc:<60} {n:>6,} {wr_all:>5.1f}% {wr1:>5.1f}% {wr2:>5.1f}% {avg:>+6.2f}%")

if not validated:
    print("无组合通过 H2>50% 验证 — C1 核心可能不适合做多信号")

# 最佳组合完整报告
if validated:
    best = validated[0]
    combo = best[4]
    full = [s for s in sigs if all(s[k] for k in combo)]
    wr = 100 * sum(s['win'] for s in full) / len(full)
    avg = 100 * sum(s['ret1'] for s in full) / len(full)
    print(f"\n===== 最优组合 =====")
    print(f"条件: {' + '.join(combo)}")
    print(f"全年: n={len(full):,}  胜率={wr:.1f}%  平均收益={avg:+.2f}%  日均={len(full)/198:.1f}次")

    # 导出明细
    out = "E:/stock_data/step_optimized_2026.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["日期", "代码", "T+1涨跌%", "是否上涨"])
        for s in sorted(full, key=lambda x: x['d']):
            w.writerow([str(s['d']), s['sc'], f"{s['ret1']*100:.2f}", s['win']])
    print(f"已导出: {out} ({os.path.getsize(out)/1024:.0f}KB)")
