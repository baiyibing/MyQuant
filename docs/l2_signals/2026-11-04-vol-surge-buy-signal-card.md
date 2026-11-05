# 信号命名：放量买强 `VOL_SURGE_BUY`（=`BIG_ORDER_STEP`）

> **定稿日期:** 2026-11-04 · **数据:** 2026 全市场
> 代号说明：命名卡用 `VOL_SURGE_BUY`；六族交接表曾称 `BIG_ORDER_STEP`（原版全条件）。**同条件，两名并存，以本卡为准。**

## 信号描述

**放量 + 买方主导 + 均线之上 + 大额净流入 —— 表面最强多头共识，实测 T+1 显著跑输基线（反指）。**

## 条件定义（命名卡定稿）

| # | 条件 | 判定 |
|---|---|---|
| C1 放量 | `buyord10w_vol ≥ 2 × 前日` | B 层 |
| C2 买强 | `buyord10w_vol > saleord10w_vol` | |
| C3 技术 | `close > MA20` 且 `close > MA100` | MA100 ≈ 命名卡「MA20周」 |
| C4 大额 | `buyord10w_amt − saleord10w_amt > 3000万` | |

## 2026 实测

| 指标 | 值 |
|---|---|
| 触发（交接） | **11,136** |
| T+1 胜率 | **45.24%** |
| vs 基线 | **−3.05pp**（显著负向） |
| 本仓可执行重跑 | ~10.9k–11.2k（窗/MA 边界略差，同量级同结论） |

### 关于 `big_order_step_v2/v3_2026.csv`

这两份是探索期中间导出，**不是**本卡四条件的 Exact 黄金（对拍 miss/extra 很大）。归档统计以本卡条件 + 交接数字为准，不以 v2/v3 CSV 反推定义。

## 复现

```text
D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal VOL_SURGE_BUY
# 别名
D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal BIG_ORDER_STEP
```

## 状态

`rejected` · 反指。可用作「共识顶部」回避参考，不可做多。
