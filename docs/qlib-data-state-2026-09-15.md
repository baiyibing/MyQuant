# qlib 数据状态（2026-09-15 短尾巴前推后）

- 日期：2026-09-15 下午（源 CSV `F:\qlibdata20260915\qlibdata` overlay 上午质量档）
- 意图：短尾巴日历前推到 09-15；CSV **无 `winratio` 列**，忽略该列、保留旧档赢筹
- 数据目录：`C:\Users\Thinkpad\.qlib\qlib_data\my_data`
- 刷新前备份：`~/.qlib/qlib_data/my_data_backup_20260915_pre_refresh_2`（同日第二次 swap）
- 重匹配 archive：上午质量备份 `my_data_backup_20260915_pre_refresh`（第一跑按 CSV 首日截断，重叠 10 天赢筹被盖空，不能再用线上 `my_data`）
- 入口：`qlib_scripts/refresh_mydata.py`（提示词 `my_docs/提示词-qlib-bin刷新.md`）
- 上一快照：`docs/qlib-data-state-2026-09-14.md`（首次入库 `$winratio`）

## 规模

| 项 | 值 |
|---|---|
| 日历 | **2020-01-02 ~ 2026-09-15，1626 个交易日** |
| `day_future.txt` | 至 **2026-09-22**（1631 天，+5 工作日） |
| 股票 | 5587（`instruments/all.txt`）；相对刷新前 ±0 |
| 指数 | `index.txt`：SH000001、SH000300，登记 **2020-01-02 ~ 2026-09-15** |
| 指数末收（对湖） | 上证 **3864.28** / 沪深300 **4450.04** |
| 字段 | 17 列（含 `$winratio`）；merge `extra_csv(0)`，缺列靠 overlay 保留 |
| `$winratio` bins | 仍在；末日 NaN，`last_valid=2026-09-14`（SH600000=0.56） |

买点过滤仍走 CYQ parquet，未改读 `$winratio`。ST `st_daily.parquet` 当时仍止于 09-14，编排器未消费。

## 上午质量修复（已被下午覆盖）

- 源：`F:\0d3fdd3bdb348a5179176bf4d7e34597_8160708623260420\qlibdata`
- 日历当时仍是 2020-01-02 ~ 2026-09-14（1625 天）；`fatal=0`，12 只票末日 `vwap=-1.#IND`；**winratio 已无 `-1.#J`**
- 指数末收当时对湖 3885.33 / 4480.08
- 备份：`my_data_backup_20260915_pre_refresh`

## 下午短尾巴要点

1. CSV 5561 文件、每只约 10 个交易日（2026-09-02 ~ 09-15），表头无 `winratio`
2. 第一跑截断 concat 把 09-02..09-15 赢筹打成空洞；第二跑 overlay + 上午备份 archive
3. staging 用独立目录（勿 `--skip-merge` 复用坏 staging）；dump 同日目标加 `--wipe-new-qlib-dir`
4. 四门禁过；宇宙 5587 ±0
5. 冒烟：`$winratio` 合法值在 [0,1]；09-15 为空可接受
