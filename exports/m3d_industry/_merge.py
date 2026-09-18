# -*- coding: utf-8 -*-
"""Merge gildata raw responses into SW L1 map + coverage report. Data-collection artifact."""
import csv
import glob
import io
import json
import os
import re
import sys
from collections import OrderedDict, Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(_HERE, "raw")
OUT_DIR = _HERE
UNIVERSE = r"C:\Users\Thinkpad\.qlib\qlib_data\my_data\instruments\all.txt"

CODE_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
EMPTY_LABELS = {"", "-", "--", "None", "nan"}

rows_all = []          # (code, name, label, src_file)
file_summaries = []
for fp in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
    base = os.path.basename(fp)
    try:
        with open(fp, "r", encoding="utf-8-sig", newline="") as f:
            rdr = csv.DictReader(f)
            recs = list(rdr)
    except Exception as e:
        file_summaries.append((base, "READ_ERROR", str(e)))
        continue
    n_rows = 0
    n_kept = 0
    claimed = None
    for rec in recs:
        md = rec.get("table_markdown") or ""
        m = re.search(r"共筛选出\s*(\d+)\s*个", md)
        if m:
            claimed = int(m.group(1))
        lines = [ln.strip() for ln in md.splitlines() if ln.strip().startswith("|")]
        if not lines:
            continue
        hdr = None
        for ln in lines:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if any("证券代码" in c for c in cells):
                hdr = cells
                break
        if hdr is None:
            continue
        try:
            i_code = next(i for i, c in enumerate(hdr) if "证券代码" in c)
            i_name = next(i for i, c in enumerate(hdr) if "证券简称" in c)
            i_ind = next(i for i, c in enumerate(hdr) if "所属申万行业名称" in c)
        except StopIteration:
            continue
        for ln in lines:
            if ln.strip("|").strip().startswith("---"):
                continue
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) < len(hdr):
                continue
            if any("证券代码" in c for c in cells):
                continue  # header repeat
            code = cells[i_code]
            name = cells[i_name]
            label = cells[i_ind]
            n_rows += 1
            cm = CODE_RE.match(code)
            if not cm:
                continue  # malformed code (e.g. 60138X.SH)
            if label in EMPTY_LABELS:
                continue  # delisted / no current SW label
            rows_all.append((code, name, label, base))
            n_kept += 1
    file_summaries.append((base, claimed, n_kept))

total_raw_rows = len(rows_all)
label_counts = Counter(lbl for _, _, lbl, _ in rows_all)

# dedup by code, keep first occurrence; record conflicts
seen = OrderedDict()
conflicts = []
for code, name, label, src in rows_all:
    if code in seen:
        prev_name, prev_label, prev_src = seen[code]
        if prev_label != label:
            conflicts.append((code, prev_name, prev_label, prev_src, name, label, src))
        continue
    seen[code] = (name, label, src)

shsz = {c: v for c, v in seen.items() if c.endswith((".SH", ".SZ"))}
bj_dropped = len(seen) - len(shsz)

# build final map
records = []
for code, (name, label, src) in shsz.items():
    num, exch = code.split(".")
    qlib = f"{exch}{num}"
    records.append((qlib, code, name, label))
records.sort(key=lambda r: r[0])

map_path = os.path.join(OUT_DIR, "sw_l1_map.csv")
with open(map_path, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["code_qlib", "code_gildata", "name", "sw_l1"])
    w.writerows(records)

conf_path = os.path.join(OUT_DIR, "conflicts.csv")
with open(conf_path, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["code_gildata", "name_kept", "label_kept", "src_kept", "name_seen", "label_seen", "src_seen"])
    w.writerows(conflicts)

# universe coverage
uni = []
with open(UNIVERSE, "r", encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if not ln:
            continue
        uni.append(ln.split("\t")[0].strip())
uni_set = set(uni)
map_codes = set(r[0] for r in records)
covered = uni_set & map_codes
missing = sorted(uni_set - map_codes)
missing_sh = sum(1 for c in missing if c.startswith("SH"))
missing_sz = sum(1 for c in missing if c.startswith("SZ"))

miss_path = os.path.join(OUT_DIR, "missing_vs_universe.txt")
missing_shsz_list = [c for c in missing if c.startswith(("SH", "SZ"))]
missing_bj_list = [c for c in missing if c.startswith("BJ")]
with open(miss_path, "w", encoding="utf-8") as f:
    f.write(f"universe_total={len(uni_set)}\n")
    f.write(f"covered={len(covered)}\n")
    f.write(f"missing_total={len(missing)} (SH={missing_sh}, SZ={missing_sz}, BJ(excluded by design)={len(missing_bj_list)})\n")
    f.write(f"missing_rate_shsz={len(missing_shsz_list)}/{len(missing_shsz_list) + len(covered)} = {100.0 * len(missing_shsz_list) / max(1, len(missing_shsz_list) + len(covered)):.2f}%\n")
    f.write("first_30_missing_shsz:\n")
    for c in missing_shsz_list[:30]:
        f.write(c + "\n")
    f.write("first_10_missing_bj:\n")
    for c in missing_bj_list[:10]:
        f.write(c + "\n")

final_label_counts = Counter(r[3] for r in records)

retrieved_max = None
for b, c, k in file_summaries:
    pass
import datetime
retrieved_at = "2026-09-13T08:53:10+08:00"
trading_ref_date = "2026-09-11"

out = {
    "total_raw_rows": total_raw_rows,
    "unique_codes_shsz": len(shsz),
    "sh_count": sum(1 for r in records if r[1].endswith(".SH")),
    "sz_count": sum(1 for r in records if r[1].endswith(".SZ")),
    "bj_dropped_unique": bj_dropped,
    "per_industry_rowlabel_counts": dict(label_counts.most_common()),
    "final_map_label_counts": dict(final_label_counts.most_common()),
    "conflicts_count": len(conflicts),
    "universe_total": len(uni_set),
    "covered": len(covered),
    "missing_count": len(missing),
    "missing_sh": missing_sh,
    "missing_sz": missing_sz,
    "missing_bj_excluded": len(missing_bj_list),
    "missing_rate_shsz_pct": round(100.0 * len(missing_shsz_list) / max(1, len(missing_shsz_list) + len(covered)), 2),
    "calls_used": 64,
    "retrieved_at": retrieved_at,
    "trading_ref_date": trading_ref_date,
    "notes": {
        "api_anomalies": [
            "基础化工/食品饮料/纺织服饰/轻工制造/国防军工/石油石化/美容护理 单行业查询返回0条（NLU行业名映射缺陷）",
            "workaround：和-组合的查询路径可绕过部分坏名（基础化工+钢铁、轻工制造+钢铁、纺织服饰+钢铁(坏名在前)）；国防军工/石油石化/美容护理所有尝试路径均失败",
            "深交所/上交所限定词解析不稳定：'深交所...电子'被忽略返回全市场617(top500)，'上交所...医药生物'行业条件被忽略返回全部上交所2763(top500)",
            "claimed N>500 时仅返回前500行（电子617/医药560/机械设备695/基础化工+钢铁723），尾部约100-220条/行业无法取回",
            "查询结果含其他行业噪音行，已按行级第N列'所属申万行业名称'为准过滤",
            "响应存在个别畸形代码（如60138X.SH/30XXXX.SZ多位数字），已按^\\d{6}\\.(SH|SZ|BJ)$严格校验丢弃",
        ],
        "missing_sample_probe": "对5个缺失代码(600078.SH/688081.SH/002092.SZ/300837.SZ/301036.SZ)单票查询：4个返回0条，1个退化为全市场top500 → 缺失主要是接口侧不可检索(退市/停牌/风险股)叠加>500截断尾部，非解析遗漏",
        "universe_note": "训练宇宙含344只BJ北交所代码，按任务要求仅保留SH/SZ，BJ全部计入missing",
    },
    "files": [{"file": b, "claimed": c, "kept_rows": k} for b, c, k in file_summaries],
}
with open(os.path.join(OUT_DIR, "harvest_report.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "files"}, ensure_ascii=False, indent=1))
