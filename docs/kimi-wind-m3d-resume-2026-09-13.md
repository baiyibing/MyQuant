# Kimi 万得行业复核：中断现场与续跑指引（M3-D 行业源）

- 日期：2026-09-13 10:28 中断（Kimi 5 小时额度 403）
- 任务：万得复核申万一级行业（M3-D 行业源，5210 只），产出与 gildata 主源（`sw_l1_map.csv`）的比对
- **续跑者必须是 Kimi**：wind MCP 只挂在 Kimi 侧，Claude/Codex 调不了

## 现场状态（已逐项核验）

```
exports/m3d_industry/
├── sw_l1_map.csv                    5211 行(含表头)=5210 只，gildata 主源映射
├── gildata_sw_industry_all.csv      gildata 全量抓取
├── harvest_report.json / missing_full.txt / missing_vs_universe.txt   前期(gildata)合并报告
├── conflicts.csv / cross_source_conflicts.csv                        冲突记录(小,基本空)
├── _merge.py / _merge_fin.py        合并与比对脚本(续跑复用,勿重写)
├── raw/ raw_fin/ raw_probe/         gildata 各阶段原始件
├── wind_probe/                      wind 探针(q100 等)
└── wind_raw/                        ← 万得复核主战场
    ├── q0000.txt .. q0053.txt       54 个问题文件(⚠ 见尾部对账注意)
    ├── batch_0000.csv .. batch_0034.csv   35 批全部完整(各 101 行=表头+100 代码)
    └── retry_0029..0033 ×a..e + rq*.txt  29~33 批的补漏子块(每批 5 块)
```

## ⚠ 两个必须对账的坑

1. **尾部切分不均**：`q0052.txt` 只含 **10** 个代码、`q0053.txt` 含 **30** 个——不是 53×100 整除。
   合并时按**实际代码集**对账（问题文件里的代码全集 vs sw_l1_map 的 5210），勿按批次号假设。
2. **batch 行数 ≠ 覆盖数**：35 批 × 100 行，但 batch CSV 里唯一代码仅 3049 个——部分行 Wind 返回
   空行业/空代码（retry 子块存在的原因）。真实覆盖以 `_merge_fin.py` 的合并口径为准。

## 续跑步骤（额度恢复后）

1. 逐批发问 `q0035.txt .. q0053.txt`（19 个文件），产出 `batch_0035.csv .. batch_0053.csv`，
   列头与现有一致：`Wind代码,证券简称,申万一级行业,申万一级行业.行业级别`
2. 跑 `_merge_fin.py` 对账：29~33 批的 retry 子块是否补齐空缺，缺的按 `rq*.txt` 续补
3. 最终合并 + 与 `sw_l1_map.csv`（gildata）比对，冲突入 `conflicts*.csv`，报告回写本文件尾部
4. 完成后此目录即 M3-D 的行业源输入（解 block）

## 备份

- `exports/m3d_industry_kimi_20260913.7z`（242 文件 / 228 KiB，2026-09-13 10:31 打包）
- 异地副本：`F:\m3d_industry_kimi_20260913.7z`
- 丢现场时：解压 7z 到 `exports/` 即原地续跑（`exports/*.csv` 不入 git，磁盘是唯一载体，7z 是唯一保险）

## 结果回写区（续跑完成后填）

- （待填：批次数/覆盖率/与 gildata 冲突数/最终行业表路径）
