# M3-D 行业/市值中性化 — 数据源盘点

- 日期：2026-09-13（Asia/Shanghai）
- 分支：`feat/m3-ranking-only`
- 计划：`docs/plan-midterm-m1m4m2m3-2026-09-13.md` §4 M3-D（条件片）

## 结论标记

```
M3D_STATUS=blocked
```

**本 VM 无可用的全市场行业分类表，跳过截面中性化实现。** 有源后再开实现片（中性化 → TopN + 单测）。

## 盘点表

| 候选源 | 路径 / 探测 | 结果 |
|--------|-------------|------|
| 披露/行业盘 `F:\disclosure_data` | `/mnt/f`、`F:`、环境变量 | **未挂载**；无 `DISCLOSURE*` / `F:` 环境 |
| 湖内 industry 表 | `/workspace` 下 `*industr*` / `*sw_ind*` / `*citics*` parquet·sqlite（排除 vendor/tmp） | **无**行业成分表 |
| MyQuant 仓内 | `docs/` / `my_scripts/` / 数据目录 | **无**行业映射产物；bin-16 亦无 industry 字段 |
| OSkhQuant1.3 | `config/disclosure_alert_sector_catalog.yaml` | 仅告警用手工板块（白酒/银行等少量代码），**不是**可截面中性化的全市场行业分类 |
| OSkhQuant1.3 文档 | `docs/.../industry-*` | 调研/重构方案文档，无数据表 |
| MyQuant-backtrader | turnover-resist / chip 相关 | 换手阻力与筹码，**无**申万/中信行业表 |
| 环境变量 | `INDUSTR*` / `LAKE*` / `QLIB*` / `MYQUANT*` | 仅见 `OSKH_DATA_ROOT=/workspace/OSkhQuant1.3`，无行业路径 |

## 为何不算「有源」

截面中性化需要：**交易日 × 股票 → 行业（或市值）** 的 as-of 映射，覆盖训练/预测宇宙。告警用几十只「板块示例」无法支撑 TopN 前的残差化。

市值中性化若仅用价格×股本近似：bin-16 有 `close`/`volume`/`adfadfbasiccurhold`，但计划写明先盘点**行业分类**源；无行业源时本片整体 blocked，不强行做半套市值残差以免与计划验收不一致。

## 解锁条件（宿主）

1. 挂载或拷贝可用行业表（如 `F:\disclosure_data` 中申万/中信成分，或湖表）
2. 回写本文件：改 `M3D_STATUS=ready` 并注明路径/日历/as-of 语义
3. 另开实现：截面中性化（行业 dummy / 市值回归残差）→ 再取 TopN + 单测

## 本 PR 交付

- 本盘点文档 + `M3D_STATUS=blocked`
- `my_tests/test_m3d_industry_neutral_blocked.py` 锁定 blocked 标记
- **不**实现 `cross_section_neutralize` 生产路径
