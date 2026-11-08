# Qlib 1min bin 刷新（infra 入口）

分钟 staging、首次构建和增量实现已迁到 MyQuant-infra，本仓训练脚本继续消费分钟 provider。
安装方式见 [README](../README.md#环境搭建)。先检查
`python -m myquant_infra.adapters.qlib_data refresh-1min --help`。

## 显式配置与运行

- `OSKH_SOURCE_PARQUET_ROOT`：湖容器，股票与指数分别使用 `stock/period=1m/dividend_type=none`、`index/period=1m/dividend_type=none`。
- `MQ_QLIB_MINUTE_DIR`：分钟 `my_data_1min` provider。
- `MQ_QLIB_DAILY_DIR`：受保护的日线 `my_data` provider。
- `MQ_QLIB_MINUTE_STAGING`：独立分钟 staging。
- `MQ_QLIB_MINUTE_RECEIPT`：provider 目录之外的 JSON receipt 路径。

在 MyQuant 根目录运行，以上变量必须提前配置，不猜路径：

```powershell
python -m myquant_infra.adapters.qlib_data refresh-1min --lake-root "$env:OSKH_SOURCE_PARQUET_ROOT/stock/period=1m/dividend_type=none" --index-lake "$env:OSKH_SOURCE_PARQUET_ROOT/index/period=1m/dividend_type=none" --qlib-dir "$env:MQ_QLIB_MINUTE_DIR" --daily-dir "$env:MQ_QLIB_DAILY_DIR" --staging-dir "$env:MQ_QLIB_MINUTE_STAGING" --receipt "$env:MQ_QLIB_MINUTE_RECEIPT"
```

该命令没有 dry-run，明确配置后才执行。首次冒烟使用同包 `build-1min`，传相同 lake、staging、qlib、daily 参数，并用 `--symbols SZ000001 SH600000` 指定范围；完整重建选项见 infra CLI help。

## 约束与验收

已有 provider 走增量；不要对短窗口直接 `dump_all`，不要用 `dump_update`。
日线与分钟目标必须分离，保持日线文件指纹不变。workers 上限 8。
增量保留旧偏移和已有数据，缺分钟补 NaN，新票取完整 staging 历史；单个 feature 原子替换并在最后发布日历。
这不是整个 provider 的事务；中途 IO 失败先从备份恢复或完整重建，不直接重复写入。

核对起止分钟、日历、股票数、probe 和日线指纹，保存 receipt。receipt 是本次观测，不代表全市场实时性认证。
训练仍用 `my_scripts/train_1min_smoke.py`，标签、模型与筛选留 MyQuant，默认不运行训练或回测。

实现与产制测试位于 infra 的 `myquant_infra/adapters/qlib_data/` 和 `tests/adapters/qlib_data/`。
