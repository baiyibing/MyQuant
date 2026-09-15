# qlib 数据最终状态（2026-09-13 全量重建）

> **已过时。** 当前线上状态见 `docs/qlib-data-state-2026-09-15.md`（日历至 2026-09-15，含 `$winratio`）。刷新流程与教训见 `my_docs/提示词-qlib-bin刷新.md`。

- 日期：2026-09-13 凌晨（继 09-12 指数补丁、数据刷新之后的最终版）
- 数据目录：`C:\Users\Thinkpad\.qlib\qlib_data\my_data`
- 归档备份：`~/.qlib/qlib_data/my_data_20260913_full.7z`（7-Zip，含本目录全部内容，212,924,772 字节 / 204 MiB）
- 异地副本：`F:\my_data_20260913_full.7z`、`G:\my_data_20260913_full.7z`——三份 MD5 一致（`42f7ca758dd61fdfc9b85f96e3784a26`）
- 相关工具：`qlib_scripts/refresh_mydata.py`（标准刷新编排器）+ `merge_archive_and_csv.py` / `dump_bin.py` / `patch_index_data.py`（PR #6 三件套）

## 规模与覆盖

| 项 | 值 |
|---|---|
| 日历 | **2020-01-02 ~ 2026-09-08，1621 个交易日** |
| 完整性 | 与 F 湖上证指数（000001_SH）的真实交易日**逐日对齐，0 缺失** |
| 股票数 | 5583（`instruments/all.txt`；含 26 只退市股完整历史） |
| 指数 | `instruments/index.txt` 独立池：SH000300（沪深300）、SH000001（上证）；`market="index"` 可取用，基准查询不受 `all.txt` 影响 |
| 字段 | 16 个/股：`adjclose amount basiccurhold adfadfbasiccurhold bigddx change close factor high low netcsfree open volddx volume vwap zhangting` |

训练窗现状：`custom_train_backtest.py` 用 2026-01-01~03-23（50 个交易日，完整）；数据现已支持把训练/评估窗扩展到 2026-09-08。

## 三个数据源的真相

| 源 | 覆盖 | 字段 | 角色 |
|---|---|---|---|
| F 湖 `stock/period=1d`（dividend_type=none） | 1990-12-19 ~ 2026-09-10 全量 | **仅 7 列**（time/OHLCV/amount） | 历史最全但缺自定义字段，不能单独作训练数据 |
| `F:\qlibdata` CSV 批 | 多数 2022-07-26 ~ 2026-09-08（导出截断，非数据缺失） | 16 列全 | 最新、字段全，但缺 2020~2022-07 |
| 旧 bin 存档 `my_data_20260410_archived` | 2020-01-02 ~ 2026-04-10 | 16 列全 | 唯一同时覆盖 2020 起且字段全的来源 |

重建方案 = **拼接**：旧档作前缀 + CSV 批作尾段。前提校验：重叠段（2022-07-26~2026-04-10）逐位一致（close/adjclose 为 float32 舍入级差异，factor/zhangting/volume 完全相同）——两批是同一管道导出。晚于 2022-07 上市的股票自然走纯 CSV 分支；仅存档有的退市股整段保留。

## 标准刷新流程（= orchestrator）

**唯一入口**：`qlib_scripts/refresh_mydata.py`。不要再手工串三件套；`~/.qlib` 数据只准经该编排器改动。Agent 操作说明：`my_docs/提示词-qlib-bin刷新.md`。

```bash
# 先看计划（本机无 F: 湖 / 无 ~/.qlib 时也安全）
python qlib_scripts/refresh_mydata.py --dry-run

# 全量刷新（merge → dump_all --max_workers 8 → patch_index → 四门禁 → 原子 swap）
python qlib_scripts/refresh_mydata.py

# 可选：打 7z 全量包并拷异地（MD5 三方校验）；异地根目录可配
python qlib_scripts/refresh_mydata.py --archive --offsite \
    --offsite-dir F:/ --offsite-dir G:/
```

编排器内部仍调用现有脚本（**不改它们 CLI**）：

1. `merge_archive_and_csv.py` → staging parquet
2. `dump_bin.py dump_all … --max_workers 8`（**禁止** `dump_update`；**禁止** 16 workers）
3. `patch_index_data.py --no-backup`（指数进 `index.txt`，不得留在 `all.txt`）
4. 完整性门禁：①日历 vs 湖 `000001_SH`（UTC ms→Asia/Shanghai）0 缺日 ②首/末日×3 标的 vs 源 CSV ③`all.txt` 无指数 ④宇宙 diff（退市超预期须 `--force`）
5. 原子 `mv`：先备份 `my_data_backup_YYYYMMDD_pre_refresh`，失败回滚

手工逐步命令仅作排障参考（见下一节历史「重建流程」）；日常刷新以 orchestrator 为准。

## 历史手工重建流程（排障参考，勿作日常入口）

```bash
# 1. 拼接出 staging（每股一个 parquet：date + 16 字段）
python qlib_scripts/merge_archive_and_csv.py --out-dir <staging>

# 2. 全量灌入新目录（不要用 dump_update！不要 16 个 worker！）
python qlib_scripts/dump_bin.py dump_all --data-path <staging> \
    --qlib-dir <新目录> --file-suffix .parquet --max_workers 8

# 3. 切换目录后补指数（自动：湖裁剪 → dump_fix → all.txt→index.txt 挪移 → 读回验证）
python qlib_scripts/patch_index_data.py --no-backup
```

## 陷阱清单（全部实踩，脚本已内置防护或规避）

1. **湖 `time` 是 UTC 毫秒**，须转 Asia/Shanghai 再取日期，否则凌晨段错一天
2. **bin 按日历位置索引**：不能从 `cn_data` 直接拷 bin（日历 2005/5062 天 vs 本数据 1621 天，全错位）
3. **`dump_fix`/归档里的指数会进 `all.txt`**：训练宇宙 `market="all"` 读它——指数混入会污染训练样本、名单导出会把 `SH000300` 剥成 `000300` 当股票。2026-09-13 拼接时归档里的指数曾借「退市股」通道复活，`patch_index_data.py` 第 4 步挪移再次堵住
4. **`dump_update` 禁用**：按个股自身日期 append，新区间内停牌一天即整体错位一天（无声）
5. **Windows 下 `dump_all --max_workers 16` 在进程池回收处死锁**（2026-09-13 实测两次），**用 8**

## 验证记录（2026-09-13）

- 日历 1621 天，对湖上证指数真实交易日缺失 0
- SH600000 双端抽验：2021-06-30 close=91.4607（恢复段）、2026-09-08 close=87.6463（新尾，与源 CSV 逐位一致）、`zhangting` 字段正常流转
- SH000300/SH000001：1621/1621 行、0 NaN、首末收盘与湖一致（4152.24→4636.57 / 3085.20→3940.55）
  - 更正（2026-09-13 17:52 复验）：上行的 4636.57 实为 **2026-04-10 收盘**（旧档前缀末日，当时的验证恰好止于该行）；全日历末收（2026-09-08）应为 **沪深300 4558.74 / 上证 3940.55**。bin 数据本身自重建起即覆盖全日历，无缺日、无 NaN
- `market="all"` 宇宙 5583 只，指数泄漏：无

## 指数补丁复跑记录（2026-09-13 17:48 / 17:52）

- 背景：`instruments/index.txt` 登记范围曾停在 2026-04-10（09-13 重建挪移时旧行优先所致；bin 实际覆盖全日历，benchmark 查询不受影响，但 `market="index"` 池语义失真）
- 动作：重跑 `qlib_scripts/patch_index_data.py`（自动备份 `my_data_backup_20260913_pre_index`；F 湖裁剪 → dump_fix → 挪移 → 读回验证）
- 脚本修复：`move_indices_out_of_all_txt` 合并语义由「旧行优先」改为「本次 dump 新行覆盖旧登记」，否则 index.txt 登记范围永远停在首次写入日期；补单测 `test_move_replaces_stale_index_row`
- 验收：SH000300/SH000001 均 1621/1621、缺日 0、nan_close 0、首末收盘与湖一致（4152.24→4558.74 / 3085.20→3940.55）；`index.txt` 登记范围刷新为 2020-01-02~2026-09-08；`market="all"` 5583 只无指数泄漏；`my_tests/test_patch_index_data.py` 6/6 绿

## day_future 日历重建（2026-09-13 22:10，同步新机修复）

- 背景：qlib 回测交易日历走 `future=True` 读 `calendars/day_future.txt`；本地 `my_data` 此前**无**该文件——回测 `end_time == 数据末日（2026-09-08）` 时 `TradeCalendarManager` 取 `calendar[index+1]` 越界崩溃（新机同日实踩，修复随 PR #33 固化进编排器 `refresh_day_future_calendar`）
- 动作：直接调用 `refresh_mydata.refresh_day_future_calendar`（与新机同一代码路径，幂等）
- 验证：`day_future.txt` 1626 天（2020-01-02 ~ 2026-09-15，数据末日 2026-09-08 后顺延 5 个工作日）；`D.calendar(future=True)` 读回一致。注意为工作日近似（不含 A 股节假日）——该文件仅用于回测取「下一交易日」epsilon，不参与数据加载
- 数据包：`my_data_20260913_longwin.7z` 已重打（含 day_future.txt），新 MD5 以 `docs/runbook-newdev-qlib-longwindow-2026-09-13.md` 为准

## 磁盘目录清单（`~/.qlib/qlib_data/`）

| 目录/文件 | 状态 | 建议 |
|---|---|---|
| `my_data/` | **最终版**（本文件描述） | 使用中 |
| `my_data_20260913_full.7z` | 最终版归档 | 长期保留 |
| `my_data_20260410_archived/` | 旧全字段版（2020-01~04-10，唯一 2020 起且字段全的旧档） | 保留（下次刷新的前缀源） |
| `my_data_csvonly_20260908/` | 2026-09-13 中间版（有 483 天空洞） | **可删** |
| `my_data_backup_20260912_pre_index/` | 09-12 指数补丁前备份 | **可删** |
| `my_data*.7z`（0401 及更早） | 历史归档 | 照旧 |
