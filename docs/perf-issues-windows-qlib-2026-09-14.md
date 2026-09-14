# MyQuant 实验 性能问题档案（新机 Windows，2026-09-14）

- 范围：全市场长窗实验（qlib 0.9.8.dev32 @ commit 79633dd9，editable 装于
  `D:\PycharmProjects\qlib-dev`；Python 3.12 conda env `vanna312`；Windows 10.0.26200）
- 目的： consolidated 记录 2026-09-13~14 实验中暴露的全部性能问题——来龙去脉、原现场、
  原因分析、已做修改、下一步建议——供后续 agent 跟进，不必重新踩坑
- 关联文档：`docs/runbook-newdev-qlib-longwindow-2026-09-13.md` §5.5/§5.6（执行备注）、
  `docs/qlib-fullmarket-longwindow-report-2026-09-14.md` §7.2

## TL;DR（问题 × 状态）

| # | 问题 | 影响 | 状态 |
|---|---|---|---|
| P1 | Windows 下 qlib `kernels>1` 每次小数据查询固定 ~29s 进程池开销 | 过滤策略回测 100s/bar（一轮 4.6h） | **已修复**（两脚本默认 kernels=1，25×提速）；custom_train_backtest.py 仍 16 待改 |
| P2 | 表达式缓存首填 = ~95 万个小文件写盘，比不缓存还慢 4× | 冷缓存首跑 Loading 1262s vs 无缓存 405s | 已量化，未修（复跑场景仍净赚，见 P3） |
| P3 | 缓存键含 filter_pipe 配置：闸门/宇宙一变即全部 miss | 窗C（闸门全开+缓存）Loading 3115s，比无缓存慢 7.7× | **开放问题**，见 §建议 N1 |
| P4 | SimpleDatasetCache 单文件键 + Windows 小文件读：16 worker 争抢 | 旧机窗C 因此中止（"expr 缓存装配路径过慢"） | 同 P3，属同一病灶 |
| P5 | `ProcessInf` 内部 `n_jobs=-1` 拉满全部核 | 与 qlib kernels 叠加造成过订阅 | 已知，须带 `LOKY_MAX_CPU_COUNT=8`（runbook §5.5） |
| P6 | 疑点：CYQ 合并后 topk50 关过滤明细净值 -406 万 ≠ 重回测 +0.65% | 正确性（非纯性能），明细级分析被冻结 | **待查**，见 §建议 N6 |

## 一、来龙去脉（时间线）

1. **09-13 Phase 1 基线**（topk10/n3，闸门全开，无缓存旗标）：全窗 632s，Loading 405s——
   无缓存裸读 bin 的基准线。
2. **09-13 闸门全关重跑**（首启 `--dataset-cache --expr-cache`）：Loading 1262s——比裸读慢，
   因为表达式缓存首填要写 `features_cache/` 下 5583 股 × ~171 表达式 ≈ **95 万个小文件**
   （实测目录 7.5 GB）。当时判断"一次付清"，未深究。
3. **09-13 同命令复跑（缓存热）**：Loading **12.5s**（相对首填 ~100×），端到端 1734s→255s。
   结论"缓存对同配置复跑有效"成立，掩盖了 P3。
4. **09-14 窗C（2025 变体，闸门全开+双缓存）**：Loading **3115s（52 分钟）**——比无缓存基线
   慢 7.7×。同日旧机跑同实验直接中止（报告 §7.1："dataset 缓存按键未命中、16 worker 读
   几十万小缓存文件"），移新机执行也没躲过。
5. **09-14 §5.6 过滤实验**：四开关全开的重回测首轮 **~100s/bar，预计 4.6h/轮**（重测脚本
   共 3 档成本 × 166 bar，实际不可接受）。定位为 P1（见下），修后 **3.6s/bar，10 分 19 秒
   跑完单轮回测**。无过滤基线不受影响（qlib 原生策略无逐日小查询，~2min/轮）。
6. **09-14 导出脚本踩同坑**：export_positions_trades 接入过滤开关后首次运行 7.8s/bar——
   同 P1 病根，同修。

## 二、原现场（可复现命令 + 数字）

### P1 kernels 进程池开销（最硬的一条）

```bash
# 探针（新机实测）：
#   kernels=8:  D.features(50股, $close, 单日)  冷=29.30s 温=28.92s
#   kernels=1:  同查询                            冷=0.09s 温=0.01s
# 开销与缓存冷热无关 → 不是缓存问题，是每次调用的进程池固定成本
cd my_scripts && /d/anaconda3/envs/vanna312/python.exe -c "
import host_env, time, qlib, pandas as pd
from qlib.config import REG_CN
from qlib.data import D
qlib.init(provider_uri='~/.qlib/qlib_data/my_data', region=REG_CN, kernels=8)  # 对比 1
codes=['SH600000','SZ000001','SH600036','SZ300750','SH688981']*10
t0=time.time(); D.features(codes, ['\$close'], start_time='2026-01-05', end_time='2026-01-05'); print(time.time()-t0)
"
```

- 放大器：`TopkDropoutStrategyWithFilter._filter_stocks_by_return_threshold`
  （custom_strategy.py:167,175）**每根 bar 调 2 次 D.features 小查询**；
  `BuyEligibilityFilter` 已有整窗 preload（buy_eligibility.py:128，纯查表）不踩此坑。
- 日志证据：`st_exp_topk10_on.log` 首跑 `96.79s/it…100s/it`（bar 7-10 稳定）；
  修后同命令 `3.58s/it`（166/166 用时 10:19）。

### P2/P3/P4 缓存三连（首填贵、键敏感、小文件读）

| 运行 | 命令要点 | Loading | Init data | 出处 |
|---|---|---|---|---|
| 基线，无缓存旗标 | `custom_train_backtest.py --train… --test 2026窗` | 405.1s | 472.1s | train_longwindow_20260913.log |
| 闸门全关，缓存冷（首填） | 同上 + `--no-*` 三开关 + `--expr-cache --dataset-cache` | 1262.2s | 1357.2s | train_longwindow_noguards_20260913.log |
| 闸门全关，缓存热 | 同上再跑一遍 | **12.5s** | 100.7s | train_longwindow_noguards_cachehit.log |
| 窗C 闸门全开，双缓存 | `--test 2025窗 + --expr-cache --dataset-cache` | **3114.6s** | 3191.4s | train_valid2025.log |

- 缓存实体：`~/.qlib/qlib_data/my_data/features_cache/`（DiskExpressionCache，
  7.5 GB / 5583 个股票目录）；`~/.cache/qlib_simple_cache/`（SimpleDatasetCache）。
- 键机制（已读源码确认）：`D.instruments` 把 filter_pipe 序列化成纯 dict
  （data.py:252-262，`to_config()`），`hash_args` = md5(sorted json)——**键稳定且区分
  闸门配置**（正确性没问题），但任何配置差异（开关、黑名单、宇宙）都是全量 miss。
- 旧机现场（报告 §7.1 引述）："本机重训 2025 变体时 expr 缓存装配路径过慢（dataset
  缓存按键未命中、16 worker 读几十万小缓存文件），已中止"。

### P5 LOKY 过订阅

`ProcessInf`（infer_processors 之一）内部 `n_jobs=-1` 会拉满全部物理核，与 qlib
kernels 的进程池叠加；旧机已实踩并写入 runbook §5.5：务必带 `LOKY_MAX_CPU_COUNT=8`。

### P6 CYQ 合并后的明细-基线不一致（待查，非纯性能）

- 合并前（18:30 前）重回测：topk50/n5 关过滤 `abs_net_after_cost.ann=+0.65%`
  （summary T091013Z），与发起机基线逐位一致。
- 合并 #37（CYQ）后，export_positions_trades 导出同配置：**nav_delta=-4,055,365**
  （导出内对账 diff=0.00%，即个股盈亏合计=净值变动，自洽），但与 +0.65%≈+38 万矛盾。
- 影响：今日导出的两份 topk50 明细 CSV（exports/*T1125*、*T1127*）**暂不可作结论依据**；
  §5.6 四轮汇总数字不受影响（合并前代码所出）。

## 三、原因分析（机制层）

1. **P1**：qlib 多 kernel 数据加载在 Windows 上每次 `D.features` 调用都要重建/同步
   进程池（spawn + IPC + 序列化），固定成本 ~29s，与数据量无关——小查询被纯开销淹没。
   未深入 qlib 源码定位到具体行（跟进项 N2）；Linux 上同版本未见此问题（旧机对照）。
2. **P2**：DiskExpressionCache 按 股票×表达式 两级目录落单文件，95 万个小文件的
   create/close 在 NTFS 上是数量级开销；裸读 bin 反而走顺序大 IO。
3. **P3/P4**：三层缓存的键都包含 instruments 配置（含 filter_pipe 序列化）。配置一变：
   dataset 键 miss → 走 16 worker 逐表达式装配 → 每个小文件读都被 16 进程争抢
   （NTFS metadata lock）→ 比单进程裸读更慢。缓存只在「完全同配置复跑」时是净赚。
4. **P5**：joblib/loky 默认占满物理核，与外层并行度无协调。
5. **P6**：尚未定位。候选嫌疑：a40be85/CYQ 对 BuyEligibilityFilter 或 custom_strategy
   的行为改动波及了"关过滤"路径以外的公共代码（如 EXCLUDE_STOCKS_DEFAULT、导出脚本
   的策略装配差异），或导出与重回测在 exchange/pred 加载上存在隐性差异。需 bisect。

## 四、已做修改（均已入库）

| 提交 | 内容 |
|---|---|
| 49dbe80→1177b64（PR #39） | `rebacktest_cost_tiers.py`：kernels 默认 16→1，`QLIB_KERNELS` 环境变量可覆盖；§5.6 执行记录 + 四份 summary 入库 |
| e6ea42b（PR #39） | `export_positions_trades.py`：接入四开关（复用 build_strategy_config）+ 同款 kernels 修复 + elig_ tag |
| 9d9a1ab / 87a3fea | 同上两笔在 ST 分支的原始提交（分支已清，内容经 #39 进 master） |
| 修复效果 | 过滤重回测 100s/bar → 3.6s/bar；§5.6 四轮全部跑完（topk10 -46.5%→-24.0%，topk50 +0.6%→+9.1%） |

未改动但相关：`custom_train_backtest.py` 的 qlib.init 仍硬编码 `kernels=16`
（见 §五 N2）；磁盘占用 `features_cache` 7.5 GB 在 `my_data` 目录内（数据刷新原子换名
时自动失效，属设计内；`qlib_simple_cache` 需手工清）。

## 五、下一步建议（给跟进 agent，按优先级）

- **N1（收益最大）给 handler 数据装载做项目级单文件缓存**：绕开 qlib 的表达式/数据集
  双层小文件缓存——按 `config_hash`（manifest 已有）把 `handler.fetch()` 的全量特征
  frame 落成单个 parquet/pickle（8~12 GB 顺序 IO，Windows 友好），二次运行直接
  `pd.read_parquet`。验收：窗C 同配置二次运行 Loading < 60s；跨闸门配置互不污染
  （键含 config_hash 天然隔离）。注意 train/eval 双窗与 fit_start/fit_end 归一化参数
  必须进键。
- **N2 统一 kernels 修复到训练脚本**：`custom_train_backtest.py` 的 `kernels=16` 改为
  `int(os.environ.get("QLIB_KERNELS", "1"))`（新机 handler 阶段单进程裸读 405s，
  16 进程在 Windows 上反而 3115s——窗C 实证；旧机 Linux 结论不适用）。顺带在
  qlib-dev 源码里定位 P1 的具体开销点（嫌疑：`DatasetProvider` 每调用重建进程池），
  可考虑给 qlib-dev 打本地补丁或上游 issue。
- **N3 决定缓存旗标的默认策略**：在 N1 落地前，Windows 上建议 `--expr-cache
  --dataset-cache` 只在「确认要同配置复跑」时使用；否则裸读更快（405s vs 1262s/3115s）。
  可把该结论写进 runbook §2/§4。
- **N4 小文件缓存的清理纪律自动化**：`refresh_mydata.py` 换目录后提示/自动清
  `~/.cache/qlib_simple_cache`（expr cache 随 my_data 换名自动失效，无需处理）。
- **N5 ProcessInf 的 n_jobs 显式化**：processor 配置里显式 `n_jobs=8` 或读
  LOKY_MAX_CPU_COUNT，去掉对环境变量的隐性依赖。
- **N6 查 P6 差异（正确性）**：bisect a40be85 前后：同一 pred（95e18c5a）、同一命令
  （topk50/n5 关过滤重回测）分别在新代码与 `49dbe80^` 上跑，diff 两份 report 的逐日
  return/turnover 定位首笔分歧日；重点核对 CYQ 是否改了 `TopkDropoutStrategyWithFilter`
  之外的公共路径（EXCLUDE_STOCKS_DEFAULT、SMA、exchange 构造）。在定位前，
  **冻结使用 post-merge 导出的明细 CSV**。
- **N7 复跑基线对照表**：把本档案 §二 的四行数字作为回归基线，任何缓存/并行改动后
  重测同四行，防止"修好一处劣化三处"。

## 七、质询复核（2026-09-14 晚，按日志时间戳逐轮核实）

质询一："今天加了过滤以后，变慢太多" —— **属实，同配置慢 6.6~7.6×**：

| §5.6 重回测（topk50/n5，同 pred 同窗） | 起止（本地时） | 耗时 |
|---|---|---|
| 关过滤（kernels=16 时代跑的基线） | 17:04:42 → 17:10:13 | **5.5 min** |
| 开过滤（kernels 修复后） | 18:11:52 → 18:53:27 | **41.6 min** |
| （topk10/n3 同样对比） | 5.5 min vs 36.2 min | ~6.6× |

- 修复前的首跑更极端：kernels=16 时 100s/bar，3 档成本全跑预计 **~14 小时**，已在 bar 10 中止。
- 修复后仍剩 ~7× 的固有差距，构成：preload 全市场 Quantile($close,250)（每轮 3~5 min，
  一次付清）+ 过滤策略每根 bar 2 次小查询 + 资格层逐票查表；基线用的 qlib 原生策略
  完全没有这些动作。

质询二："昨天加了缓存之后，太慢了" —— **属实，冷启/异配置 2.7~5.7× 慢，仅同配置复跑反超**：

| custom_train_backtest（kernels=16 未修，2026/2025 窗） | 起止 | 总耗时 | 对基线 |
|---|---|---|---|
| 基线（无缓存旗标） | 18:41:49 → 18:52:21 | **10.5 min** | — |
| 闸门全关 + 双缓存（冷首填） | 19:11:22 → 19:40:16 | **28.9 min** | 2.7× 慢 |
| 同命令复跑（缓存热） | 19:46:38 → 19:50:52 | **4.2 min** | 2.5× 快 |
| 窗C 闸门全开 + 双缓存（dataset 键 miss） | 12:35:13 → 13:35:02 | **59.8 min** | **5.7× 慢** |

- 缓存"变慢"的完整机理 = P2（首填写 95 万小文件）+ P3（键含闸门配置，配置一变全
  miss）+ P4（miss 后 16 worker 读小文件，NTFS 元数据争抢）+ **P1 未修的放大器**
  （训练脚本 kernels=16 仍在，见 N2）——四者叠加，只有「完全同配置复跑」这一种场景
  缓存是净赚（12.5s Loading / 4.2 min 端到端）。
- 结论落到操作纪律：Windows 上，确认要同配置复跑才开 `--expr-cache --dataset-cache`；
  单次实验、或闸门配置会变的消融矩阵，裸跑更快。根本解法见 N1（项目级单文件缓存）。

## 六、快速复现索引

```bash
# P1 探针（改 kernels 对比）
# P2/P3 四行对照：依次跑下列四条，取各自日志的 Loading data Done
cd MyQuant/my_scripts
export MLFLOW_DISABLE_AGENT_HINT=1 LOKY_MAX_CPU_COUNT=8
PY=/d/anaconda3/envs/vanna312/python.exe
$PY custom_train_backtest.py --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2026-01-01:2026-09-08 > p_nocache.log 2>&1
$PY custom_train_backtest.py --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2026-01-01:2026-09-08 --no-exclude-filter --no-limit-filter --no-limit-threshold --expr-cache --dataset-cache > p_cold.log 2>&1
$PY custom_train_backtest.py --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2026-01-01:2026-09-08 --no-exclude-filter --no-limit-filter --no-limit-threshold --expr-cache --dataset-cache > p_warm.log 2>&1
$PY custom_train_backtest.py --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2025-01-01:2025-12-31 --expr-cache --dataset-cache > p_winC.log 2>&1
```
