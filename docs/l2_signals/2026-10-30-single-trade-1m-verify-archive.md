# 归档：单笔≥100万「放量×主动买」验证（2026-10-30）

> 历史反指实验。脚本已迁入 MyQuant-infra `scripts/l2/archive_single_trade_1m/`（L2 数据处理归 infra）。
> 全文数字与过程见 ops：`docs/ops/l2-bigorder-signal-verify-20261030.md`。

## 口径（≠ 现行信号 SSOT）

| 项 | 本实验 | 现行 gen0/gen1 |
|---|---|---|
| 大单 | 单笔成交额 ≥ **100 万** | 订单聚合 amt ≥ **10 万**（B 层） |
| 信号 | 大单量 ≥2×前日 ∧ 全日成交额>3000万 ∧ 主动买额≥大单额 | 见各信号定义卡 |
| 数据 | 直读 `J:/l2_lake/l2_parquet` main | 读 rollup + `bigorder_daily` |

## 结论（已复跑核对）

| 指标 | 值 |
|---|---|
| 信号次数 | 90,860 |
| T+1 上涨率 | **45.49%** |
| 对照上涨率 | **46.07%** |
| 差 | **−0.58pp**（独立样本近似 z≈−3.2） |

无交易价值；勿与 `VOL_SURGE_BUY`（订单 10 万档）混称。

## 复现入口

见 MyQuant-infra `scripts/l2/archive_single_trade_1m/README.md`。
