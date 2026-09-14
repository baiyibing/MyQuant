# 提示词：qlib bin 全量刷新（my_data）

> 发给实施 agent（Cursor / Codex）或未来的自己。SSOT：本文件 + `qlib_scripts/refresh_mydata.py`。
> 固化自 2026-09-13 首次编排器落地，以及 **2026-09-14** 把 `F:\qlibdata20260914` 合并进
> `~/.qlib/qlib_data/my_data`（日历到 2026-09-14、补 `$winratio`、指数同步）的实踩。
> 指数-only 补丁仍见 `my_docs/提示词-指数数据修补.md`。

## 任务边界

把一批新 CSV（及可选旧档前缀）灌进 qlib bin，使线上 `my_data` 的**个股 + 指数**日历对齐到 CSV/湖末日，CSV 多出的列（如 `winratio`）进 `$field` bin。

**只走编排器**，不要手工串 `merge_archive_and_csv` / `dump_bin dump_all` / `patch_index_data`。`~/.qlib` 只准经 `refresh_mydata.py` 改。

**明确不做**（除非用户点名）：

- 禁止 `dump_update`、禁止 `max_workers=16`
- 不把 `$winratio` 接到买点过滤 / Alpha158；买点仍走 CYQ parquet（`--winner-ratio-file`）
- 不从 `cn_data` 拷 bin；湖股票日线只有 7 列，不能单独当训练源
- 不改源 CSV；Windows NaN 由 coerce 收成真正的 NaN

## 执行方式

解释器钉死 **`D:\anaconda3\envs\vanna312\python.exe`**（不要 vanna310 / 系统 Python）。

```bash
cd E:\PycharmProjects\MyQuant
# 1. 先看计划
D:/anaconda3/envs/vanna312/python.exe qlib_scripts/refresh_mydata.py --dry-run \
  --csv-dir F:/qlibdataYYYYMMDD/qlibdata \
  --archive-dir C:/Users/Thinkpad/.qlib/qlib_data/my_data \
  --staging-dir F:/qlib_staging_YYYYMMDD \
  --python D:/anaconda3/envs/vanna312/python.exe

# 2. 实跑（C 盘空间紧时 staging 必须在 F:）
D:/anaconda3/envs/vanna312/python.exe -u qlib_scripts/refresh_mydata.py \
  --csv-dir F:/qlibdataYYYYMMDD/qlibdata \
  --archive-dir C:/Users/Thinkpad/.qlib/qlib_data/my_data \
  --staging-dir F:/qlib_staging_YYYYMMDD \
  --python D:/anaconda3/envs/vanna312/python.exe
```

常用开关：

| 开关 | 何时用 |
|---|---|
| `--skip-merge` | staging 已完整，只重 dump / 过门禁 |
| `--skip-dump` | dump 已 100% 完成，只补指数 + 门禁 + swap |
| `--wipe-new-qlib-dir` | `my_data_new_*` 是半成品，必须先删再 dump_all |
| `--allow-beyond-lake` | **先复测湖末日**；仅当 CSV 尾巴确实比湖新时才开。湖范围内缺日仍失败 |
| `--force` | 退市数超 `expected_delist_max` 时才过门禁 4 |
| `--skip-swap` | 门禁过了但先不换线上目录 |
| `--skip-csv-scan` | 已确认 CSV 非法浮点只有 winratio/vwap，想省扫描时间 |

失败后续跑：**看日志定位到哪一步**，用 skip 续跑，禁止对半成品目录盲目 `dump_all`。

## 日历更新（昨晚 / 今天上午踩过，三件不是一件）

qlib 里「日历」其实有三份，只改其中一份就会看起来像「日历没更新」：

| 文件 | 谁写 | 这次有没有跟上 |
|---|---|---|
| `calendars/day.txt` | **只有 `dump_all`** 从 staging 日期并集重建 | 已解决：线上 **2020-01-02 ~ 2026-09-14（1625 天）** |
| `calendars/day_future.txt` | 编排器 `refresh_day_future_calendar`（dump **不会**写它） | 已解决：swap 前必重建；停在旧末日则回测 `end_time==数据末日` 越界（**2026-09-13 晚**实踩） |
| `instruments/index.txt` 起止日 | patch 的 `upsert_index_txt_dates` | 已解决：曾停在 09-08，bin 已到 09-14（**今天**实踩） |

另外两件容易混进来：

- **禁止 `dump_update` 去「更新日历」**：它按个股自己的日期 append，新区间停牌一天就整体错位一天（无声）。要加交易日必须 `dump_all` 进新目录。
- **门禁 1 vs 湖**：今天上午湖一度停在 09-11、CSV 到 09-14。先复测湖；真落后才 `--allow-beyond-lake`。晚上湖已到 09-14。

手工只跑 `dump_bin dump_all`、不走编排器 → `day.txt` 新了、`day_future.txt` 仍旧，这就是「日历更新了回测却炸」。

## 2026-09-14 经验教训（再犯即返工）

1. **半成品 dump 必须删干净再重灌。** `dump_all` 不是断点续传。第一次因 `winratio=-1.#J` 炸在 `astype("<f")` 后，目录里日历/部分 bin 会骗人。编排器现在拒绝往非空 `new_qlib_dir` 上 dump，除非 `--wipe-new-qlib-dir`。
2. **MSVC/Windows NaN 会进 CSV。** `-1.#J`（winratio，可整列缺失）和 `-1.#IND`（0 成交日 vwap）。OHLC 出现 = 导出事故，中止。merge 与 `dump_bin._data_to_bin` 均 `pd.to_numeric(..., errors="coerce")`。不要改 5561 个源文件。
3. **CSV 多出的列要进 staging。** `extra_csv_fields` 保留 `winratio` 这类旧档没有的列；旧档日期填 NaN。
4. **指数 bins ≠ index.txt 登记。** dump_all 可能把归档里的 SH000001/SH000300 按旧末日写进 all.txt；`DumpDataFix` **不更新已有标的区间**。必须 `move_indices_out_of_all_txt` + `upsert_index_txt_dates` 写成日历首末日。验收看 index.txt **和** bin 末收。
5. **门禁 2 不能抽 all.txt 前几只。** 按代码排序常是北交所 BJ920000，2020-01-02 无 bin。抽样必须覆盖日历首末日（`pick_sample_symbols` 已按 all.txt 起止日过滤）。
6. **先核湖再 `--allow-beyond-lake`。** 09-14 白天湖一度停在 09-11，晚上已到 09-14。旗标只管「日历比湖新」；湖范围内缺日仍失败。
7. **C 盘空间。** 线上 `my_data` 约 0.5GB features + 数 GB `features_cache`（随旧目录备份走）。staging 默认别放 C:，用 `F:\qlib_staging_YYYYMMDD`。
8. **archive-dir 可以是当前线上 my_data。** CSV 已从 2020-01-02 起时，前缀为空、整段走 CSV；退市股仍靠旧档/线上仅存部分保留。不要误用过期 `my_data_20260410_archived` 当唯一前缀还以为日历会停在 04-10。
9. **dump 是否完成看日志 `end of features dump`，不要看进程还在。** 进程被打断后日历可能已经是新的。
10. **swap 后冒烟。** 日历末日、index.txt 两端、`D.features` 读 `$close`/`$winratio`、指数末收对湖。买点过滤不因此改源。
11. **Windows 预检/权限。** 动 `~/.qlib` 的 shell 需要非沙箱；PowerShell 无 bash HEREDOC。

## 验收清单（全部满足才算完成）

- [ ] 四门禁过：日历 vs 湖 0 缺日；抽样首末日 close 对 CSV；`all.txt` 无 SH000/SZ399；宇宙 diff 打印且退市未超预期（或已 `--force`）
- [ ] `index.txt` 起止日 = 日历首末日；SH000001/SH000300 bin 行数 = 日历天数、nan_close=0、末收对湖
- [ ] `market="all"` 宇宙无指数泄漏
- [ ] CSV 多出的列（如 `$winratio`）有 bin；抽一只合法值在 [0,1]；源里整列 `-1.#J` 的票该列为 NaN
- [ ] `calendars/day_future.txt` 在数据末日后再顺延约 5 个工作日
- [ ] 线上目录已 swap（除非 `--skip-swap`）；备份 `my_data_backup_YYYYMMDD_pre_refresh` 在
- [ ] 单测：`python -m pytest my_tests/test_refresh_mydata.py my_tests/test_patch_index_data.py my_tests/test_merge_archive_and_csv.py my_tests/test_csv_float_scan.py`

## 排障续跑

| 症状 | 动作 |
|---|---|
| `could not convert string to float: '-1.#J'` | 确认 dump_bin 已 coerce；`--wipe-new-qlib-dir --skip-merge` 重 dump |
| 门禁 2 BJ920xxx 无 bin 值 | 抽样过滤已修；不要用 `--sample-symbol BJ...` |
| 门禁 1 日历比湖新 | 复测湖 `000001_SH` parquet 末日；真落后才 `--allow-beyond-lake` |
| index.txt 停在旧日、bin 已到新日 | 重跑 patch（编排器 `--skip-merge --skip-dump`），依赖 `upsert_index_txt_dates` |
| dump 目标已存在且非空 | `--wipe-new-qlib-dir` 或换 `--new-qlib-dir` |
| C 盘不足 | `--staging-dir F:\...`；必要时把 new 目录也放到空间更大的盘（swap 仍回 `~/.qlib`） |

## 相关文件

- 编排器 `qlib_scripts/refresh_mydata.py`（单测 `my_tests/test_refresh_mydata.py`）
- 扫描 `qlib_scripts/csv_float_scan.py`
- 拼接 `qlib_scripts/merge_archive_and_csv.py`
- 写入 `qlib_scripts/dump_bin.py`（禁止 dump_update；max_workers=8）
- 指数 `qlib_scripts/patch_index_data.py`
- 数据快照 `docs/qlib-data-state-2026-09-14.md`
- 技能 `.cursor/skills/qlib-bin-refresh/SKILL.md`
