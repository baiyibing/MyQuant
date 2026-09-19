# 提示词：qlib 1min bin 刷新（my_data_1min）

> 发给实施 agent（Cursor / Codex）或未来的自己。SSOT：本文件 + `qlib_scripts/refresh_mydata_1min.py`。
> 固化自 **2026-09-18**：湖分钟线更新到 09-18 后，全市场 `dump_all --freq=1min` 在
> `_get_all_date` 被 Windows 进程池 OOM 杀掉；改为增量追加 + 高频日历只从锚点票并集。
> 日频刷新仍见 `my_docs/提示词-qlib-bin刷新.md`，**两套 provider 不要混**。

## 任务边界

把分钟湖（股票 + 指数）灌进 **`~/.qlib/qlib_data/my_data_1min`**。

| 意图 | 走哪条 |
|---|---|
| 已有 1min bin，湖只多了几天 | **`refresh_mydata_1min.py`**（默认增量 append） |
| 目录不存在 / 要推倒重来 | `refresh_mydata_1min.py --rebuild` 或 `build_mydata_1min.py --all-symbols` |
| 20 只冒烟 | `build_mydata_1min.py`（默认，含 SH000300） |

**只走上面的编排器。** 不要手工 `dump_bin dump_all --freq=1min` 扫全市场（旧实现会 OOM；新实现虽已修日历路径，全量写 bin 仍要 14GB+ 时间和空间）。
**禁止 `dump_update`**：它会把全部 staging 读进一个 DataFrame（注释就写了 Need more memory），1min 比日线更致命。
**禁止写 `~/.qlib/qlib_data/my_data`。** 日线日历 / `$winratio` / keeper pred 与 1min 无关。

**明确不做**（除非用户点名）：

- 不把 1min 灌进日频 `my_data`，不改 `pred.pkl`
- 禁止 `max_workers=16`（高频侧脚本夹到 8）
- 不承诺和 BT 分钟湖 / LEBS / Paper 净值对齐
- 不把指数从 `my_data_1min/instruments/all.txt` 挪走（1min 宇宙目前就是 dump 进去的 `all`；日频指数泄漏规则不套过来）
- 不从 `cn_data` / `cn_data_1min` 拷 bin

## 执行方式

解释器钉死 **`D:\anaconda3\envs\vanna312\python.exe`**。

湖根 = **`OSKH_SOURCE_PARQUET_ROOT`**（与 1.3 同键）。未设则报错，不猜 E:/F:。**不要**把 `OSKH_DATA_ROOT` 当湖，CI 里它是 `D:\oskh_ci_data`。脚本默认：

- 股票：`{OSKH_SOURCE_PARQUET_ROOT}/stock/period=1m/dividend_type=none`
- 指数：`{OSKH_SOURCE_PARQUET_ROOT}/index/period=1m/dividend_type=none`（8 个分区；`899001_BJ` 可能无 parquet，跳过）
- 细粒度覆盖：`OSKH_PERIOD_1M_ROOT` / `OSKH_INDEX_1M_ROOT`（指数**永不**读股票 `OSKH_PERIOD_*`）
- staging：`D:\qlib_data\_staging_1min`（不要放 C:）

```bash
cd D:\PycharmProjects\MyQuant

# 日常：已有 my_data_1min，湖末日新了
D:/anaconda3/envs/vanna312/python.exe -u qlib_scripts/refresh_mydata_1min.py

# 首次 / 推倒重来
D:/anaconda3/envs/vanna312/python.exe -u qlib_scripts/refresh_mydata_1min.py --rebuild
```

先核湖末日（`000001_SZ` / `000300_SH` parquet 最后一根），再跑。盘中湖常停在上一交易日。

## 2026-09-18 经验教训（再犯即返工）

1. **日频 `my_data` 与 1min `my_data_1min` 是两套目录。** 用户说「更新 qlib 分钟 bin」只动后者。跑前记下 `my_data/calendars/day.txt` 的 mtime/hash，跑后必须一样。编排器会查。
2. **不要对全市场 1min 走旧 `_get_all_date`。** 旧代码对每只 `set(全部 Timestamp)` 经 `ProcessPoolExecutor.map` 传回父进程。日线一只 ~1600 天能扛；1min 一只 ~10 万根，队列里堆几百个 set 就是数 GB。Windows spawn 再放大，子进程被杀，父进程只看到 `BrokenProcessPool`（exit `4294967295`），**features 目录仍是 0 个文件**。进度条停在 20% 很久不是写 bin，是还在扫日历。
3. **高频日历只从锚点并集。** `dump_bin` 对 `freq != day` 用 `sz000001` / `sh000300` / `sh000001` / `sz399001`（有哪个用哪个）建 `calendars/1min.txt`；其余票只回传 min/max 写 `all.txt`。A 股 1min 交易时段共用，不要再对 5500 只求并集。
4. **已有 bin 只追加新分钟，不要 `dump_all` 重写 14GB。** `dump_all` 会按 staging 窗口重建日历：若 staging 只切了最近几天，日历会被截短。增量用 `UPDATE_MODE` 往已有 `.1min.bin` 后面 append，日历 = 旧轴 + 新轴。新上市 / 新指数没有旧 bin，才对那几只 full-stage + `ALL_MODE`。
5. **`dump_update` 对 1min 更禁。** 日线禁它是因为停牌错位；1min 还多一条：`_load_all_source_data` 把 5500 只×10 万行读进一个 DataFrame。
6. **指数分钟要单独 stage。** 股票湖路径不含 `index/period=1m`。漏了就没有 SH000300。部分指数湖起点不是 2025-01-02（沪深300 约 2025-05-15，上证综指等约 2025-09-10），bin 起点跟湖走，不要按股票首日去对。
7. **`--end` 不要留过期默认。** 旧 `build_mydata_1min.py` 默认 `20260909`，湖到 09-18 时若照抄会丢掉新尾巴。不传 start/end = 湖里有的都要。
8. **半成品 `my_data_1min_new` 失败就删。** 全量 dump 中途被杀时新目录往往还是空的；线上 `my_data_1min` 仍是旧末日。不要拿空目录 swap。
9. **`max_workers` 高频夹 8。** 16 在日线 dump 回收死锁；1min 日历 pickle 更先爆。脚本夹到 8，不要手改 16。
10. **staging 在 D:，线上 bin 在 C:。** 全量 stage 约十余 GB；增量 stage 只有新几天，很小。跑完可删 staging。
11. **验收看日历末日 + 锚点 bin 长度，不要只看进程还在。** 进程被杀后日历可能完全没写。`read_bin_field` / `np.fromfile`：1min.bin 首元素同样是日历起始下标。

## 验收清单（全部满足才算完成）

- [ ] `my_data_1min/calendars/1min.txt` 末日 = 湖锚点最后一根（例：`2026-09-18 15:00:00`）
- [ ] `SZ000001` 的 `close.1min.bin` 行数（去掉 4 字节下标）= 日历行数
- [ ] 指数在 `instruments/all.txt` 且有 bin：至少 `SH000300`（有湖的 SH000001 / SZ399001 / SZ399006 也应在）
- [ ] `~/.qlib/qlib_data/my_data/calendars/day.txt` 未变
- [ ] 未调用 `dump_update`；`max_workers` ≤ 8
- [ ] 单测：`python -m pytest my_tests/test_dump_bin_highfreq.py my_tests/test_refresh_mydata_1min.py tests/test_stage_1min_from_lake.py`

## 排障续跑

| 症状 | 动作 |
|---|---|
| `BrokenProcessPool` / 进程 exit `4294967295`，features=0 | 旧日历扫描 OOM。确认 `dump_bin` 已走 highfreq refs；已有 bin 改增量，不要重扫全市场 set |
| 日历被截成最近几天 | 对短 staging 做了 `dump_all`。用日历备份或重走增量；`--rebuild` 必须 stage **全历史** |
| 指数不在 all.txt | 漏了 `--index-lake`。`refresh_mydata_1min.py` 默认带指数；不要 `--skip-index` |
| `BJ899001` 没有 bin | 湖分区空，跳过 |
| 日线 `day.txt` 变了 | 写到 `my_data` 了。停，从备份还原日线，1min 只用 `my_data_1min` |
| C 盘不足 | staging 必须在 D:；增量不要 `my_data_1min_new` 双份 14GB |
| PowerShell `$close` 被吞 | 同日频：`@' ... '@` 或只看 `1min.txt` 文本 |

## 相关文件

- 编排器 `qlib_scripts/refresh_mydata_1min.py`（单测 `my_tests/test_refresh_mydata_1min.py`）
- 首次/冒烟 `qlib_scripts/build_mydata_1min.py`
- 湖 → staging `qlib_scripts/stage_1min_from_lake.py`（`tests/test_stage_1min_from_lake.py`）
- 写入 `qlib_scripts/dump_bin.py`（`is_highfreq` / `_get_all_date_highfreq`；单测 `my_tests/test_dump_bin_highfreq.py`）
- 背景 `docs/qlib-1min-infra-2026-09-18.md`
- 日频刷新 `my_docs/提示词-qlib-bin刷新.md`（不要用它刷 1min）
