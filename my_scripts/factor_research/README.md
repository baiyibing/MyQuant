# 因子研究入口

实现统一在 `myquant_factors.research`，本目录只设置当前 MyQuant 研究根并调用入口。
例如在本仓根目录使用选定的研究解释器：

```text
<python> my_scripts/factor_research/weekly_macd_divergence.py --help
<python> my_scripts/factor_research/data/full_market_canonical_resist.py --help
<python> my_scripts/factor_research/tr/backfill_turnover_resistance_yearly.py --help
```

数据根必须显式配置。TR backfill 目前为迁入的研究工具；不代表已经接入
infra 的正式批量生产或获得真实行情写入授权。完整旧路径映射见
`examples/chip_research/entrypoint-migration.json`。
