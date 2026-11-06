# l2_signals — L2 大单 × Alpha158 联合信号研究

> 建线：2026-11-04 · 从 grok-bot-ops PR #105 的信号探索（6 信号族、安静吸筹洞察）延续而来。

## 四仓分工（L2）

| 仓 | 职责 |
|---|---|
| **MyQuant-infra** | L2 **数据处理**（写侧 + 湖工具 + `l2/research` 读侧探索脚手架；可摸原始湖） |
| **MyQuant**（本模块） | L2 **数据利用**（信号研究、定义卡、跨年验证、池导出；只吃 rollup / B 层等成品表） |
| **MyQuant-backtrader** | **回测执行**（如 stab_t1 书；跨引擎契约） |
| **grok-bot-ops** | **全局配置 / 湖口径与历程 SSOT 文档**（研究脚本已全部迁出） |

判据：要碰湖的原始格式 / 分区 / 增量机制 → infra；只消费成品表出信号代号与定义卡 → MyQuant。  
infra `l2/research` 可做贴湖假说探查，但**不是 signals**；命名信号与定义卡只落本仓。

## 定位与边界

- **读侧研究**：只读消费 `J:/l2_lake`（core rollup + bigorder B 层），不写湖、不扫逐笔 `l2_parquet`。
- 湖写侧、跑批、修湖、贴湖 research CLI → MyQuant-infra；本模块只出信号与研究成果。
- 研究产出（parquet/csv）写 `E:/stock_data/l2_research/`，数据文件不入库。

## 数据依赖

| 数据 | 路径 | 说明 |
|---|---|---|
| core rollup（291 列日线） | `J:/l2_lake/rollup/daily_stock/version=l2-daily-v3/params=a2e3a427af892982d0ce/` | OHLCV + vwap + total_vol（机械盘，只读慢） |
| 大单 B 层 v2（日频，18 列） | `J:/l2_lake/rollup/bigorder_daily_{year}.parquet`（2020–2026） | 10 万档大单 + 小单 `{buy,sale}ordsml_{vol,amt}`（2026-11-06 v2 重算） |
| **E: 研究缓存** | `E:/stock_data/l2_research/cache/` | B 层 v2 七年逐字节副本 + `daily_px_2019_2026.parquet`（OHLC 五列提取 7.54M 行，原始价）+ `daily_px_adj_2019_2026.parquet`（**等比前复权**，dr 因子表 `adj_factor_geometric.parquet` 派生；除权日收益/RSV 严格连续，禁用 QMT front 等差口径算涨跌幅）；研究脚本优先读此层（SSD） |
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
| `MEGA_MA20_BREAK` | 大单破线确认 | 2 | deprecated（涨停不可买） |

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
| `search_ma20_mega.py` | gen2 池（净大单量/流通>2% × MA20 上穿）+ Alpha158 贪心搜索 + 内置跨年冻结诊断；`--exclude-limit-close` 可买性硬过滤（→ [MEGA_MA20_BREAK 已 deprecated](../docs/l2_signals/2026-11-05-ma20-mega-gen2-search.md)） |
| `validate_ma20_mega_break.py` | MEGA_MA20_BREAK 冻结阈值跨年打分（发现年不覆写 export 文件） |
| `low20_smallsell_dry.py` | 低位×小卖枯竭假设检验（30日收盘 20% 分位下 + 小卖额<0.5×30日均值 → T+5..T+10 涨幅统计；读 E: B 层 v2/价格缓存；[研究记录](../docs/l2_signals/2026-11-06-low20-smallsell-dry-hypothesis.md)） |
| `low20_kdj_cross.py` | 低位×KDJ月线金叉假设检验（同 C1 + 周线J>K + 月线J上穿K当日 → T+1/5/10；as-of 运行 bar 无未来函数；v1 完整周期 bar 泄漏已修，结论=不成立；[研究记录](../docs/l2_signals/2026-11-06-low20-kdj-cross-hypothesis.md)） |
| `regime_gate.py` | STAB_LOW_TREND 事前 regime 门控（N≥5 + MA200 斜率/回撤 + 指数日；[研究文档](../docs/l2_signals/2026-11-05-regime-gate-research.md)） |
| `baseline_signal_search.py` | grok-bot-ops 初代搜索脚本存档（六信号族条件定义的原始出处） |
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
