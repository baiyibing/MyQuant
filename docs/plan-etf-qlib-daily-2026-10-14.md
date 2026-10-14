# 任务书：ETF 日线 qlib 实验（独立 bin → 读回 → Alpha158 冒烟）

- 日期：2026-10-14
- 状态：**草案 v0.2，已补 GO-WITH-NITS 评审意见，待合并**。本 PR 只落本文，不写 staging、不灌 bin、不跑训练。
- 风险档：中。新 provider 与股票 `my_data` 隔离；灌错目录会污染股票宇宙。
- 数据源说明：OSkhQuant1.3 `docs/operations/etf-qmt-download.md`（PR [#1167](https://github.com/baiyibing/OSkhQuant1.3/pull/1167)，`docs(data): record the QMT channel for ETF daily and minute downloads`）。
- 本机探针：2026-10-14 对 `E:\stock_data`（用户环境变量 `OSKH_SOURCE_PARQUET_ROOT`）的抽样。实现时以当时湖为准重算，下文带「探针」的数字是草案锚，不是永久门禁。
- 上游约束：`docs/plan-midterm-m1m4m2m3-2026-09-13.md` §0（`dump_all` workers=8、禁用 `dump_update`、湖 `time` 转上海日期、禁止从 `cn_data` 拷 bin、qlib 入口要有 `freeze_support`）。股票编排器 `qlib_scripts/refresh_mydata.py` **不负责**本任务。

---

## 0. 一句话

用已经落湖的 ETF **日线前复权**，灌到一套新的 qlib provider `~/.qlib/qlib_data/my_data_etf`。读回对上湖之后，再用官方 `Alpha158` + 小 LightGBM 在长历史子集上做一次 IC 冒烟。股票 `my_data` 不读不写。分钟线、股票训练入口、成交核都不在本计划。

```text
E:\stock_data\etf\period=1d\dividend_type=front
        │  stage（上海日期、丢掉占位 0、裁到 2020-01-02..2026-10-13）
        ▼
D:\qlib_data\_staging_etf_1d\sh510300.parquet
        │  dump_bin dump_all --max_workers=8
        ▼
~/.qlib/qlib_data/my_data_etf          ← 独立 provider
        │  读回验收
        ▼
my_scripts/train_etf_smoke.py          ← Alpha158 + LGB，宇宙 etf_full
```

---

## 1. 探针事实（2026-10-14）

湖布局与 1.3 文档一致：日线在 `etf/period=1d/dividend_type={none,front}/symbol=*_*/data.parquet`。列是 `time, open, high, low, close, volume, amount`。`time` 是 UTC 毫秒；转到 `Asia/Shanghai` 后小时是 8，**日期就是交易日**（00:00 UTC = 当日 08:00 上海）。

| 项 | 探针 |
|---|---|
| `dividend_type=none` 文件 | 1669 |
| none 里 `close>0` 且 `volume>0` | 1629 |
| none 整段无有效 OHLC | 40（与 front 少的 40 只是同一批占位过滤） |
| `dividend_type=front` 文件 | 1629 |
| none 有效窗 | **2020-01-02 → 2026-10-13**（下载窗 `20200101→20261013`；更早的行是 0） |
| 8 只流动性 ETF 的有效日并集 | **1640** 天，无周末。标的：`510050/510300/510500/510180/513100/518880` 的 SH，`159915/159919` 的 SZ |
| 末日不是 2026-10-13 | 仅 `512390.SH`，止于 **2026-09-04**（1539 根有效 K） |
| 窗口起点就有行情、末日 ≥ 2026-10-01、有效根数 ≥ 1000 | **225**（none 侧；中位数 1640） |

`510050`：none 有效首收 3.081（2020-01-02）、末收 2.917（2026-10-13）。front 从上市日 2005-02-23 起就有有效 K，末收与 none 同为 2.917（前复权末端比 1.0）；两套在 2020-01-02 的收盘比约 0.90。front 在 2020 之前还有历史，**v1 不用**。

量是手。末根抽查：`vwap = amount / (volume × 100)` 与收盘同量级（510300 末根成交额约 46.8 亿，vwap 4.326，close 4.345）。

分钟不进 v1。1.3 文档写明这条 QMT 渠道补不出 2020 年起的有效 ETF 分钟；2026-10-14 续跑是板块 1671、跳过 1187、新写入 442、42 只无有效 OHLC。

---

## 2. 草案决定（评审打回就改本文，不在实现 PR 里另起一套）

| ID | 决定 | 草案 |
|---|---|---|
| P-1 | provider | 新建 `~/.qlib/qlib_data/my_data_etf`。目标与受保护的股票 `~/.qlib/qlib_data/my_data`、分钟 `my_data_1min` 路径均须解析 `realpath`（含符号链接等别名）。目标若等于、是祖先或是后代，进程拒绝启动；仅比较路径相等不足以保护目录，检查必须在任何清空操作之前完成。 |
| P-2 | 复权 | 灌 **front**。Alpha158 和标签吃的是收益率；末端价格等于现价。none 留在湖里，不进这套 bin。 |
| P-3 | 窗口 | **2020-01-02 ~ 2026-10-13**。对齐 none 的有效窗和股票实验年代。510050 的 2005–2019 front 历史单独立项，不塞进 v1。 |
| P-4 | 占位行 | `close<=0` 或 `volume<=0` 的行丢掉。40 只全零代码不产生 staging 文件，不进 `all.txt`。 |
| P-5 | 日历 | 以 **`510300_SH` front** 在窗口内的有效交易日为唯一日历（探针期望 1640、无周末）。其他标的的日期必须是它的子集；多出来的日期中止，禁止用全市场并集把废日期写进 `day.txt`。 |
| P-6 | 代码 | 沿用 `stage_1min_from_lake.lake_partition_to_qlib_code`：`510300_SH` → `SH510300`。文件名 `sh510300.parquet`，交给现有 `dump_bin` 的 `fname_to_code`。 |
| P-7 | 字段 | `open, high, low, close, volume, amount, vwap`。`vwap = amount / (volume × 100)`，量保持手。VWAP 是 Alpha158 兼容 dump 的特征字段，不是独立标签；E3 验收前必须验证该公式所得 VWAP 与 front OHLC 的复权口径一致。末端抽查不能确认历史 amount/volume 是否复权，须核对历史口径并记录证据，未确认一致不得通过 E3。不写 `$factor`（价格已经是前复权）。staging 可以带 `symbol` 列，dump 时 `--exclude_fields=symbol`。 |
| P-8 | 宇宙 | `instruments/all.txt` = 全部成功 staging 的 ETF（探针约 1629，含上市晚的）。另写 `instruments/etf_full.txt`：名字表示「长历史子集」，不保证完整窗口，允许窗口中途缺日；筛选条件为窗口第一天就有 K、末日 ≥ 2026-10-01、窗口内根数 ≥ 1000。探针 225 来自 **none**，实现时用 **front staging** 重算，允许数量变化，但必须是 `all.txt` 的子集。`512390` 这种 2026-09-04 收尾的留在 `all.txt`，不进 `etf_full`。末日筛选会引入幸存者偏差，实验解释须注明；E3/E4 日志均须报告逐标的缺日比例（相对 P-5 窗口日历）及其汇总。 |
| P-9 | 灌库 | 只走 `dump_bin.py dump_all`。`--file_suffix=.parquet`，`--max_workers=8`。禁用 `dump_update`。半成品目标目录先清空再灌。不调用 `refresh_mydata.py`，不调用 `patch_index_data.py`。 |
| P-10 | 第一轮模型 | 官方 `qlib.contrib.data.handler.Alpha158`，宇宙 `market="etf_full"`。标签用 handler 默认 `Ref($close, -2)/Ref($close, -1) - 1`。切分：训练 2020-01-02~2023-12-29，验证 2024-01-02~2024-12-31，测试 2025-01-02~2026-10-13。handler / preprocessor 的 fit 起止仅限训练期，验证与测试不得参与拟合。默认标签引用未来第 1、2 个交易日，分段末尾会跨越切分边界，序列末端标签未定义；须记录跨界样本的处理规则及各分段有效标签样本数，验收排除跨界与未定义标签。模型是小 LightGBM。基准 `SH510300`。先记 IC；IC 必须来自非空有效样本且为有限值，通过之后才允许加 `TopkDropout`。 |
| P-11 | 入口 | 新脚本 `my_scripts/train_etf_smoke.py`，形状对齐 `train_1min_smoke.py`：provider 只能是 `my_data_etf`，`kernels=1`，`if __name__ == "__main__"` + `freeze_support()`。不改 `custom_train_backtest.py`（ST / 涨停 / 赢筹是股票过滤）。 |

债券 ETF、货币 ETF v1 留在 `etf_full` 里。先看到未筛选宇宙的 IC，再用成交额或类型门槛收窄，避免宇宙还没跑就被定死。

---

## 3. 明确不做

- 不改 `~/.qlib/qlib_data/my_data` 与 `my_data_1min`，不把 ETF 行补进股票 `all.txt`。
- 不灌分钟，不把 42 只无 OHLC 的分钟代码当成日线缺口去重下。
- 不从 `cn_data` 拷 bin，不猜 `E:`/`F:` 以外的湖根：湖根只认 `OSKH_SOURCE_PARQUET_ROOT` 或显式 `--lake-root`。日线子树是 `{container}/etf/period=1d`；`OSKH_ETF_DAILY_ROOT` 仅在已设置时覆盖。
- 不跑 PortAna 当产品结论。判优只看 IC / Rank IC。单窗净值不入库。
- 不把本计划扩成股票编排器的一环，不改 `dump_bin.py` 的日历并集行为；日历门禁放在 ETF 编排器里，在调用 `dump_all` 之前做完。

---

## 4. 切片

实现从 master 拉 `feat/etf-qlib-daily`。本文件所在 PR 合完之前不要开实现 PR。编码只做下表。

| 片 | 产物 | 内容 | 验收 |
|---|---|---|---|
| **E1** | `qlib_scripts/stage_etf_daily_from_lake.py` | hive front → 每只一个 parquet。上海日期、P-3 裁窗、P-4 丢行、P-6 文件名、P-7 字段。空帧不写文件。默认湖根走 `my_scripts/data_root.py` 的 `resolve_etf_1d_none()` 的同级 `dividend_type=front`（不要把 none 当默认）。staging 默认 `D:\qlib_data\_staging_etf_1d`。 | `tests/test_stage_etf_daily_from_lake.py`：代码转换、UTC 毫秒 → 上海日期、0 行丢弃、vwap、窗外行不出现。不读真实湖。 |
| **E2** | `qlib_scripts/build_etf_qlib.py` | 子进程串 E1 → 日历门禁 → `dump_all`。`--dry-run` 只打印计划。按 P-1 对目标和股票 `my_data` / `my_data_1min`（含别名）解析 `realpath`；相等、祖先或后代关系均退出非 0，必须先检查再执行任何 wipe。`--wipe-qlib-dir` 才允许清空**新**目录里的半成品。workers 钉死 8，传别的值拒绝。 | `tests/test_build_etf_qlib.py`：对 `my_data` / `my_data_1min` 的相等、祖先、后代及符号链接等别名路径均拒绝，并断言拒绝发生在任何 wipe 之前；workers≠8 拒绝；合成日历里出现子集外日期则中止且不调用 dump。 |
| **E3** | 宿主跑 E2 | 真实湖 → `my_data_etf`。日志记下 staging 文件数、`all.txt` 行数、`etf_full.txt` 行数、日历首末日与长度、`etf_full` 逐标的缺日比例及汇总、末日筛选的幸存者偏差。 | `calendars/day.txt` 无周末，首日 2020-01-02，末日 2026-10-13。`D.features` 读回 `SH510050`、`SH510300`、`SZ159915`、`SH518880` 的窗口首末收盘与 front 湖一致（容差 1e-4）。`512390` 若仍在湖里，登记末日是它的最后有效日，而不是日历末日。40 只全零代码不在 `all.txt`。按 P-7 核验历史 VWAP 与 front OHLC 的复权口径一致并留下证据，不能仅凭末端抽查验收。 |
| **E4** | `my_scripts/train_etf_smoke.py` | P-10 / P-11。产物目录 `exports/etf_smoke/`（gitignore 已覆盖的导出不要强制入库）。MLflow 实验名 `etf_daily_smoke`。 | 冒烟能 `fit` + `predict`；记录 handler / preprocessor 仅在训练期 fit 的边界、跨切分标签处理及各分段有效标签样本数、`etf_full` 缺日比例及汇总与幸存者偏差。IC 验收要求预测与标签均有效的样本非空，且计算出的 IC 为有限值；仅日志含「IC」不算通过。失败就停，不自动改标签、不换模型、不加 `TopkDropout`。 |

v1 本次实验锁定 P-3 窗口末日为 **2026-10-13**，E3 验收末日与 P-10 测试末日保持一致。E3 的日历长度探针是 1640；实现时按固定窗口内的 `510300` 有效日重算，并在实现 PR 说明实际长度。即使湖新增交易日，也只记录湖增长情况，不延长 P-3、测试末日或验收末日；延长须先显式修订本计划。

---

## 5. 评审时请直接改的点

下面每条都已经有草案。不同意就在 PR 里点名 ID，不要只说「再看看」。

1. **P-2** 用 front 而不是 none。反对意见通常是：前复权用了未来分红。v1 接受这一点，因为标签是收益率、末端要等于现价。若评审要求 point-in-time，本计划作废，另开「factor 列」计划。
2. **P-5** 日历钉死 510300，而不是 `dump_all` 默认的全文件并集。并集会把单只 ETF 的脏日期写进所有 bin 的下标。
3. **P-8** 第一轮训练用长历史子集（允许中途缺日），而不是 1629 只全市场。全市场里 2025–2026 新上市很多，Alpha158 暖机会吃掉它们的大部分历史。
4. **P-10** 直接上官方 Alpha158，而不是先做 5 个收益率特征的更小 handler。小 handler 更快，但和股票实验无可比性。
5. **P-11** 新脚本，而不是给 `custom_train_backtest.py` 加 `--provider etf`。加开关容易把 ST/涨停过滤带到 ETF 上。

没有第 6 个开放项：分钟、并入股票 `my_data`、2020 年之前的 front 历史，都不在本轮评审范围里。
