# qlib 数据状态（2026-09-15 质量修复刷新后）

- 日期：2026-09-15 上午（源 CSV `F:\0d3fdd3bdb348a5179176bf4d7e34597_8160708623260420\qlibdata` → 线上 `my_data`）
- 意图：纠错 + 赢筹浮点修复；**日历末日未前推**（盘中，CSV/湖仍止于 2026-09-14）
- 数据目录：`C:\Users\Thinkpad\.qlib\qlib_data\my_data`
- 刷新前备份：`~/.qlib/qlib_data/my_data_backup_20260915_pre_refresh`
- 入口：`qlib_scripts/refresh_mydata.py`（提示词 `my_docs/提示词-qlib-bin刷新.md`）
- 上一快照：`docs/qlib-data-state-2026-09-14.md`（首次入库 `$winratio`，源里仍有 `-1.#J`）

## 规模

| 项 | 值 |
|---|---|
| 日历 | **2020-01-02 ~ 2026-09-14，1625 个交易日**（与 09-14 快照相同） |
| `day_future.txt` | 至 **2026-09-21**（1630 天，+5 工作日） |
| 股票 | 5587（`instruments/all.txt`）；相对刷新前 ±0 |
| 指数 | `index.txt`：SH000001、SH000300，登记 **2020-01-02 ~ 2026-09-14** |
| 指数末收（对湖） | 上证 **3885.33** / 沪深300 **4480.08** |
| 字段 | 17 列（含 `$winratio`）；merge `extra_csv(0)` |
| `$winratio` bins | 5589 |

买点过滤仍走 CYQ parquet，未改读 `$winratio`。

## 扫描与抽样

- CSV 5561：`fatal=0`，`warn=12` **全部**是 2026-09-14 `vwap=-1.#IND`（0 成交 → `$vwap` NaN）
- **winratio 已无 `-1.#J`**（相对 09-14 批的源侧修复）
- 抽样：SH600000 末日 close=88.6756 / winratio=0.56；SH688981 末日 114.07 / 0.01；合法值在 [0,1]

## 本次刷新要点

1. archive = 当时线上 `my_data`；CSV 自 2020-01-02 起，几乎全 `csv_only`（5559）+ `archive_only` 28 只退市 + merged 2
2. staging `F:\qlib_staging_20260915`；dump `my_data_new_20260915` 后原子 swap
3. 哈希目录当 `--csv-dir`，未改名
4. 四门禁过；宇宙 5587 ±0
5. 冒烟勿在 PowerShell 双引号里写 `$close`；读 bin 用 `read_bin_field`
