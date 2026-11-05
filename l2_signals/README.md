# l2_signals — L2 大单 × Alpha158 联合信号研究

> 建线：2026-11-04 · 从 grok-bot-ops PR #105 的信号探索（6 信号族、安静吸筹洞察）延续而来。
> 定位遵循三仓分工：**MyQuant 出信号**，backtrader 向量化研究，1.3 执行验收。

## 定位与边界

- **读侧研究**：只读消费 `J:/l2_lake`（core rollup + bigorder B 层），不写湖。
- 湖写侧、跑批、修湖归 grok-bot-ops / myquant_infra；本模块只出信号与研究成果。
- 研究产出（parquet/csv）写 `E:/stock_data/l2_research/`，数据文件不入库。

## 数据依赖

| 数据 | 路径 | 说明 |
|---|---|---|
| core rollup（291 列日线） | `J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/` | OHLCV + vwap + total_vol |
| 大单 B 层（日频） | `J:/l2_lake/rollup/bigorder_daily_2026.parquet` | 10 万档大单买卖量额 |
| 自由流通股本 | `E:/stock_data/free_float_shares.parquet` | PIT 对齐 |
| Alpha158 因子（本模块产出） | `E:/stock_data/l2_research/alpha158_daily.parquet` | 158 因子，d≥2025-01-01 |

## 信号代号（口头怎么叫）

规范名用英文代号（代码 / CSV / `--signal` 唯一键）；中文是别名。目录 SSOT：
`l2_signals/signal_catalog.py`（`python l2_signals/signal_catalog.py` 可打印）。

| 代号 | 中文名 | 代 | 状态 |
|---|---|---|---|
| `STEP_DIP_ACCUM` | 阶跃回调吸筹 | 0 | archived |
| `QUIET_DIP_TECH` | 静阴技术 | 0 | rejected |
| `QUIET_DIP_ACCUM` | 缩量阴线吸筹 | 0 | archived |
| `MEGA_ORDER_ACCUM` | 极大单吸筹 | 0 | archived |
| `VOL_SURGE_BUY` | 放量买强（=`BIG_ORDER_STEP`） | 0 | rejected |
| `DIP_CATCH_FALL` | 接刀吸筹 | 0 | rejected |
| `STAB_LOW_TREND` | 低位企稳趋势 | 1 | candidate（主线） |
| `QUIET_LOW_TREND` | 安静低位趋势（废弃） | 1 | deprecated |

易混：`QUIET_DIP_ACCUM`（gen0 六族）≠ `QUIET_LOW_TREND`（gen1 已废弃）。
日常说「缩量阴线吸筹」→ `QUIET_DIP_ACCUM`；说现在在验的信号 → `STAB_LOW_TREND`。

gen0 六族索引与定义卡：[`docs/l2_signals/2026-11-04-gen0-signal-family-index.md`](../docs/l2_signals/2026-11-04-gen0-signal-family-index.md)

## 模块文件

| 文件 | 用途 |
|---|---|
| `signal_catalog.py` | 信号代号 / 中文名 / 状态 / 定义卡路径（SSOT） |
| `reproduce_gen0_signals.py` | gen0 六族统一复现 + 黄金对拍（`--signal` / `--year`） |
| `reproduce_quiet_dip_accum.py` | QUIET_DIP_ACCUM 专用复现 |
| `reproduce_quiet_dip_tech.py` | QUIET_DIP_TECH 专用复现 |
| `alpha158_spec.json` | 官方 158 因子表达式（从 `qlib.contrib.data.loader.Alpha158DL` 导出，作为对齐基准） |
| `alpha158_build.py` | core rollup OHLCV → 158 因子 parquet（pandas 复刻 qlib 语义） |
| `search_alpha158.py` | C1 池（大单量≥2×前日）+ 大单特征 + 168 维贪心搜索（H1/H2 切分） |
| `baseline_signal_search.py` | grok-bot-ops 初代搜索脚本存档（六信号族条件定义的原始出处） |
| `archive_single_trade_1m/` | 归档：单笔≥100万放量×主动买验证（ops 删前脚本；反指结论） |
| `export_signal.py` | 命名信号导出（`--signal STAB_LOW_TREND`） |
| `validate_cross_year.py` | 冻结阈值跨年打分 |

## 环境

```
D:/anaconda3/envs/vanna312/python.exe   # qlib 0.9.8 editable + pandas/pyarrow/duckdb
```

## qlib 语义复刻要点（alpha158_build.py 实测对拍）

- 所有滚动算子 `min_periods=1`（窗口不满也给部分窗口值）
- `Std` = pandas ddof=1；`Rank` = rolling rank(pct=True)（平均秩/有效数）
- `Quantile` = pandas 线性插值；`IdxMax/IdxMin` = 窗口内 argmax+1（1 基）
- `Slope/Rsquare/Resi` = 窗口 OLS（对拍 qlib._libs.rolling 逐位一致）；`Rsquare`/`Corr`
  在窗口 std≈0（atol 2e-05）时置 NaN
- 除零保护统一 `+1e-12`，与官方表达式一致

## 历史结论（搜索起点，勿推翻）

1. 安静吸筹（大单买占成交<10% + 回调）方向是最强正指（76.2%）
2. 极端大单占比（>5% 流通）正指；中等占比（0.5-2%）反指
3. 所有信号都是 1-2 日动量，持有 >3 天失效
4. 搜索一律在 C1 池（大单量≥2×前日）上进行

## 验收标准（沿用 grok-bot-ops 交接）

| 指标 | 要求 |
|---|---|
| T+1 胜率 | >55% |
| 年信号数 | 50-500 次 |
| H2 验证 | >50% |
| 2025 跨年 | 2025 A 层跑完后验证 |
