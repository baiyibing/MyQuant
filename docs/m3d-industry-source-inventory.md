# M3-D 行业/市值中性化 — 数据源盘点

- 日期：2026-09-13（Asia/Shanghai，行业源已解锁并完成万得复核）
- 分支：master（工作树携带 gildata 主源与 wind 复核产物，等待提交）
- 计划：`docs/plan-midterm-m1m4m2m3-2026-09-13.md` §4 M3-D（条件片）

## 结论标记

```
M3D_STATUS=ready
```

**行业分类源已就绪**（2026-09-13 通过 Kimi datasource 插件落地，见下「可用行业源」）。
实现片（截面中性化 → TopN + 单测）另开，本片只回写源与语义。

## 可用行业源（本次新增）

| 项 | 值 |
|----|----|
| 映射表 | `exports/m3d_industry/sw_l1_map.csv`（UTF-8 无 BOM，按 code_qlib 排序） |
| Schema | `code_qlib,code_gildata,name,sw_l1`（例：`SH600519,600519.SH,贵州茅台,食品饮料`） |
| 覆盖 | **5210 只 SH/SZ**（SH 2317 / SZ 2893）；对训练宇宙（`~/.qlib/qlib_data/my_data/instruments/all.txt`，5583 只）覆盖 5207 = **93.3%**；SH/SZ 口径仅缺 32 只 = **0.61%** |
| 行业口径 | 申万一级（2021 版，31 个行业全齐；计数：机械设备 539、电子 493、医药生物 478、基础化工 411、电力设备 377 … 综合 20） |
| 来源 | Kimi datasource 插件 3.4.0 `gildata`（恒生聚源）→ `gildata_fin_query` API「申万{行业}行业成分股」，31 句一次全成、无截断 |
| 采集审计 | `exports/m3d_industry/raw_fin/`（31 份原始响应）、`_merge_fin.py`、`harvest_report.json`；全程 95 次插件调用 |
| 双源校验 | 与 `gildata_smart_stock_selection` 噪音版（备份 `sw_l1_map_smart_selection.csv.bak`）重叠代码 **0 冲突**；行级标签 0 异常 |

### 日历 / as-of 语义

- 快照取数日 **2026-09-13**（Asia/Shanghai），成分交易参照日 **2026-09-11**（最近交易日）。
- **现行分类回看**：训练窗（2026-03-02 ~ 2026-08）内使用 2026-09-11 的现行申万分类，申万年度调样不在窗内逐日回放 → 存在 point-in-time 偏差（每年 5–6 月调样涉及的股票数占比小，v1 接受；M5 复盘时若敏感可升级）。
- 非逐日映射：实现片按「快照静态映射」用，不构造 交易日×股票 长表。

### 未覆盖与处理

- 宇宙内 **344 只北交所**（`.BJ`）按设计剔除（训练宇宙 bin 数据无 BJ）。
- SH/SZ 缺失 32 只：多为退市/风险股（接口不收录）+ 宇宙内 2 个畸形码（`SZ371036`/`SZ381036`）+ ~10 只三板 legacy 码（如久其软件以 `430007` 旧码在成分表中，现行 SZ 码未覆盖）。
- 实现片约定：无行业标签的股票进「未知」dummy 桶，不进残差回归的自变量缺失。

## 接口教训（gildata / 插件侧，后续复用注意）

1. `get_data_source_desc` 对 3.3.0/3.4.0 新增源路由错位（要 `gildata` 给 `stock_finance_data` 的文档、`wind` 给 `yahoo_finance`、`imf` 给 `world_bank_open_data`；3.2.0 旧源正常）——后端 bug，本机修不了，已按插件规范只上报不硬试。取数可走「报错即列出可用 API」的路径发现接口名。
2. `gildata_smart_stock_selection`：NLU 筛选有噪音（行级标签才准）、结果 500 行截断无分页、7 个行业名（基础化工/国防军工/石油石化等）解析必返 0、交易所限定词常被忽略——**不适合**做全量成分采集。
3. `gildata_fin_query`：结构化查询，精确成分表、无截断，是申万成分的正确入口。
4. 本次采集共 95 次计费调用；后续刷新快照只需 31 次（fin_query 每行业一句）。

## 万得独立复核

用户要求以万得为权威源对 `sw_l1_map.csv` 做全量独立复核。

| 项 | 值 |
|----|----|
| 复核表 | `exports/m3d_industry/wind_l1_map.csv` |
| 调用 | `wind_get_financial_data`（问题串：100 个 code 用「、」连接 +「的申万一级行业」） |
| 批次数 | 54/54 完成（batch_0000–0053）；其中 0029–0033/0035/0037/0041/0042/0043 首采返回 canned 演示数据，已标 `.bogus.csv` 并用 20/50 码子块补齐；**0 丢码** |
| 返回记录 | 5240 条（含 q0053 中 30 只退市股，不在 sw_l1_map 的 5210 之内） |
| 对齐口径 | overlap = 5210，wind_missing = 0 |
| 冲突 | raw 口径 0 条，归一化口径 0 条 |
| 一致率 | 1.000000（raw & normalized） |
| 抽查 | 600519.SH=食品饮料、000001.SZ=银行、300750.SZ=电力设备、601857.SH=石油石化、002594.SZ=汽车 全部一致 |
| 结论 | gildata 主源与 wind 权威源在训练宇宙 5210 只上申万一级行业完全一致，`sw_l1_map.csv` 可直接作为 M3-D 行业源 |

产物：
- `exports/m3d_industry/wind_conflicts.csv`：仅表头，0 行冲突
- `exports/m3d_industry/wind_crosscheck.json`：含 agreement_rate、wind_missing、progress_note
- `exports/m3d_industry/wind_raw/`：全部原始响应与 retry 子块（含 `.bogus.csv` 证据）

## 原盘点表（2026-09-13 早前结论，留档）

| 候选源 | 路径 / 探测 | 结果 |
|--------|-------------|------|
| 披露/行业盘 `F:\disclosure_data` | `/mnt/f`、`F:`、环境变量 | **未挂载**；无 `DISCLOSURE*` / `F:` 环境 |
| 湖内 industry 表 | `/workspace` 下 `*industr*` / `*sw_ind*` / `*citics*` parquet·sqlite（排除 vendor/tmp） | **无**行业成分表 |
| MyQuant 仓内 | `docs/` / `my_scripts/` / 数据目录 | **无**行业映射产物；bin-16 亦无 industry 字段 |
| OSkhQuant1.3 | `config/disclosure_alert_sector_catalog.yaml` | 仅告警用手工板块（白酒/银行等少量代码），**不是**可截面中性化的全市场行业分类 |
| OSkhQuant1.3 文档 | `docs/.../industry-*` | 调研/重构方案文档，无数据表 |
| MyQuant-backtrader | turnover-resist / chip 相关 | 换手阻力与筹码，**无**申万/中信行业表 |
| 环境变量 | `INDUSTR*` / `LAKE*` / `QLIB*` / `MYQUANT*` | 仅见 `OSKH_DATA_ROOT=/workspace/OSkhQuant1.3`，无行业路径 |

## 解锁条件对照（宿主）

1. ✅ 挂载或拷贝可用行业表 → 本次以 Kimi datasource `gildata` 申万成分表落地（无需 F: 盘）
2. ✅ 回写本文件：`M3D_STATUS=ready`，路径/日历/as-of 语义见「可用行业源」
3. ⏭ 另开实现：截面中性化（行业 dummy / 市值回归残差）→ 再取 TopN + 单测（**本片不做**）

## 本 PR 交付边界

- 行业映射表 + 采集审计 + 本盘点回写（工作树未提交）
- `my_tests/test_m3d_industry_source_ready.py` 锁定 ready 状态与映射表 schema/覆盖率下限
- **不**实现 `cross_section_neutralize` 生产路径（保持「无假实现」守卫）
