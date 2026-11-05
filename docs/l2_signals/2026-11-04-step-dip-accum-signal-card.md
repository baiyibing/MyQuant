# 信号命名：阶跃回调吸筹 `STEP_DIP_ACCUM`

> **定稿日期:** 2026-11-04 · **数据:** 2026 全市场 · **黄金:** `E:/stock_data/step_optimized_2026.csv`

## 信号描述

**大单量阶跃（≥2×前日）出现在「昨跌 + 今跌 + 大买单占成交额仍低」的回调日 → 次日反弹。**
六族中 T+1 胜率最高的主题种子，但 n=21 极小，未作跨年验收。

## 条件定义（可执行，对拍 Exact）

| # | 条件 | 判定 |
|---|---|---|
| C1 放量 | `buyord10w_vol ≥ 2 × 前日` | B 层 10 万档订单聚合 |
| 昨跌 | `ret_prev = 昨收/前收 − 1 < 0` | T-1 收盘为跌 |
| 今跌 | `ret_1d = 今收/昨收 − 1 < 0` | T 日收盘为跌（**不要求阴线 KMID**） |
| 安静 | `bs = buyord10w_amt / total_amt < 0.10` | 大买单额占成交 <10% |

> 易混：交接/搜索脚本有时写 `KMID<0`（收<开）。对拍黄金后锁定为 **收盘跌**（`ret_1d<0`）；黄金里有 2 条阳线但收盘仍跌的样本。

## 2026 实测

| 指标 | 值 |
|---|---|
| 触发 | **21** |
| T+1 胜率 | **76.2%** |
| 黄金对拍 | **Exact 21/21** |

## 复现

```text
D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal STEP_DIP_ACCUM
```

原始搜索导出脚本存档：`l2_signals/baseline_signal_search.py`（最优组合写出同一黄金 CSV）。

## 状态

`archived` · 主题种子，不可直接当可交易信号。启发 gen1「安静回调」方向。
