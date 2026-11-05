# 信号命名：接刀吸筹 `DIP_CATCH_FALL`

> **定稿日期:** 2026-11-04 · **数据:** 2026 全市场 · **黄金:** `E:/stock_data/dip_buy_accum_2026.csv`

## 信号描述

**下跌日出现中等以上大单净买入（净量/流通 >2%）——名义「接刀吸筹」，实测 T+1 反指。**

## 条件定义（可执行）

| # | 条件 | 判定 |
|---|---|---|
| 跌日 | `close < 昨收` | 收盘下跌（不要求阴线实体） |
| C2>2% | `nfr_vol = (bov − sov) / freeFloatCapital > 0.02` | 点时 ASOF |

## 2026 实测

| 指标 | 值 |
|---|---|
| 黄金行数 | **835** |
| T+1 胜率（交接） | **42.5%**（反指） |
| 对拍 | **Exact 835/835**（不强制 T+1；有 T+1 子集 ≈830 用于评分） |

## 复现

```text
D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal DIP_CATCH_FALL
```

## 状态

`rejected` · 反指，仅作对照。与 `MEGA_ORDER_ACCUM`（>5%）对照说明：中等净买入在跌日更像出货/对倒，不是建仓。
