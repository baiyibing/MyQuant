# qlib 数据状态（2026-09-14 刷新后）

> **已被 2026-09-15 刷新覆盖。** 当前线上见 `docs/qlib-data-state-2026-09-15.md`（日历至 2026-09-15）。
> 本快照保留 `$winratio` 首次入库与源侧 `-1.#J` 事故记录。

- 日期：2026-09-14 晚（CSV 批 `F:\qlibdata20260914\qlibdata` → 线上 `my_data`）
- 数据目录：`C:\Users\Thinkpad\.qlib\qlib_data\my_data`
- 刷新前备份：`~/.qlib/qlib_data/my_data_backup_20260914_pre_refresh`
- 入口：`qlib_scripts/refresh_mydata.py`（提示词 `my_docs/提示词-qlib-bin刷新.md`）
- 上一快照：`docs/qlib-data-state-2026-09-13.md`（日历当时止于 2026-09-08，无 winratio）

## 规模

| 项 | 值 |
|---|---|
| 日历 | **2020-01-02 ~ 2026-09-14，1625 个交易日** |
| 股票 | 5587（`instruments/all.txt`）；相对 09-13 快照 +4（BJ920268、SH688801、SZ301689、SZ301699） |
| 指数 | `index.txt`：SH000001、SH000300，登记 **2020-01-02 ~ 2026-09-14** |
| 指数末收（对湖） | 上证 **3885.33** / 沪深300 **4480.08** |
| 字段 | 原 16 列 + **`winratio`**（`$winratio`，源口径 [0,1]） |

买点过滤仍走 CYQ parquet，未改读 `$winratio`。源 CSV 中 10 只 winratio 为 `-1.#J`（整列或后半段缺失），入库为 NaN；12 只在 2026-09-14 因 0 成交 `vwap=-1.#IND` → 该日 `$vwap` 为 NaN。

## 本次刷新要点

1. archive = 当时线上 `my_data`（CSV 已从 2020-01-02 起，前缀为空）
2. staging 在 `F:\qlib_staging_20260914`（C 盘空间不够放 parquet）
3. dump 曾因 `-1.#J` 失败；coerce 后 `--wipe`/`--skip-merge` 重灌
4. 门禁 2 曾误抽 BJ920000（首日无行情）；抽样改为覆盖日历两端
5. patch 后 `index.txt` 用日历首末日 upsert，避免 DumpDataFix 不改已有登记
