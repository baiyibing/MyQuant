# 提示词：qlib bin 全量刷新（my_data）

> 发给实施 agent（Cursor / Codex）或未来的自己。SSOT：本文件 + `qlib_scripts/refresh_mydata.py`。
> 固化自 2026-09-13 首次编排器落地，**2026-09-14** 把 `F:\qlibdata20260914` 灌进
> `~/.qlib/qlib_data/my_data`（日历到 2026-09-14、补 `$winratio`、指数同步），
> **2026-09-15 上午** 用哈希目录批纠错/修赢筹浮点（日历末日不变，仍走 `dump_all`），
> 以及 **2026-09-15 下午** 用 `F:\qlibdata20260915\qlibdata` 短尾巴前推到 09-15
> （CSV 无 `winratio`，overlay 忽略该列）。
> 指数-only 补丁仍见 `my_docs/提示词-指数数据修补.md`。
> **1min bin 是另一套目录**（`my_data_1min`），不要用本文件去刷分钟线；见 `my_docs/提示词-qlib-1min-bin刷新.md`。

## 任务边界

把一批新 CSV（及可选旧档前缀）灌进 qlib bin。常见三种意图，**都走编排器 + `dump_all`**：

1. **全量日历前推**：CSV 自 2020 起、列齐全；个股 + 指数对齐到新末日。
2. **质量修复**（2026-09-15 上午）：日历末日可以不变，只修源错误 / 赢筹浮点。**禁止**因为「末日没变」就改走 `dump_update` 或跳过 dump。
3. **短尾巴增量**（2026-09-15 下午）：CSV 只有最近几天。「更新就行」= overlay 盖有值的列 + 仍 `dump_all`，**不是** `dump_update`。缺列或整列/单元格为空（这批无 `winratio`）**忽略**，保留旧档；不要删 `$winratio` bin。

CSV 多出的列（如 `winratio`）进 `$field` bin。旧档已有同名列时 merge 日志会是 `extra_csv(0)`，属预期。短尾巴缺该列时也是 `extra_csv(0)`，靠 overlay 保住旧值。

**只走编排器**，不要手工串 `merge_archive_and_csv` / `dump_bin dump_all` / `patch_index_data`。日频 `~/.qlib/qlib_data/my_data` 只准经 `refresh_mydata.py` 改。分钟线走 `refresh_mydata_1min.py`，禁止写进 `my_data`。

**明确不做**（除非用户点名）：

- 禁止 `dump_update`、禁止 `max_workers=16`
- 不把 `$winratio` 接到买点过滤 / Alpha158；买点仍走 CYQ parquet（`--winner-ratio-file`）
- 不从 `cn_data` 拷 bin；湖股票日线只有 7 列，不能单独当训练源
- 不改源 CSV；Windows NaN 由 coerce 收成真正的 NaN

## 执行方式

解释器钉死 **`D:\anaconda3\envs\vanna312\python.exe`**（不要 vanna310 / 系统 Python）。

`--csv-dir` **以用户给的路径为准**。可以是 `F:/qlibdataYYYYMMDD/qlibdata`，也可以是下载器哈希目录
`F:/<hash>_<id>/qlibdata`（2026-09-15 实踩）。不要先改名再灌。

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

常用入口：盘中刷新时 CSV/湖通常仍停在**上一交易日**（2026-09-15 上午即如此）。先核湖末日，不要空等当天 bar。

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

## 日历更新（三件不是一件）

qlib 里「日历」其实有三份，只改其中一份就会看起来像「日历没更新」：

| 文件 | 谁写 | 2026-09-15 线上 |
|---|---|---|
| `calendars/day.txt` | **只有 `dump_all`** 从 staging 日期并集重建 | **2020-01-02 ~ 2026-09-15（1626 天）**（下午短尾巴前推后） |
| `calendars/day_future.txt` | 编排器 `refresh_day_future_calendar`（dump **不会**写它） | swap 前必重建；现至 **2026-09-22**（+5 工作日） |
| `instruments/index.txt` 起止日 | patch 的 `upsert_index_txt_dates` | 必须写成日历首末日，不是改 day.txt 就会自动变 |

另外两件容易混进来：

- **禁止 `dump_update` 去「更新日历」或「只修字段」**：它按个股自己的日期 append，新区间停牌一天就整体错位一天（无声）。要加交易日 **或** 重写已有字段，都必须 `dump_all` 进新目录。
- **门禁 1 vs 湖**：先复测湖；真落后才 `--allow-beyond-lake`。旗标只管「日历比湖新」；湖范围内缺日仍失败。盘中湖末日 = 上一交易日属正常。

手工只跑 `dump_bin dump_all`、不走编排器 → `day.txt` 新了、`day_future.txt` 仍旧，这就是「日历更新了回测却炸」。

## 2026-09-15 下午经验教训（短尾巴 / 空 winratio）

1. **先看 CSV 跨度再 merge。** `F:\qlibdata20260915\qlibdata` 5561 文件但每只大约 **2026-09-02 ~ 09-15（10 个交易日）**，表头无 `winratio`。编排器 dry-run / 预检现在打 `[csv-profile] short_tail=... missing_vs_archive=...`。不要把「文件数 ≈ 全市场」当成全历史。
2. **「更新就行」仍是 overlay + `dump_all`。** 短尾巴不是 `dump_update`，也不是按 CSV 首日截断旧档再 concat。截断会把重叠 10 天的 `$winratio` 整段打成 NaN（下午第一跑即如此）。
3. **空/缺 `winratio` 就忽略，不要删字段。** 用户口径：这列空或没有都可以忽略。`overlay_csv_on_archive` 只写 CSV **有值**的单元格；缺列、整列空、单元格空都保留旧档。新末日没有旧值才是 NaN。买点过滤仍走 CYQ，不要因此改读 `$winratio`。
4. **打洞之后不要拿线上 `my_data` 当 archive。** 第一跑已经把赢筹盖空时，重匹配 archive 用上午质量备份 `my_data_backup_YYYYMMDD_pre_refresh`，不要用已打洞的线上目录，也不要 `--skip-merge` 复用坏 staging。
5. **同日第二次 swap 备份会撞名。** `backup_name` 自动变成 `..._pre_refresh_2`。同日重跑 dump 目标也要 `--wipe-new-qlib-dir`，staging 换目录或确认 overlay 正确后再用。
6. **冒烟看 `last_valid`，不要只看末日。** 短尾巴缺赢筹时末日 `$winratio` 为 NaN 是预期（09-15 空、09-14=0.56）。合法值仍须在 [0,1]。
7. **ST 刷新不是 bin 步骤。** 用户说本地 ST 也刷新了，编排器仍不读 `st_daily.parquet`。核湖指数末日即可；当时 ST parquet 仍止于 09-14 也不挡 swap。

## 2026-09-15 上午经验教训（质量修复 / 赢筹浮点）

1. **日历末日不变仍要全量 `dump_all`。** 用户说明「修数据错误、赢筹浮点」时，不要因为 CSV/湖/线上都停在同一天就改 `dump_update` 或 `--skip-dump`。字段值必须重写 bin。
2. **`--csv-dir` 可以是哈希下载目录。** 本次源是 `F:\0d3fdd3bdb348a5179176bf4d7e34597_8160708623260420\qlibdata`（5561 文件），不是 `F:\qlibdata20260915`。路径以用户为准。
3. **扫描先看 `by_column`，再看文件列表。** 09-14 批有 winratio `-1.#J`；09-15 批 `fatal=0`、**winratio 已干净**，只剩 12 只票末日 `vwap=-1.#IND`（0 成交，coerce→NaN）。编排器现在打印 `[csv-scan] by_column: ...`。
4. **`extra_csv(0)` 是重灌同 schema 的正常结果。** 线上 archive 已有 `winratio` 时不会再进 `extra_csv_fields`。merge 仍会是大量 `csv_only` + 少量 `archive_only` 退市股。
5. **盘中刷新日历通常不前推。** 09-15 周二上午，CSV/湖末日仍是 09-14。先核湖，不要为「今天为什么没有」空转或误开 `--allow-beyond-lake`。
6. **冒烟读 bin 用 `read_bin_field`，不要裸 `np.fromfile`。** qlib day.bin 首元素是日历起始下标（1626 vs 1625 就是这个）。编排器 swap 后会抽一只 `$winratio` 打 `[0,1]` 区间。
7. **PowerShell 会吃掉 `$close` / `$winratio`。** 双引号 `-c "..."` 里的 `$field` 被当成变量，`D.features` 变非法语法。用单引号 here-string `@' ... '@`，或直接调 `refresh_mydata.read_bin_field`。不要为了躲 `$` 去改买点过滤。

## 2026-09-14 经验教训（再犯即返工）

1. **半成品 dump 必须删干净再重灌。** `dump_all` 不是断点续传。第一次因 `winratio=-1.#J` 炸在 `astype("<f")` 后，目录里日历/部分 bin 会骗人。编排器现在拒绝往非空 `new_qlib_dir` 上 dump，除非 `--wipe-new-qlib-dir`。
2. **MSVC/Windows NaN 会进 CSV。** `-1.#J`（winratio，可整列缺失）和 `-1.#IND`（0 成交日 vwap）。OHLC 出现 = 导出事故，中止。merge 与 `dump_bin._data_to_bin` 均 `pd.to_numeric(..., errors="coerce")`。不要改 5561 个源文件。
3. **CSV 多出的列要进 staging。** `extra_csv_fields` 保留 `winratio` 这类旧档没有的列；旧档日期填 NaN。重灌已含该列的线上档时见上一节第 4 条。
4. **指数 bins ≠ index.txt 登记。** dump_all 可能把归档里的 SH000001/SH000300 按旧末日写进 all.txt；`DumpDataFix` **不更新已有标的区间**。必须 `move_indices_out_of_all_txt` + `upsert_index_txt_dates` 写成日历首末日。验收看 index.txt **和** bin 末收。
5. **门禁 2 不能抽 all.txt 前几只。** 按代码排序常是北交所 BJ920000，2020-01-02 无 bin。抽样必须覆盖日历首末日（`pick_sample_symbols` 已按 all.txt 起止日过滤）。
6. **先核湖再 `--allow-beyond-lake`。** 09-14 白天湖一度停在 09-11，晚上已到 09-14。旗标只管「日历比湖新」；湖范围内缺日仍失败。
7. **C 盘空间。** 线上 `my_data` 约 0.5GB features + 数 GB `features_cache`（随旧目录备份走）。staging 默认别放 C:，用 `F:\qlib_staging_YYYYMMDD`。
8. **archive-dir 可以是当前线上 my_data。** CSV 已从 2020-01-02 起时，前缀为空、整段走 CSV；退市股仍靠旧档/线上仅存部分保留。不要误用过期 `my_data_20260410_archived` 当唯一前缀还以为日历会停在 04-10。
9. **dump 是否完成看日志 `end of features dump`，不要看进程还在。** 进程被打断后日历可能已经是新的。
10. **swap 后冒烟。** 日历末日、index.txt 两端、`read_bin_field` 读 close/winratio（或 PowerShell 单引号 here-string 调 `D.features`）、指数末收对湖。买点过滤不因此改源。
11. **Windows 预检/权限。** 动 `~/.qlib` 的 shell 需要非沙箱。PowerShell 没有 bash HEREDOC，但有 `@' ... '@` 单引号 here-string；双引号会展开 `$`。

## 验收清单（全部满足才算完成）

- [ ] 四门禁过：日历 vs 湖 0 缺日；抽样首末日 close 对 CSV；`all.txt` 无 SH000/SZ399；宇宙 diff 打印且退市未超预期（或已 `--force`）
- [ ] `index.txt` 起止日 = 日历首末日；SH000001/SH000300 bin 行数 = 日历天数、nan_close=0、末收对湖
- [ ] `market="all"` 宇宙无指数泄漏
- [ ] `$winratio` 有 bin（不要因为本批 CSV 缺/空该列就删掉）；扫描 `by_column` 无 OHLC fatal；抽一只合法值在 [0,1]（编排器 smoke 已打）；**末日 NaN 可接受**，看 `last_valid`；源里若仍有整列 `-1.#J` 则该列为 NaN
- [ ] 短尾巴批：dry-run / 预检已打印 `short_tail` 与 `missing_vs_archive`；重叠日旧档赢筹未被盖空
- [ ] `calendars/day_future.txt` 在数据末日后再顺延约 5 个工作日（末日未变也必须重建）
- [ ] 线上目录已 swap（除非 `--skip-swap`）；备份 `my_data_backup_YYYYMMDD_pre_refresh` 在（同日第二次是 `_2`）
- [ ] 单测：`python -m pytest my_tests/test_refresh_mydata.py my_tests/test_patch_index_data.py my_tests/test_merge_archive_and_csv.py my_tests/test_csv_float_scan.py`

## 排障续跑

| 症状 | 动作 |
|---|---|
| `could not convert string to float: '-1.#J'` | 确认 dump_bin 已 coerce；`--wipe-new-qlib-dir --skip-merge` 重 dump |
| 扫描 winratio 仍有 `-1.#J`、用户说已修复 | 核 `by_column` 是否真是旧批；不要改源 CSV，coerce 后 bin 应为 NaN |
| 门禁 2 BJ920xxx 无 bin 值 | 抽样过滤已修；不要用 `--sample-symbol BJ...` |
| 门禁 1 日历比湖新 | 复测湖 `000001_SH` parquet 末日；真落后才 `--allow-beyond-lake` |
| 盘中刷新、日历没动 | 预期：CSV/湖停在上一交易日。质量修复仍应 dump_all + swap |
| 短尾巴灌完 `$winratio` 重叠日全空 | 按 CSV 首日截断再 concat 了。用质量备份当 `--archive-dir` 重 overlay，禁止 `--skip-merge` 复用坏 staging |
| CSV 无/空 `winratio` | 忽略该列，保留旧档；不要删 `$winratio` bin，不要改买点过滤 |
| 同日第二次 swap 报备份已存在 | `backup_name` 应自动 `_2`；dump 半成品加 `--wipe-new-qlib-dir` |
| 用户说 ST 也刷新了 | 编排器不读 `st_daily.parquet`；只核湖指数。ST 末日落后不挡 bin swap |
| index.txt 停在旧日、bin 已到新日 | 重跑 patch（编排器 `--skip-merge --skip-dump`），依赖 `upsert_index_txt_dates` |
| dump 目标已存在且非空 | `--wipe-new-qlib-dir` 或换 `--new-qlib-dir` |
| C 盘不足 | `--staging-dir F:\...`；必要时把 new 目录也放到空间更大的盘（swap 仍回 `~/.qlib`） |
| `D.features` `invalid syntax` / `field []` | PowerShell 吞了 `$close`；改用 `read_bin_field` 或 `@' ... '@` |
| 裸 `fromfile` 长度 = 日历天数 + 1 | 首元素是 start index，用 `read_bin_field` |
| 用户要更新「qlib 分钟 bin」 | 本文件不管。去 `提示词-qlib-1min-bin刷新.md`，写 `my_data_1min` |
| 1min `dump_all` `BrokenProcessPool` | 旧 `_get_all_date` 每只回传 10 万 Timestamp。已修高频路径；已有 bin 走增量，不要 `dump_update` |

## 相关文件

- 编排器 `qlib_scripts/refresh_mydata.py`（单测 `my_tests/test_refresh_mydata.py`）
- 扫描 `qlib_scripts/csv_float_scan.py`（`by_column` 汇总）
- 拼接 `qlib_scripts/merge_archive_and_csv.py`（`overlay_csv_on_archive` / `[csv-profile]`）
- 写入 `qlib_scripts/dump_bin.py`（日频禁止 dump_update；max_workers=8。`--freq=1min` 日历只从锚点并集，见 1min 提示词）
- 指数 `qlib_scripts/patch_index_data.py`
- 当前快照 `docs/qlib-data-state-2026-09-15.md`（上一份 `docs/qlib-data-state-2026-09-14.md`）
- 分钟线 `my_docs/提示词-qlib-1min-bin刷新.md` + `qlib_scripts/refresh_mydata_1min.py`
