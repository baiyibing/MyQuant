# 归档：单笔≥100万成交「放量×主动买」验证（反指）

> 源：grok-bot-ops `scripts/ops/l2_agg_daily_metrics.py` + `l2_hypo_report.py`（删于 `022f820`）
> 报告原文：ops `docs/ops/l2-bigorder-signal-verify-20261030.md`
> MyQuant 摘要卡：`docs/l2_signals/2026-10-30-single-trade-1m-verify-archive.md`

**不是**现行 gen0/gen1 信号族。口径是逐笔 `Price×Volume≥100万`，与订单聚合 `≥10万` SSOT 不同。2026 实测无正向优势（信号 45.49% vs 对照 46.07%）。

## 复现

```text
# 1) 从逐笔 main 聚合日×票（约半小时级，USB HDD 建议 concurrency=1）
D:/anaconda3/envs/vanna312/python.exe l2_signals/archive_single_trade_1m/l2_agg_daily_metrics.py `
  --lake J:/l2_lake/l2_parquet `
  --out E:/stock_data/l2_research/single_trade_1m/agg_v2.csv `
  --start 2026-01-01 --end 2026-10-26 --lookback 1 --forward-days 1 --on-dup fail

# 2) 统计报告（应对齐 ops 验证文档数字）
D:/anaconda3/envs/vanna312/python.exe l2_signals/archive_single_trade_1m/l2_hypo_report.py `
  E:/stock_data/l2_research/single_trade_1m/agg_v2.csv `
  --start 2026-01-01 --end 2026-10-26
```

`_lake_helpers.py` 仅含原 `l2_rollup_daily` 里本实验用到的分区/哈希/唯一键辅助，**不写湖**。
