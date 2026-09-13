# Runbook：新开发机搭建 + 全市场长窗实验迁移

- 日期：2026-09-13
- 发起机：Thinkpad 笔记本（本机，E:\PycharmProjects\MyQuant）
- 目标：在另一台高配置开发机上跑全市场长窗实验（handler_init 是重头，本机估 2~6 小时，高配机按核数缩短）
- 实验定义：train 2020-01-01~2024-12-31 / valid 2025-01-01~2025-12-31 / test 2026-01-01~2026-09-08；
  Alpha158CostKDJ（171 特征）+ LGBM + TopkDropout(topk=10, n_drop=3)；benchmark=SH000300
- 背景：`docs/qlib-data-state-2026-09-13.md`（数据状态）、`my_docs/提示词-指数数据修补.md`（数据修复背景）

## 1. 传输物清单（三样）

| # | 内容 | 位置 | 校验 |
|---|------|------|------|
| 1 | 代码 | git 分支 `feat/fullmarket-longwindow`（`git pull` 即可） | 以 CI/pytest 绿为准 |
| 2 | qlib 数据包 | `C:\Users\Thinkpad\.qlib\qlib_data\my_data_20260913_longwin.7z`（203 MiB / 212,935,952 字节） | **MD5 `2e8d7e26a2baf8ab3a8196af353e2813`** |
| 3 | （仅重建数据才需要）F 湖 + `F:\qlibdata` CSV 批 + `my_data_20260410_archived` 前缀 | F:/G: 盘 | 本次实验**不需要**，数据包已是最终态 |

数据包内容 = 2026-09-13 22:10 的最终 `my_data`
（日历 2020-01-02~2026-09-08 共 1621 天、5583 只股票、指数 SH000300/SH000001 全覆盖、
含重建后的 `calendars/day_future.txt`——day.txt 全量 + 末日后 5 个工作日（至 2026-09-15），
回测交易日历 `future=True` 依赖；比早上的版本多了指数 `index.txt` 登记范围修复与
day_future 重建两项。**旧 MD5 `35acc693…` 的包缺 day_future.txt，勿再使用**）。

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
print('calendar:', cal[0].date(), '->', cal[-1].date(), len(cal), 'days')   # 期望 2020-01-02 -> 2026-09-08, 1621
fut = D.calendar(future=True)
print('future calendar:', len(fut), 'days, last =', fut[-1].date())   # 期望 last > 2026-09-08（day_future.txt 顺延；若 =2026-04-17 说明包内是陈旧文件，见下方注）
df = D.features(['SH000300'], ['$close'], start_time='2026-09-01', end_time='2026-09-08')
print(df)   # 期望 2026-09-08 close=4558.74（指数修复后的真值；数据无此行=解压不完整）
inst = D.list_instruments(D.instruments(market='all'), as_list=True)
print('universe:', len(inst))   # 期望 5583
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
    --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2026-01-01:2026-09-08 \
    > train_longwindow_20260913.log 2>&1
```

- 窗口参数是 `START:END` 格式，三段必须齐全；全缺省则回落到现役三月窗（向后兼容）。
- 日志里程碑：`before handler_init(filtered)`（大头，看机器约 0.5~3 小时）→
  `after handler_init` → `before model_fit`（分钟级）→ `SignalRecord` → `PortAnaRecord` →
  `=== Train manifest saved: ... ===`。
- 高配机调优（只影响速度不影响结论）：`qlib.init(kernels=16)` 与 LGBM `num_threads=20`
  可按核数上调；内存峰值估 8~12 GB（handler 一次性持有全量特征 frame）。
- 产物（都在 `my_scripts/` 下）：
  `manifests/train_<UTC>.json`（含 **recorder_id**，Phase 2 要用）、`预测结果.csv`、
  `timing_custom_train_backtest_alpha158_cost_kdj_lgb.json`、`mlruns/` 里对应 recorder。

## 5. 跑 Phase 2：成本敏感性 + 等权基准（不重训）

```bash
cd MyQuant/my_scripts
python rebacktest_cost_tiers.py \
    --recorder-id <§4 manifest 里的 recorder_id> \
    --test 2026-01-01:2026-09-08
```

- 三档成本：zero / qlib_default(0.0005/0.0015) / realistic(0.001/0.002)，均含涨跌停 0.095 限制。
- 等权基准由 `market="all"` 全体横截面日均收益自算，输出双基准超额。
- 产出：`rebacktest_cost_tiers_summary_<UTC>.json`（普通结果文件，非 run-manifest schema）。

## 6. 注意事项

- **取回清单**（回传本机或直接在新机继续 Phase 3）：`manifests/train_*.json`、
  `rebacktest_cost_tiers_summary_*.json`、`train_longwindow_20260913.log`、
  `预测结果.csv`、timing json；如需在本机复跑 Phase 2 才用 mlruns recorder 目录。
- **判读纪律**：结论以 IC/RankIC/ICIR 为主（manifest 契约），NAV 是本次实验点名要的收益观察项；
  无论结果如何不改线上 topk 默认值。
- Linux 新机：§4/§5 命令一致；`dump_update 禁用`、`max_workers=8` 等 Windows dump 陷阱本次用不上（不 dump）。
- 首次 handler_init 无表达式缓存（缓存按机器本地存），第二次跑同窗会显著加速。

## 7. 相关文件

- 训练入口：`my_scripts/custom_train_backtest.py`（`--train/--valid/--test` 参数化见 `my_scripts/train_wiring.py`）
- 成本敏感性：`my_scripts/rebacktest_cost_tiers.py`
- 数据修复：`qlib_scripts/patch_index_data.py`（单测 `my_tests/test_patch_index_data.py`）
- 数据状态：`docs/qlib-data-state-2026-09-13.md`
