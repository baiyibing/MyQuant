# gen0 六信号族索引

> 定稿：2026-11-04 · 源：grok-bot-ops 条件搜索时代 · 可执行复现迁入 MyQuant `l2_signals/`
> 主线已转向 gen1 `STAB_LOW_TREND`；本页只做 gen0 归档与对拍入口。

## 一览

| # | 代号 | 中文 | 方向 | 2026 n / T+1 胜率 | 黄金对拍 | 定义卡 |
|---|---|---|---|---|---|---|
| 1 | `STEP_DIP_ACCUM` | 阶跃回调吸筹 | ✅ 极强（样本极小） | 21 / 76.2% | Exact 21 | [卡](2026-11-04-step-dip-accum-signal-card.md) |
| 2 | `QUIET_DIP_TECH` | 静阴技术 | ≈硬币 | ~4.1万 / ~50% | 无（交接 805/67.8% **无法复现**） | [卡](2026-11-04-quiet-dip-tech-signal-card.md) |
| 3 | `QUIET_DIP_ACCUM` | 缩量阴线吸筹 | ✅ | 18 / 61.1% | Exact 18 | [卡](2026-11-04-quiet-dip-accum-signal-card.md) |
| 4 | `MEGA_ORDER_ACCUM` | 极大单吸筹 | ✅ 一日动量 | 1321 / 50.2% | Exact 1321 | [卡](2026-11-04-mega-order-accum-signal-card.md) |
| 5 | `VOL_SURGE_BUY`（=`BIG_ORDER_STEP`） | 放量买强 | ❌ 反指 | ~1.1万 / 45.2% | 命名卡定稿；v2/v3 CSV 非 Exact | [卡](2026-11-04-vol-surge-buy-signal-card.md) |
| 6 | `DIP_CATCH_FALL` | 接刀吸筹 | ❌ 反指 | 835 / 42.5% | Exact 835 | [卡](2026-11-04-dip-catch-fall-signal-card.md) |

## 复现入口

```text
D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --list
D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal ALL --year 2026
D:/anaconda3/envs/vanna312/python.exe l2_signals/reproduce_gen0_signals.py --signal STEP_DIP_ACCUM
```

专用脚本（与统一脚本同口径，可继续用）：

| 信号 | 脚本 |
|---|---|
| `QUIET_DIP_ACCUM` | `l2_signals/reproduce_quiet_dip_accum.py` |
| `QUIET_DIP_TECH` | `l2_signals/reproduce_quiet_dip_tech.py` |
| 六族统一 | `l2_signals/reproduce_gen0_signals.py` |
| 代号目录 | `l2_signals/signal_catalog.py` |

产出目录：`E:/stock_data/l2_research/signals/`（不入库）。

## 共用口径

| 符号 | 定义 |
|---|---|
| C1 | `buyord10w_vol ≥ 2 × 前日`（订单聚合 >10 万档，B 层） |
| nfr_vol | `(buyord10w_vol − saleord10w_vol) / freeFloatCapital`（点时 ASOF） |
| bs | `buyord10w_amt / total_amt` |
| nbam | `buyord10w_amt − saleord10w_amt` |
| MA100 | 命名卡「MA20周」的可执行代理（约 100 个交易日） |

数据：`J:/l2_lake` core rollup + `bigorder_daily_{year}.parquet` + `E:/stock_data/free_float_shares.parquet`。

## 与 gen1

gen0 最强主题种子是「安静回调 + 低 bs」→ 启发 gen1 `STAB_LOW_TREND`（Alpha158 × C1）。
gen0 本身样本/可交易性未充分验收，状态多为 `archived` / `rejected`，勿直接上线。
