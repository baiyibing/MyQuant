# qlib 数据最终状态（2026-09-13 全量重建）

- 日期：2026-09-13 凌晨（继 09-12 指数补丁、数据刷新之后的最终版）
- 数据目录：`C:\Users\Thinkpad\.qlib\qlib_data\my_data`
- 归档备份：`~/.qlib/qlib_data/my_data_20260913_full.7z`（7-Zip，含本目录全部内容，212,924,772 字节 / 204 MiB）
- 异地副本：`F:\my_data_20260913_full.7z`、`G:\my_data_20260913_full.7z`——三份 MD5 一致（`42f7ca758dd61fdfc9b85f96e3784a26`）
- 相关工具：`qlib_scripts/merge_archive_and_csv.py`、`qlib_scripts/patch_index_data.py`、`qlib_scripts/dump_bin.py`（PR #6）

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

## 重建流程（可复现）

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
- `market="all"` 宇宙 5583 只，指数泄漏：无

## 磁盘目录清单（`~/.qlib/qlib_data/`）

| 目录/文件 | 状态 | 建议 |
|---|---|---|
| `my_data/` | **最终版**（本文件描述） | 使用中 |
| `my_data_20260913_full.7z` | 最终版归档 | 长期保留 |
| `my_data_20260410_archived/` | 旧全字段版（2020-01~04-10，唯一 2020 起且字段全的旧档） | 保留（下次刷新的前缀源） |
| `my_data_csvonly_20260908/` | 2026-09-13 中间版（有 483 天空洞） | **可删** |
| `my_data_backup_20260912_pre_index/` | 09-12 指数补丁前备份 | **可删** |
| `my_data*.7z`（0401 及更早） | 历史归档 | 照旧 |
