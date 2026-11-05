# 归档：单笔≥100万「放量×主动买」验证（2026-10-30）

> 历史反指实验。**工具 SSOT 在 MyQuant-infra**（贴湖探查）；本卡只留结论与指针。
> 实验档案卡：infra `scripts/l2/archive_single_trade_1m/README.md`
> 全文数字：ops `docs/ops/l2-bigorder-signal-verify-20261030.md`

## 口径（≠ 现行信号 SSOT）

| 项 | 本实验 | 现行 gen0/gen1 |
|---|---|---|
| 大单 | 单笔成交额 ≥ **100 万** | 订单聚合 amt ≥ **10 万**（B 层） |
| 信号 | 大单量 ≥2×前日 ∧ 全日成交额>3000万 ∧ 主动买额≥大单额 | 见各信号定义卡 |
| 数据 | 直读 `l2_parquet` main（infra research） | 读 rollup + `bigorder_daily` |

## 结论（已复跑核对）

| 指标 | 值 |
|---|---|
| 信号次数 | 90,860 |
| T+1 上涨率 | **45.49%** |
| 对照上涨率 | **46.07%** |
| 差 | **−0.58pp**（独立样本近似 z≈−3.2） |

无交易价值；勿与 `VOL_SURGE_BUY`（订单 10 万档）混称。

## 复现（infra 正式 CLI）

```sh
python -m myquant_infra.l2.research agg-daily-metrics \
  --lake J:/l2_lake/l2_parquet \
  --out E:/stock_data/l2_research/single_trade_1m/agg_v2.csv \
  --start 2026-01-01 --end 2026-10-26 --lookback 1 --forward-days 1 --on-dup fail

python -m myquant_infra.l2.research hypo-report \
  E:/stock_data/l2_research/single_trade_1m/agg_v2.csv \
  --start 2026-01-01 --end 2026-10-26
```

谱系：ops `fa1c42e` → infra Knife 14 `l2/research/` → ops 删原脚本 `022f820` → 本仓只留摘要卡。
