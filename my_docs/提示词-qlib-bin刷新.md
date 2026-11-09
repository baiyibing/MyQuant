# Qlib 日线 bin 刷新（infra 入口）

数据产制已迁到 MyQuant-infra，本仓不保留刷新、merge、dump 或指数 patch 实现。
安装方式见 [README](../README.md#环境搭建)；运行前用同一个 Python 检查
`python -m myquant_infra.adapters.qlib_data refresh-daily --help`。

同一解释器的帮助必须包含 `--source-parquet-root`；缺少该参数说明当前安装的源码尚未对齐，先按 README 核对导入路径。源码探针和离线测试通过后，仍需补齐下列宿主输入、输出配置，才能生成本批真实刷新计划。

## 显式配置

在 MyQuant 根目录执行，以下变量由操作人配置，禁止猜盘符或换输入文件：

- `OSKH_QLIB_CSV_DIR`：本批厂商 CSV 目录。
- `OSKH_SOURCE_PARQUET_ROOT`：湖容器；指数分区为 `index/period=1d/dividend_type=none`。
- `MQ_QLIB_ARCHIVE_DIR`：完整日线 archive provider（包含 calendars、instruments、features）。
- `MQ_QLIB_DAILY_DIR`：当前 `my_data` provider。
- `MQ_QLIB_NEW_DIR`：待验收的新 provider，必须与当前 provider 分离。
- `MQ_QLIB_DAILY_STAGING`：独立 staging 目录。

```powershell
python -m myquant_infra.adapters.qlib_data refresh-daily --archive-dir "$env:MQ_QLIB_ARCHIVE_DIR" --csv-dir "$env:OSKH_QLIB_CSV_DIR" --lake-index-root "$env:OSKH_SOURCE_PARQUET_ROOT/index/period=1d/dividend_type=none" --source-parquet-root "$env:OSKH_SOURCE_PARQUET_ROOT" --qlib-dir "$env:MQ_QLIB_DAILY_DIR" --new-qlib-dir "$env:MQ_QLIB_NEW_DIR" --staging-dir "$env:MQ_QLIB_DAILY_STAGING" --csv-validator myquant_infra.data_validation.csv_float:scan_csv_dir --dry-run
```

确认计划中的数据批次、日期和目标后，用相同参数去掉 `--dry-run` 执行。
infra 不读取上述环境变量；shell 将它们展开为显式参数。变量缺失时先配置，不补默认路径。

## 执行与验收

1. CSV 浮点 preflight → archive/CSV 合并 → `dump_all`（workers 固定 8）→ 指数 patch。
2. 日历与湖、抽样 close、指数不混入股票宇宙、宇宙变化门禁全部通过后才交换 provider。
3. 旧 provider 重命名为同级 `my_data_backup_YYYYMMDD_pre_refresh`，同日多次不覆盖旧备份。交换失败由 infra 尝试回滚；检查异常后再操作。
4. 需要 Qlib 指数读回时显式加 `--verify-patch`。压缩、异地复制等选项以 infra `--help` 为准，只在明确配置目标后启用。

日线不调用 `dump_update`，不从其他 provider 复制 bin。新 provider 非空时默认拒绝；不要为绕过失败随意加 wipe/force。
刷新期间停止同一 provider 的其他写入，不自动训练或改模型。仅在本批及门禁通过后记录数据范围、宇宙数、备份和最终 provider 路径。

分钟数据见[分钟刷新](提示词-qlib-1min-bin刷新.md)，其目录和日线隔离。
实现及产制测试统一位于 infra 的 `myquant_infra/adapters/qlib_data/` 和 `tests/adapters/qlib_data/`。
