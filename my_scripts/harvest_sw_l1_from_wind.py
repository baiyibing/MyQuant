#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wind 申万一级行业批量采集后处理脚本（配合 Kimi datasource MCP 使用）。

工作流：
1. 准备阶段（本机/无额度）：运行 `--generate-questions`，按参考表切分为 100 码一批，
   生成 `wind_raw/q0000.txt` 等问题串文件。
2. 采集阶段（Kimi agent）：把本脚本和 prompt 文件交给 Kimi agent，由它调用 MCP
   `wind_get_financial_data` 逐批发问，每个结果保存为 `wind_raw/batch_NNNN.csv`。
   若某批返回 canned/空码/空行业，agent 将该批标为 `.bogus.csv` 并用 20/50 码 retry
   子块补齐。
3. 合并阶段（本机/无额度）：运行 `--merge`，把有效 batch + retry CSV 合并为
   `wind_l1_map.csv`。
4. 比对阶段（本机/无额度）：运行 `--compare`，与 gildata 主源比对，生成
   `wind_conflicts.csv` 和 `wind_crosscheck.json`。

示例：
    python my_scripts/harvest_sw_l1_from_wind.py --all --map exports/m3d_industry/sw_l1_map.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

DEFAULT_MAP = "exports/m3d_industry/sw_l1_map.csv"
DEFAULT_WIND_DIR = "exports/m3d_industry/wind_raw"
DEFAULT_OUTPUT_DIR = "exports/m3d_industry"
DEFAULT_BATCH_SIZE = 100


def normalize_industry(name: str) -> str:
    """去掉空格与括号后缀，用于跨源行业名比对。"""
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"[\s（）\(\)]+", "", s)
    return s.strip()


def normalize_wind_code(code: str) -> str | None:
    """统一为大写 .SH/.SZ/.BJ 格式，空/无效返回 None。"""
    if not code:
        return None
    c = code.strip().upper()
    if not re.match(r"^\d{6}\.(SH|SZ|BJ)$", c):
        return None
    return c


def load_ref_map(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_wind_csv(path: Path) -> list[dict[str, str]]:
    """读取 Wind 返回的 CSV，兼容列头里带点号的「申万一级行业.行业级别」。"""
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            # 列名在不同响应里可能有「申万一级行业」或「申万一级行业.行业级别」
            code = None
            name = None
            industry = None
            for k, v in r.items():
                if v is None:
                    continue
                kk = k.strip() if k else ""
                if kk.startswith("Wind") or kk.startswith("代码"):
                    code = v.strip() if v else None
                elif "简称" in kk:
                    name = v.strip() if v else None
                elif kk == "申万一级行业" or ("申万" in kk and "行业" in kk and "级别" not in kk):
                    industry = v.strip() if v else None
            if code and industry:
                rows.append({"Wind代码": code, "证券简称": name or "", "申万一级行业": industry})
        return rows


def generate_questions(
    map_rows: list[dict[str, str]],
    wind_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
    suffix: str = "的申万一级行业",
) -> list[list[str]]:
    """按 batch_size 切分参考表的 code_gildata，生成问题串文件。"""
    codes = [r["code_gildata"] for r in map_rows if r.get("code_gildata")]
    batches: list[list[str]] = []
    wind_dir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(codes), batch_size):
        batch = codes[i : i + batch_size]
        batches.append(batch)
        qfile = wind_dir / f"q{i // batch_size:04d}.txt"
        qfile.write_text(
            "、".join(batch) + suffix,
            encoding="utf-8",
        )
    return batches


def merge_wind_csvs(wind_dir: Path) -> dict[str, tuple[str, str]]:
    """合并 wind_raw/ 下所有非 bogus 的 batch/retry CSV，返回 code→(name, industry)。"""
    results: dict[str, tuple[str, str]] = {}
    files = sorted(wind_dir.glob("batch_*.csv")) + sorted(wind_dir.glob("retry_*.csv"))
    for fp in files:
        if ".bogus." in fp.name:
            continue
        for r in load_wind_csv(fp):
            code = normalize_wind_code(r["Wind代码"])
            if not code:
                continue
            industry = r.get("申万一级行业", "").strip()
            if not industry:
                continue
            name = r.get("证券简称", "").strip()
            # 若同一个 code 出现多次，断言行业一致，否则 later wins 并打印警告
            if code in results and results[code][1] != industry:
                print(
                    f"WARN duplicate conflict {code}: {results[code][1]} vs {industry}",
                    file=sys.stderr,
                )
            results[code] = (name, industry)
    return results


def write_wind_map(
    wind_map: dict[str, tuple[str, str]],
    output_dir: Path,
) -> Path:
    path = output_dir / "wind_l1_map.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code_gildata", "name", "wind_sw_l1"])
        for code in sorted(wind_map):
            name, industry = wind_map[code]
            writer.writerow([code, name, industry])
    return path


def compare_with_ref(
    wind_map: dict[str, tuple[str, str]],
    ref_rows: list[dict[str, str]],
    output_dir: Path,
) -> dict:
    ref_by_code: dict[str, dict[str, str]] = {}
    for r in ref_rows:
        code = r.get("code_gildata", "").strip().upper()
        if code:
            ref_by_code[code] = r

    overlap = set(wind_map) & set(ref_by_code)
    wind_missing = sorted(set(ref_by_code) - set(wind_map))
    conflicts_raw: list[dict] = []
    conflicts_norm: list[dict] = []
    for code in sorted(overlap):
        ref = ref_by_code[code]
        wind_name, wind_ind = wind_map[code]
        gildata_ind = ref.get("sw_l1", "").strip()
        if gildata_ind != wind_ind:
            conflicts_raw.append(
                {
                    "code_gildata": code,
                    "name": ref.get("name", wind_name),
                    "gildata_sw_l1": gildata_ind,
                    "wind_sw_l1": wind_ind,
                }
            )
        norm_equal = normalize_industry(gildata_ind) == normalize_industry(wind_ind)
        if not norm_equal:
            conflicts_norm.append(
                {
                    "code_gildata": code,
                    "name": ref.get("name", wind_name),
                    "gildata_sw_l1": gildata_ind,
                    "wind_sw_l1": wind_ind,
                }
            )

    # 写冲突清单
    conflicts_path = output_dir / "wind_conflicts.csv"
    with conflicts_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code_gildata", "name", "gildata_sw_l1", "wind_sw_l1", "normalized_equal"])
        for c in conflicts_raw:
            norm_eq = 1 if normalize_industry(c["gildata_sw_l1"]) == normalize_industry(c["wind_sw_l1"]) else 0
            writer.writerow(
                [c["code_gildata"], c["name"], c["gildata_sw_l1"], c["wind_sw_l1"], norm_eq]
            )

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "expected": len(ref_by_code),
        "wind_returned": len(wind_map),
        "wind_missing": wind_missing,
        "overlap": len(overlap),
        "agree_raw": len(overlap) - len(conflicts_raw),
        "agree_normalized": len(overlap) - len(conflicts_norm),
        "agreement_rate_raw": round((len(overlap) - len(conflicts_raw)) / max(len(overlap), 1), 6),
        "agreement_rate_normalized": round(
            (len(overlap) - len(conflicts_norm)) / max(len(overlap), 1), 6
        ),
        "conflicts_raw_count": len(conflicts_raw),
        "conflicts_normalized_count": len(conflicts_norm),
        "conflicts_preview": conflicts_raw[:10],
        "progress_note": "",
    }
    report_path = output_dir / "wind_crosscheck.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 简单打印
    print(f"overlap={len(overlap)} wind_missing={len(wind_missing)} "
          f"raw_conflicts={len(conflicts_raw)} norm_conflicts={len(conflicts_norm)}")
    print(f"agreement raw={report['agreement_rate_raw']} normalized={report['agreement_rate_normalized']}")
    print(f"wrote {conflicts_path}, {report_path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Wind SW L1 industry harvest helper")
    parser.add_argument("--map", default=DEFAULT_MAP, help="reference map CSV")
    parser.add_argument("--wind-dir", default=DEFAULT_WIND_DIR, help="dir for q files and batch CSVs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="output dir")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="codes per question")
    parser.add_argument("--generate-questions", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--all", action="store_true", help="generate + merge + compare")
    args = parser.parse_args()

    if not (args.generate_questions or args.merge or args.compare or args.all):
        parser.print_help()
        return 0

    map_path = Path(args.map)
    wind_dir = Path(args.wind_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ref_map_path = Path(args.map)

    if args.generate_questions or args.all:
        ref_rows = load_ref_map(ref_map_path)
        batches = generate_questions(ref_rows, wind_dir, args.batch_size)
        print(f"generated {len(batches)} question files in {wind_dir}")
        # 打印最后一批大小作为尾部检查
        if batches:
            print(f"last batch size: {len(batches[-1])}")

    if args.merge or args.compare or args.all:
        wind_map = merge_wind_csvs(wind_dir)
        print(f"merged {len(wind_map)} valid codes from {wind_dir}")
        wind_map_path = write_wind_map(wind_map, output_dir)
        print(f"wrote {wind_map_path}")

    if args.compare or args.all:
        ref_rows = load_ref_map(ref_map_path)
        report = compare_with_ref(wind_map, ref_rows, output_dir)
        if report["agreement_rate_normalized"] < 0.98:
            print("WARN normalized agreement < 98%; inspect wind_conflicts.csv", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
