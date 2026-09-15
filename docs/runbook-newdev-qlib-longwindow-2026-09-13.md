# Runbook：新开发机搭建 + 全市场长窗实验迁移

- 日期：2026-09-13
- 发起机：Thinkpad 笔记本（本机，E:\PycharmProjects\MyQuant）
- 目标：在另一台高配置开发机上跑全市场长窗实验（handler_init 是重头，本机估 2~6 小时，高配机按核数缩短）
- 实验定义：train 2020-01-01~2024-12-31 / valid 2025-01-01~2025-12-31 / test 2026-01-01~2026-09-14；
  Alpha158CostKDJ（171 特征）+ LGBM + TopkDropout(topk=10, n_drop=3)；benchmark=SH000300
- 背景：`docs/qlib-data-state-2026-09-15.md`（当前数据状态）、`my_docs/提示词-指数数据修补.md`（数据修复背景）

## 1. 传输物清单（三样）

| # | 内容 | 位置 | 校验 |
|---|------|------|------|
| 1 | 代码 | git 分支 `feat/fullmarket-longwindow`（`git pull` 即可） | 以 CI/pytest 绿为准 |
| 2 | qlib 数据包 | `C:\Users\Thinkpad\.qlib\qlib_data\my_data_20260913_longwin.7z`（203 MiB / 212,935,952 字节） | **MD5 `2e8d7e26a2baf8ab3a8196af353e2813`** |
| 3 | （仅重建数据才需要）F 湖 + `F:\qlibdata` CSV 批 + `my_data_20260410_archived` 前缀 | F:/G: 盘 | 本次实验**不需要**，数据包已是最终态 |

数据包内容 = 当前线上 `my_data`（见 `docs/qlib-data-state-2026-09-15.md`）
（日历 2020-01-02~2026-09-14 共 1625 天、5587 只股票、指数 SH000300/SH000001 全覆盖、
含重建后的 `calendars/day_future.txt`——day.txt 全量 + 末日后 5 个工作日（至 2026-09-21），
回测交易日历 `future=True` 依赖。**旧 MD5 `35acc693…` 的包缺 day_future.txt，勿再使用**）。

数据传输方式任选：U盘/移动硬盘、局域网共享（scp/robocopy）、网盘。传完先对 MD5 再解压。

## 2. 新机环境搭建（实测配方，Windows；Linux 亦可，差异见 §6）

```bash
# ① Python 3.12 环境（conda 或 venv 均可）
conda create -n vanna312 python=3.12 -y
conda activate vanna312

# ② Qlib 源码 editable 安装（开发基准 commit 见 requirements.txt 头注，勿用 pip 的 pyqlib 包）
git clone https://github.com/microsoft/qlib.git qlib-dev
cd qlib-dev && git checkout 79633dd9 && pip install -e .
cd ..

# ③ 项目代码 + 其余依赖
git clone <本仓库> MyQuant    # 或 git pull 已有 clone
cd MyQuant
git checkout feat/fullmarket-longwindow
pip install -r requirements.txt
```

- **Redis 可选**：qlib 连不上 Redis 会自动降级为无缓存锁（脚本注释里写明了），不影响正确性，只影响缓存协作。
- CI（`.github/workflows`）就是这套配方的无人值守版，装完可对照。

## 3. 数据放置与验证

```bash
# ① 解压到用户主目录下的 ~/.qlib/qlib_data/（解压后应得到 my_data/ 目录）
7z x my_data_20260913_longwin.7z -o"%USERPROFILE%\.qlib\qlib_data" -y

# ② 读回验证（在仓库根目录，用 §2 的 python）
python -c "
import qlib, pandas as pd
from qlib.config import REG_CN
from qlib.data import D
qlib.init(provider_uri='~/.qlib/qlib_data/my_data', region=REG_CN)
cal = D.calendar()
print('calendar:', cal[0].date(), '->', cal[-1].date(), len(cal), 'days')   # 期望 2020-01-02 -> 2026-09-14, 1625
fut = D.calendar(future=True)
print('future calendar:', len(fut), 'days, last =', fut[-1].date())   # 期望 last > 2026-09-14（day_future.txt 顺延；若 =2026-04-17 说明包内是陈旧文件，见下方注）
df = D.features(['SH000300'], ['$close'], start_time='2026-09-14', end_time='2026-09-14')
print(df)   # 期望 2026-09-14 close≈4480.08（指数修复后的真值；数据无此行=解压不完整）
inst = D.list_instruments(D.instruments(market='all'), as_list=True)
print('universe:', len(inst))   # 期望 5587
"
```

> **注（2026-09-13 实踩）**：qlib 回测交易日历读的是 `calendars/day_future.txt`（`future=True`
> 分支），不读 `day.txt`。原始数据包内该文件是 4 月旧档（止于 2026-04-17），当回测
> `end_time` == 数据末日时，`get_step_time` 取「下一交易日」越界崩溃（IndexError 1524/1524）。
> 修复：`day_future.txt` = `day.txt` 全量 + 末日后 5 个工作日（本机已重建，原文件备份为
> `day_future.txt.bak_stale_20260417`）；编排器侧由 `refresh_mydata.py` 的
> `refresh_day_future_calendar` 在门禁前自动重建，后续数据包不会再带出陈旧版本。

## 4. 跑 Phase 1：主实验（一次训练 + 默认成本回测）

```bash
cd MyQuant/my_scripts
MLFLOW_DISABLE_AGENT_HINT=1 python custom_train_backtest.py \
    --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2026-01-01:2026-09-14 \
    > train_longwindow_20260914.log 2>&1
```

- 窗口参数是 `START:END` 格式，三段必须齐全；全缺省则回落到现役三月窗（向后兼容）。
- 日志里程碑：`before handler_init(filtered)`（大头，看机器约 0.5~3 小时）→
  `after handler_init` → `before model_fit`（分钟级）→ `SignalRecord` → `PortAnaRecord` →
  `=== Train manifest saved: ... ===`。
- **Windows 缓存纪律（2026-09-14，perf N3）**：`--expr-cache --dataset-cache` **只在确认同配置复跑时开**。
  闸门/宇宙/窗一变，dataset 键 miss，16 worker 读几十万小文件会比裸读更慢（窗 C Loading 52 分钟 vs 裸读 405s）。
  换配置或只跑一次：裸跑，或开 `--handler-cache`（单文件 pickle，键含日历指纹）。
- 并行：训练脚本默认 `kernels=1`（`QLIB_KERNELS` 可覆盖）。Windows 上 `kernels=16` 曾把 Loading 拖到 52 分钟。
  LGBM `num_threads=20` 可按核数调；内存峰值估 8~12 GB（handler 一次性持有全量特征 frame）。
- 产物（都在 `my_scripts/` 下）：
  `manifests/train_<UTC>.json`（含 **recorder_id**，Phase 2 要用）、`预测结果.csv`、
  `timing_custom_train_backtest_alpha158_cost_kdj_lgb.json`、`mlruns/` 里对应 recorder。

## 5. 跑 Phase 2：成本敏感性 + 等权基准（不重训）

```bash
cd MyQuant/my_scripts
python rebacktest_cost_tiers.py \
    --recorder-id <§4 manifest 里的 recorder_id> \
    --test 2026-01-01:2026-09-14
```

- 三档成本：zero / qlib_default(0.0005/0.0015) / realistic(0.001/0.002)，均含涨跌停 0.095 限制。
- 等权基准由 `market="all"` 全体横截面日均收益自算，输出双基准超额。
- 产出：`rebacktest_cost_tiers_summary_<UTC>.json`（普通结果文件，非 run-manifest schema）。

## 5.5 窗 C 复验（2025 窗 topk50 vs topk10；2026-09-14 追加，指定新机执行）

背景见 `docs/qlib-fullmarket-longwindow-report-2026-09-14.md` §7.1：窗 A（2026 全窗）与窗 B
（2026-04~08 OOS）topk50 ≫ topk10 两窗同号；本机跑窗 C 时 expr 缓存装配路径过慢已中止，
**移新机执行**。注意本机已验证两处坑：长窗需 `drop_raw=True`+零拷贝诊断（已在 master）；
`ProcessInf` 内部 `n_jobs=-1` 会拉满全部核，**务必带 `LOKY_MAX_CPU_COUNT=8`**（按新机核数可调）。

```bash
cd MyQuant/my_scripts
export MLFLOW_DISABLE_AGENT_HINT=1 LOKY_MAX_CPU_COUNT=8

# ① 2025 变体重训（train/valid 与 §4 相同，test=2025；模型等价重建，manifest 自动落盘）
python custom_train_backtest.py \
    --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2025-01-01:2025-12-31 \
    --handler-cache > train_valid2025.log 2>&1

# ② 同 pred 两轮重回测（--recorder-id 缺省取最新 recorder，即 ① 产出的；建议核对 manifest）
python rebacktest_cost_tiers.py --test 2025-01-01:2025-12-31 --topk 10 --n-drop 3 > rebacktest_C_2025_topk10.log 2>&1
python rebacktest_cost_tiers.py --test 2025-01-01:2025-12-31 --topk 50 --n-drop 5 > rebacktest_C_2025_topk50.log 2>&1
```

判读（预锁）：取两轮 summary JSON 里 `qlib_default` 档的 `abs_net_after_cost.annualized_return`，
**topk50 相对 topk10 的排序与窗 A/窗 B 同号**（更高或更低）→ 三窗成立，宽名单族多窗证据闭环；
结果无论方向，回写报告 §7.1 并按预锁纪律处理（不改线上 topk 默认，改参需正式流程）。

> **执行结果（2026-09-14，新机完成）**：窗 C 反号——topk10 净年化 +92.0% > topk50 +87.8%
> （IR/回撤/换手仍偏 topk50，详见报告 §7.2）。三窗一致性不成立，按预锁纪律不改线上 topk
> 默认。新机备注：dataset 缓存键含闸门配置，全开闸门首跑必 miss（数据加载 52 分钟，慢于
> guards-off 的 21 分钟属预期）；expr 缓存可跨窗复用。

## 5.6 过滤开关实验（2026 窗，四开关全开 vs 无过滤基线；2026-09-14 追加）

前置：§2 环境 + my_data 就位 + **分支 `feat/st-wind-pit-feed`**（PR #36，含四开关、
Wind ST PIT 接线；若已合并则 master 等价）。

### ① 传两个数据目录（发起机 → 新机，保持相对结构）

| 源（发起机） | 放到（新机） | 体积 |
|---|---|---|
| `MyQuant/my_scripts/mlruns/312677471335446378/4410e4a3a4714f4f9e261120449232d1/` | `MyQuant/my_scripts/mlruns/312677471335446378/…`（同路径） | 15 MB |
| `F:/stock_data/vendor_wind_st_status/`（整个目录） | `F:/stock_data/vendor_wind_st_status/` | <1 MB |
| `F:/stock_data/cyq_winner_ratio_20260914.7z`（或整个 `cyq_winner_ratio/` 目录） | `F:/stock_data/` 下解压，得到 `cyq_winner_ratio/` | 7z **6.57 MiB**；parquet MD5 `644750b32010922b7721795359b98620` |

（recorder = 2026 窗现有 pred，重回测免重训；ST PIT 为 Wind 收割产物；盈筹率为本仓 CYQ 外部 parquet，与 ST 同级，不进 bins。）

盈筹率包解压与校验：

```bat
7z x cyq_winner_ratio_20260914.7z -oF:\stock_data -y
certutil -hashfile F:\stock_data\cyq_winner_ratio\cyq_winner_ratio_daily_2026.parquet MD5
:: 期望 644750b32010922b7721795359b98620
:: 7z 本身 MD5 ababd3798e17db48f602caf4ac85277f
```

### ② 宇宙文件现生成（不传文件，重跑脚本即得）

```bash
cd MyQuant/my_scripts
python build_tradable_universe.py
# 期望输出: 全宇宙 5583 → 剔除ST 177 → 保留 5406，起始日顺延 60 个交易日
#           → ~/.qlib/qlib_data/my_data/instruments/all_tradable.txt
```

只读 `all.txt` + `day.txt` 两个文本（秒级、零外部依赖）。说明：ST 剔除用静态
EXCLUDE_STOCKS_DEFAULT；PIT 精确层由 ③ 的 `--st-daily-file` 在策略级承担。

### ②b 精确盈筹率（优先拷包，与 ST 同级；不必在新机重算）

① 已含 `cyq_winner_ratio/`。消费文件：

`F:/stock_data/cyq_winner_ratio/cyq_winner_ratio_daily_2026.parquet`

期望：912,350 行、5569 只、166 日（2026-01-05～09-08）、列 `stock_code/date/winner_ratio`。
对拍见 `docs/winner-ratio-cyq-parity-2026-09-14.md`。

新机若已有完整 my_data 且想复核，才重跑（约 1～3 分钟，依赖 numba）：

```bash
python build_winner_ratio.py --test 2026-01-01:2026-09-14 --workers 8 \
    --out F:/stock_data/cyq_winner_ratio/cyq_winner_ratio_daily_2026.parquet
# 期望: DONE stocks≈5569+/5587 rows 随末日前推略增
```

### ③ 四开关全开重回测（topk10 与 topk50 各一轮）

```bash
export MLFLOW_DISABLE_AGENT_HINT=1 LOKY_MAX_CPU_COUNT=8
python rebacktest_cost_tiers.py \
    --recorder-id 4410e4a3a4714f4f9e261120449232d1 \
    --test 2026-01-01:2026-09-14 --topk 10 --n-drop 3 \
    --buy-state-filter --st-filter --age-filter \
    --st-daily-file "F:/stock_data/vendor_wind_st_status/st_daily.parquet" \
    --winner-ratio-file "F:/stock_data/cyq_winner_ratio/cyq_winner_ratio_daily_2026.parquet"
python rebacktest_cost_tiers.py \
    --recorder-id 4410e4a3a4714f4f9e261120449232d1 \
    --test 2026-01-01:2026-09-14 --topk 50 --n-drop 5 \
    --buy-state-filter --st-filter --age-filter \
    --st-daily-file "F:/stock_data/vendor_wind_st_status/st_daily.parquet" \
    --winner-ratio-file "F:/stock_data/cyq_winner_ratio/cyq_winner_ratio_daily_2026.parquet"
```

无过滤基线（同机同 pred，qlib 默认档）：topk10 净年化 **-46.5%** / topk50 **+0.6%**。
判读问题：过滤能否救 topk10、是否拖累 topk50。跑完取回两份
`rebacktest_cost_tiers_summary_*.json` 回写报告 §7.4。

> **执行结果（2026-09-14，新机完成）**：新机无 4410e4a3 recorder，按预案改用本机同配置
> 2026 窗 pred（`95e18c5a…`，manifest train_20260913T105221Z）——无过滤基线复算得
> topk10 **-46.5%** / topk50 **+0.6%**，与发起机基线逐位一致（两机 pred 等价）。ST 数据
> 路径按本机实际为 `E:/stock_data/vendor_wind_st_status/st_daily.parquet`。四开关全开
> （qlib 默认档，净年化）：
>
> | 配置 | 关过滤 | 开过滤 | 变化 |
> |---|---|---|---|
> | topk10/n3 | -46.5% | **-24.0%**（IR -0.58，回撤 -41.9%） | +22.5pp |
> | topk50/n5 | +0.6% | **+9.1%**（IR +0.27，回撤 -28.0%，超额 vs 等权 +6.1pp） | +8.4pp |
>
> 两问皆有答案：过滤救回 topk10 一半亏损但仍是深负；**不拖累 topk50，反而大幅加持**
> （IR/回撤同步改善，换手不变 31.1×）。四份 summary 已入库（T090433/T091013 基线，
> T101143/T105327 过滤开）。§7.4 对比撰写留给发起机。
>
> 新机 perf 注：Windows 下 qlib `kernels>1` 每次小数据查询固定 ~29s 进程池开销
> （D.features 50 股单日 29s → kernels=1 时 0.09s）；资格过滤策略每日小查询，
> 已把 rebacktest_cost_tiers **与** custom_train_backtest 的 kernels 默认改为 1（QLIB_KERNELS 可覆盖），
> 过滤轮回测从 ~100s/bar 降到 ~3.6s/bar。训练 Loading 用 `--handler-cache` 复跑，勿默认开 expr/dataset 小文件缓存。
>
> **执行结果（2026-09-15，F 湖 PIT 四过滤）**：recorder 改回发起机 `4410e4a3…`；ST 读
> `F:/stock_data/vendor_wind_st_status/st_daily.parquet`（日志 `PIT+fallback 280` 只，
> 不再用 09-14 的 `E:/…` 旧路径）。四开关全开、qlib 默认档净年化：
>
> | 配置 | 关过滤 | 开过滤 09-14（E 盘旧 ST） | 开过滤 09-15（F 湖 PIT） |
> |---|---|---|---|
> | topk10/n3 | -46.5% | -24.0% | **−7.4%**（IR −0.17，回撤 −56.2%） |
> | topk50/n5 | +0.6% | +9.1% | **+15.5%**（IR +0.43，回撤 −31.1%） |
>
> 判读不变：过滤仍救 topk10 且不拖累 topk50。NAV 变好是 ST 覆盖/日期换成 PIT 的预期，
> 不是同一张 ST 表的复现。墙钟：preload + 三档约 **5.7 / 5.9 min**，回测环 **~0.15–0.17 s/bar**
> （6 it/s）。summary：`T161924Z` topk10、`T162527Z` topk50。

## 6. 注意事项

- **取回清单**（回传本机或直接在新机继续 Phase 3）：`manifests/train_*.json`、
  `rebacktest_cost_tiers_summary_*.json`、`train_longwindow_20260913.log`、
  `预测结果.csv`、timing json；如需在本机复跑 Phase 2 才用 mlruns recorder 目录。
- **判读纪律**：结论以 IC/RankIC/ICIR 为主（manifest 契约），NAV 是本次实验点名要的收益观察项；
  无论结果如何不改线上 topk 默认值。
- Linux 新机：§4/§5 命令一致；`dump_update 禁用`、`max_workers=8` 等 Windows dump 陷阱本次用不上（不 dump）。
- 首次 handler_init 无缓存时按裸读（Windows 默认 kernels=1，约数分钟～十几分钟）。
  同配置复跑优先 `--handler-cache`（`~/.cache/qlib_handler_cache`），不要靠 95 万个 expr 小文件。

## 7. 相关文件

- 训练入口：`my_scripts/custom_train_backtest.py`（`--train/--valid/--test` 参数化见 `my_scripts/train_wiring.py`）
- 成本敏感性：`my_scripts/rebacktest_cost_tiers.py`
- 数据修复：`qlib_scripts/patch_index_data.py`（单测 `my_tests/test_patch_index_data.py`）
- 数据状态：`docs/qlib-data-state-2026-09-13.md`
