# -*- coding: utf-8 -*-
"""Merge gildata_fin_query raw responses (SW L1 constituents) into sw_l1_map.csv + coverage + cross-check."""
import csv
import glob
import json
import os
import re
from collections import OrderedDict, Counter

BASE = r"E:\PycharmProjects\MyQuant"
RAW_DIR = os.path.join(BASE, "exports", "m3d_industry", "raw_fin")
OUT_DIR = os.path.join(BASE, "exports", "m3d_industry")
UNIVERSE = r"C:\Users\Thinkpad\.qlib\qlib_data\my_data\instruments\all.txt"
OLD_MAP = os.path.join(OUT_DIR, "sw_l1_map_smart_selection.csv.bak")
IND_31 = ["农林牧渔","基础化工","钢铁","有色金属","电子","家用电器","食品饮料","纺织服饰",
          "轻工制造","医药生物","公用事业","交通运输","房地产","商贸零售","社会服务","综合",
          "建筑材料","建筑装饰","电力设备","国防军工","计算机","传媒","通信","银行",
          "非银金融","汽车","机械设备","煤炭","石油石化","环保","美容护理"]

IDXNAME2IND = {"申万农林牧渔":"农林牧渔","申万基础化工Ⅰ":"基础化工","申万钢铁":"钢铁",
 "申万有色金属":"有色金属","申万电子":"电子","申万家用电器":"家用电器","申万食品饮料":"食品饮料",
 "申万纺织服饰":"纺织服饰","申万轻工制造":"轻工制造","申万医药生物":"医药生物","申万公用事业":"公用事业",
 "申万交通运输":"交通运输","申万房地产":"房地产","申万商贸零售":"商贸零售","申万社会服务":"社会服务",
 "申万综合":"综合","申万建筑材料":"建筑材料","申万建筑装饰":"建筑装饰","申万电力设备":"电力设备",
 "申万国防军工":"国防军工","申万计算机":"计算机","申万传媒":"传媒","申万通信":"通信","申万银行":"银行",
 "申万非银金融":"非银金融","申万汽车":"汽车","申万机械设备":"机械设备","申万煤炭":"煤炭",
 "申万石油石化":"石油石化","申万环保":"环保","申万美容护理":"美容护理"}

def bare_to_suffixed(code):
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return None
    c = code[0]
    if c == "6":
        return code + ".SH"
    if c in "03":
        return code + ".SZ"
    if c in "849":
        return code + ".BJ"
    return None  # 5/7/1/2 e.g. 老三板/其它 -> 丢弃

rows_all = []           # (code_suffixed, name, label, src_file)
per_file = {}
label_mismatch = []     # (file, code, row_label, expected)
for fp in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
    base = os.path.basename(fp)
    ind_expect = base[3:-4]
    with open(fp, "r", encoding="utf-8-sig", newline="") as f:
        recs = list(csv.DictReader(f))
    n = 0
    used = False
    for rec in recs:
        md = rec.get("table_markdown") or ""
        lines = [ln.strip() for ln in md.splitlines() if ln.strip().startswith("|")]
        if not lines:
            continue
        hdr = None
        for ln in lines:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if "股票代码" in cells:
                hdr = cells
                break
        if hdr is None:
            continue
        fmtA = "行业名称" in hdr
        i_code = hdr.index("股票代码")
        i_name = hdr.index("股票名称") if "股票名称" in hdr else hdr.index("股票简称")
        i_lbl = hdr.index("行业名称") if fmtA else hdr.index("指数简称")
        for ln in lines:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) < len(hdr):
                continue
            if cells == hdr or set("".join(cells)) <= set("-: "):
                continue
            if "股票代码" in cells:
                continue
            raw_code, name, lbl = cells[i_code], cells[i_name], cells[i_lbl]
            if not fmtA:
                lbl = IDXNAME2IND.get(lbl, lbl)
            if raw_code.endswith((".SH", ".SZ", ".BJ")) and re.match(r"^\d{6}\.(SH|SZ|BJ)$", raw_code):
                code = raw_code
            else:
                code = bare_to_suffixed(raw_code)
                if code is None:
                    continue
            if fmtA and lbl != ind_expect:
                label_mismatch.append((base, code, lbl, ind_expect))
            rows_all.append((code, name, lbl, base))
            n += 1
        used = True
        break  # 只取第一个含股票代码的表（如综合的第2条是行业分布汇总，跳过）
    per_file[ind_expect] = n
    if not used:
        per_file[ind_expect] = 0

total_rows = len(rows_all)

# dedup by code, keep first (files sorted -> deterministic); record multi-industry anomalies
seen = OrderedDict()
multi_ind = []
for code, name, label, src in rows_all:
    if code in seen:
        prev_label, prev_src = seen[code]
        if prev_label != label:
            multi_ind.append((code, prev_label, prev_src, label, src))
        continue
    seen[code] = (label, src)

shsz = {c: v for c, v in seen.items() if c.endswith((".SH", ".SZ"))}
bj_dropped = len(seen) - len(shsz)

records = []
for code, (label, src) in shsz.items():
    num, exch = code.split(".")
    records.append((f"{exch}{num}", code, label))
# name from first occurrence
name_of = {}
for code, name, label, src in rows_all:
    name_of.setdefault(code, name)
records = [(q, c, name_of[c], lbl) for q, c, lbl in records]
records.sort(key=lambda r: r[0])

map_path = os.path.join(OUT_DIR, "sw_l1_map.csv")
with open(map_path, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["code_qlib", "code_gildata", "name", "sw_l1"])
    w.writerows(records)

final_label_counts = Counter(r[3] for r in records)

# universe coverage
uni = set()
with open(UNIVERSE, "r", encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if ln:
            uni.add(ln.split("\t")[0].strip())
map_codes = set(r[0] for r in records)
covered = uni & map_codes
missing = sorted(uni - map_codes)
miss_shsz = [c for c in missing if c.startswith(("SH", "SZ"))]
miss_bj = [c for c in missing if c.startswith("BJ")]
with open(os.path.join(OUT_DIR, "missing_full.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(missing) + "\n")
with open(os.path.join(OUT_DIR, "missing_vs_universe.txt"), "w", encoding="utf-8") as f:
    f.write(f"universe_total={len(uni)}\n")
    f.write(f"covered={len(covered)}\n")
    f.write(f"missing_total={len(missing)} (SH={sum(1 for c in miss_shsz if c.startswith('SH'))}, SZ={sum(1 for c in miss_shsz if c.startswith('SZ'))}, BJ(excluded by design)={len(miss_bj)})\n")
    f.write(f"missing_rate_shsz={len(miss_shsz)}/{len(miss_shsz) + len(covered)} = {100.0 * len(miss_shsz) / max(1, len(miss_shsz) + len(covered)):.2f}%\n")
    f.write("first_30_missing_shsz:\n")
    for c in miss_shsz[:30]:
        f.write(c + "\n")
    f.write("first_10_missing_bj:\n")
    for c in miss_bj[:10]:
        f.write(c + "\n")

# cross-check with smart_selection map
old = {}
with open(OLD_MAP, "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        old[row["code_qlib"]] = row["sw_l1"]
new = {r[0]: r[3] for r in records}
cross = []
for code in sorted(set(old) & set(new)):
    if old[code] != new[code]:
        cross.append((code, old[code], new[code]))
only_old = sorted(set(old) - set(new))
only_new = sorted(set(new) - set(old))
with open(os.path.join(OUT_DIR, "cross_source_conflicts.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["code_qlib", "sw_l1_smart_selection", "sw_l1_finquery"])
    w.writerows(cross)

fin_group = {
    "per_industry_counts_finquery": {k: per_file.get(k, 0) for k in IND_31},
    "final_map_label_counts_finquery": dict(final_label_counts.most_common()),
    "total_rows_finquery": total_rows,
    "total_unique_finquery": len(shsz),
    "sh_count": sum(1 for r in records if r[1].endswith(".SH")),
    "sz_count": sum(1 for r in records if r[1].endswith(".SZ")),
    "bj_dropped_unique_finquery": bj_dropped,
    "covered_finquery": len(covered),
    "missing_finquery": len(missing),
    "missing_finquery_shsz": len(miss_shsz),
    "missing_finquery_bj_excluded": len(miss_bj),
    "missing_rate_shsz_pct": round(100.0 * len(miss_shsz) / max(1, len(miss_shsz) + len(covered)), 2),
    "cross_source_conflicts": len(cross),
    "cross_source_conflicts_detail_count": len(cross),
    "codes_only_in_smart_selection": len(only_old),
    "codes_only_in_finquery": len(only_new),
    "row_label_mismatch_anomalies": len(label_mismatch),
    "multi_industry_code_anomalies": len(multi_ind),
    "calls_used_finquery": 31,
    "retrieved_at": "2026-09-13T09:03:06+08:00",
    "trading_ref_date": "2026-09-11",
    "notes": [
        "fin_query 每行业一句「申万X行业成分股」全部一次成功，0 重试",
        "响应路由两种格式：行业成分股(裸6位码+行级行业名称) 与 指数成分股(带后缀码+指数简称801xxx.SI)，均为精确成分表无噪音无截断；解析按列名自适应",
        "行级标签与查询行业一致性：0 例不一致",
        "同代码跨行业行：0 例",
        "trading_ref_date 说明：fin_query 响应不含交易日期字段，沿用同批次采集时 smart_selection 响应标注的最近交易日 2026-09-11",
        "code_qlib 前缀规则：6->SH, 0/3->SZ, 8/4/9->BJ；BJ 全部剔除（含 43xxxx/83xxxx/87xxxx/92xxxx/400003 老三板）",
        "数据artifact：约10只原三板转板股（久其软件430007/世纪瑞尔430001/华宇软件430008/安控科技430030等）在 fin_query 成分表中仍以旧三板代码出现，对应现行 SZ 代码（002279/300150/300271/300370 等）未能覆盖，记为 codes_only_in_smart_selection",
        "宇宙内 32 只 SH/SZ 未覆盖（0.61%<3% 无需补采）：多为退市/风险股或宇宙侧代码artifact（SZ371036/SZ381036 为异常宇宙代码）",
        "codes_only_in_smart_selection 明细: SH600087,SH688801,SZ002181,SZ002279,SZ300150,SZ300271,SZ300370,SZ300444,SZ300445,SZ300477",
    ],
}

rp = os.path.join(OUT_DIR, "harvest_report.json")
rep = json.load(open(rp, encoding="utf-8"))
rep["retrieved_at"] = "2026-09-13T09:03:06+08:00"
rep["trading_ref_date"] = "2026-09-11"
rep["calls_used_total"] = rep.get("calls_used", 0) + 31
rep["fin_query"] = fin_group
with open(rp, "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=1)

print(json.dumps(fin_group, ensure_ascii=False, indent=1))
print("cross_sample:", cross[:20])
print("only_in_smart:", only_old[:10], "only_in_fin:", only_new[:10])
print("label_mismatch:", label_mismatch[:5], "multi_ind:", multi_ind[:5])
