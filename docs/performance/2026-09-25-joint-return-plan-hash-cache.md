> 2026-09-25 从 Bot VM 性能研究导入，促成 PR “perf: enable plan-hash cache by default”。
> 两个 CLI 现默认启用 plan-hash cache；§落地顺序中显式传入 `--cache-plan-hash` 的命令等价于默认行为，`--no-cache-plan-hash` 选择慢速参考路径。
> 默认输出保留 `research_acceleration: TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW` 研究标记；两端均选择慢速参考路径时不新增该标记，已有上游标记仍保留。
> 以下测量与评审保留研究当时的表述，“默认”指当时的慢速参考路径；所有 `scratch/` 工件均在 Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/` 下，属于仓外工件，未入库。

**PR #197 性能评审与提速方案 · 2026-09-25**

结论：**应立即验证并启用 MQ 两端已有的 `--cache-plan-hash`，不应先做多进程重写，也不应等重生成达到“月级”才处理。** 默认路径在每个候选上重复序列化整份 plan，形成近似平方复杂度。本机 5 天 × 1,000 证券的 control_only 生成，普通计时中位数 **14.880 → 0.368 秒，40.44×**；整份生成产品相同。这个瓶颈来自重复工作，串行状态链没有阻止其消除。

**PR 建议修改后合入。** MQ 生成与 BT 回放属于不同耗时域的判断正确；“哈希/验证大头”在合成 profile 中得到支持，但应明确大头是重复 canonical JSON 编码，并非 SHA 算法。“全量实测 11–14h”“历史 7.2h 上界”“逐日审计彼此独立”“24 核可快 10–20×”“只能靠 NumPy/Rust”“月级前负 ROI”均需修正或降格为假设。本文没有 4090 的原始全量数据与运行日志，不把本机合成结果当成 4090 的完成回执。

两个主 checkout 保持只读；所有实验、复制的源码和产物均在原 Bot VM 报告旁的仓外 `scratch/`（未入库）。没有 push，没有运行交易栈。实验没有安装依赖。MQ 使用 `~/.venvs/mq-ci/bin/python`，BT 使用 `~/.venvs/bt-ci/bin/python`。

**证据范围与复现条件**

- 审查对象是提供的 pr197.diff（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/pr197.diff`，未入库）。主 BT checkout 尚无这篇新笔记；已从 diff 原样提取 scratch/pr197-note.md（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/pr197-note.md`，未入库），以下评审行号对应新文件。
- MQ：`b072cc3bef6f2a49af32de6c904ebf34256e55cc`；BT：`2f7937514c8d42769e02f8733c749e9b6bc966b1`。均在本次开始时 clean。
- 环境：Linux x86_64，CPython 3.12.14，Intel Xeon，8 个可见 CPU，cgroup CPU 配额 8 核、内存上限 16 GiB。不是 13900KF/Windows。团队内正式性能基准错开执行；宿主其他任务不可完全控制。单进程计时 CPU/wall 接近 1；不能据此声称整台宿主空闲。
- 输入源是仓库现有 data-free fixture。生成实验为 control_only、P-BASE、50/5、5 个显式合成 session、初始现金 1e8；每天排名轮转 7 只、参考价格略变，确保首日建仓后每天都有 5 卖/5 买，避免用“后四天空计划”夸大加速。100/300/1,000 证券三个尺度，每模式普通计时 3 次，报告中位数。构造输入、生成结果的比对哈希不计入生成耗时。
- `cProfile` 单独运行，只用来归因，不拿 profile wall 计算加速比。缓存路径普通计时 0.368s，而 profile 总计 1.131s，说明解释器函数较多时 profiler 开销不可忽略。

**真实生成与消费路径**

| 阶段 | 实际入口/函数 | 职责、依赖与成本 |
|---|---|---|
| B 时钟准备 | MQ `docs/reviews/joint-return-v1/intent-clock-4090-reexport.md` §2；`joint_return_contract.py:102 next_session_clocks` | 显式 execution calendar 推导下一 session available/effective/expiry；保留 market/decision/mark 输入，重登记来源/hash。不是训练、不是下载数据。 |
| C1 读入 | `my_scripts/joint_return_rule_intents.py:188 main`；`joint_return_freeze_snapshot.py:34 _read_json` | 读 scores/initial_state/sessions/metadata；JSON 解析拒绝重复键、BOM/NUL/非有限值，计算 raw/content hash，核对 URI 和来源。 |
| C1 排序与规划 | `joint_return_portfolio.py:37 score_days`；`joint_return_rule_intents.py:130 generate_plans`、`:71 make_rule_plan` | 校验分数与 PIT，按 `(-score,instrument)` 稳定排序；按日/arm 维护 holdings 与 holding_days；市场资格/参考价检查，TopK dropout，含费预算与整手数量、候选/lot 身份、session/scores/strategy/state hash。 |
| C1 状态折叠 | `joint_return_portfolio.py:288 _step`，由 rules 导入 | 再校验 plan/source/pre-state/时钟/候选；构建真实意图，递推参考现金/持仓/风险/换手；返回完整 before/after 历史。下一日依赖此 state；这是参考账，不接收 BT 实际成交反馈。 |
| 哈希热点 | `joint_return_portfolio.py:266 _intent`、`:340` 附近候选循环；`joint_return_contract.py:231/240/244` | 默认每个候选、卖单、选中买单都调用 `content_hash(plan)`；候选还构造一个立即丢弃的临时 intent，生成 ID 后 `validate_intents` 再算一次 ID。`content_hash` = canonical JSON + UTF-8 + SHA256。 |
| C1 写包 | `joint_return_rule_intents.py:234` 附近；`joint_return_merge_scores.py:118 write_bundle` | plans raw/content hash 分别编码；再编码 plans、metadata、rule-manifest，写新目录并回读比较。历史中的 `source_plan=deepcopy(plan)` 使同一大计划再次进入 rule-manifest。 |
| C2 freeze | `joint_return_freeze_snapshot.py:102 freeze_snapshot` | 核对 URI/双 hash，`validate_snapshot` 与 `_validate_sections` 检查；序列化完整 snapshot，独占创建、回读并再次验证。不是 portfolio 数值递推，也不是上游真实来源认证。 |
| C3 审计与意图 | `joint_return_portfolio.py:481 run_snapshot` → `:439 build_portfolio` | `load_snapshot` 后再验 snapshot、再次分组 scores；按日/arm 重跑 `_step` 的状态链、约束、意图和符号映射检查。full 模式另跑 P-REF；本次 control_only 不跑 P-REF。**C3 不是一组独立的逐日哈希。** |
| C3 输出 | `run_snapshot` | 写 `intents.csv`、`constraints.csv`、`pref_check.json`、`manifest.json`；标量 JSON 嵌入 CSV，无损保留类型；manifest 又含完整 reference_states/source_plan。 |
| BT 消费/回放 | `backtest/research/joint_return_replay.py:364 validate_manifest`、`:512 load_bundle`、`:1267 replay`、`:1359 run_replay` | 核对冻结合同、伴随文件、intent/hash/参考状态链/plan 绑定，然后按 M-REF/M-LAG 回放。BT 已在每个 reference plan 上算一次 hash；不能把 MQ 每候选重复哈希的问题归给 BT 撮合核。 |

所有 MQ 路径均相对于本仓库根目录，BT 路径相对于独立的 BT 仓库 `MyQuant-backtrader` 根目录（不在本仓库）。`load_json_bytes` 还会在 parse 后重新 canonicalize 以拒绝 NaN/Infinity；`validate_snapshot` 对每个 section 复算 content hash。缓存之后，这些整包扫描、deepcopy 与重复嵌入成为下一轮目标。

**复杂度与并行性判定**

设某日候选数为 C、已选买/卖数为 B/S、plan 大小为 P（候选多时 P≈O(C)）。默认 `_step` 的整 plan 哈希成本约为 `(C+B+S)×P`，即 O(C²)；cache 路径每个非空 step 算一次，降为 O(P)，其余逐候选资格验证继续完整执行。本机 1,000 证券样本的 5 天合计候选 4,800、选中买 70、卖 20，**整 plan 哈希从 4,890 次降到 5 次**。这不是“省略审计”。

同一 arm 的未知状态不能简单“一天一个进程”。但可在状态链外处理 scores/market 静态检查与排序，full 模式的独立 arms 可并行，生成好的 immutable plan 可以分块做纯验证。若使用 checkpoint 分段，必须证明起始 state/holding_days/累计身份与串行结果相同，并核验每段接缝；改变较早输入通常会使后续状态与 lot 身份全部失效。本次只有一个 P-BASE，arm 并行没有收益。

portfolio 若要分块，应把独立的结构/字段/hash 检查与参考现金持仓递推分开。直接相信被审计包自带的 before-state 后独立跑每一天，会削弱链连续性证明；需要校验初态、相邻 before/after 与全局唯一性、顺序及聚合约束。并行报错应按原始 day/arm/row 顺序稳定归并。

**实测一：现有 plan cache，先消掉平方项**

原型驱动与原始数据：bench_rule.py（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/bench_rule.py`，未入库）、results.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/results.json`，未入库）、普通计时日志（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/run.log`，未入库）。使用实际仓库实现，不替换算法、不更改排序或浮点数。

| 5 天证券数 | 默认生成中位秒 | cache 中位秒 | 加速比 | 5 天候选数 |
|---:|---:|---:|---:|---|
| 100 | 0.18165 | 0.03850 | 4.72× | 100/50/50/50/50 |
| 300 | 1.28930 | 0.11213 | 11.50× | 300/250/250/250/250 |
| 1,000 | 14.88004 | 0.36792 | 40.44× | 1,000/950/950/950/950 |

1,000 规模普通计时范围：默认 14.805–15.174s，cache 0.358–0.378s；CPU/wall≈1。300→1,000 证券池规模增约 3.33 倍（总候选为1,300→4,800，约3.69倍），默认耗时增 11.54 倍，而 cache 增 3.28 倍，支持“平方项→近似线性”的代码推导。全部重复的 canonical 完整 product（plans、reference_states、final_states、scope）一致；不是只比输出文件大小。

1,000 规模 `cProfile` 归因如下。表为不重叠的 self-time 桶，避免把 `_step`、`_intent`、`content_hash` 的嵌套 cumulative 时间加在一起：

| 类别 | 默认占比 | cache 占比 |
|---|---:|---:|
| JSON 编解码 | 84.12% | 15.44% |
| SHA256 原生计算/hex | 8.97% | 2.40% |
| deepcopy | 1.29% | 17.88% |
| 时钟解析 | 0.62% | 8.42% |
| 合同模块其他 Python 工作 | 1.80% | 21.02% |
| portfolio Python 工作 | 0.49% | 5.54% |
| rule Python 工作 | 0.21% | 4.58% |
| 其余内建/运行时 | 2.50% | 24.73% |

默认 `content_hash` 累计 14.698/15.618s≈94.11%，`make_rule_plan` 累计仅 0.131s。cache 后 `content_hash` 累计 0.257/1.131s≈22.67%，包含小型身份/state/scores 哈希，并非全是可并行的 plan hash。原始 profile：reference（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/rule-1000-False.txt`，未入库）、cache（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/rule-1000-True.txt`，未入库），同名 `.prof` 可用 pstats 检查调用图。profile 与普通计时分开解释。

已有 MQ [Track B 说明](../reviews/joint-return-v1/track-b/README.md) 早已写明**两个 CLI 都要加开关**，且记录过 80 证券 Linux fixture 的 2.79×/4.79× combined 收益。PR 的“未实测”只能表示“4090 全量未实测”，不能表示此前没有任何实验。

**实测二：分块并行哈希并不是第一刀**

原型（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/parallel/benchmark_parallel.py`，未入库）、原始数据（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/parallel/results.json`，未入库）、详细解释（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/parallel/findings.md`，未入库）。96 个独立的真实 plan 结构 × 每个 2,500 候选，canonical JSON 合计 114.65 MB。每个 plan 只哈希一次，每块 4 plans；显式 spawn，3 次普通计时中位数，含进程启动/import/pickle/IPC/归并/退出，排除输入构造。

| 模式 | wall 秒 | 总 CPU 秒（含子进程） | 加速 |
|---|---:|---:|---:|
| 串行 | 0.5920 | 0.5920 | 1.00× |
| 2 进程 | 0.5271 | 1.2446 | 1.12× |
| 4 进程 | 0.3785 | 1.4297 | 1.56× |
| 8 进程 | 0.4086 | 1.7877 | 1.45× |
| 4 线程 | 0.5781 | 0.6324 | 1.02× |

逐 plan 哈希全部一致。独立的分阶段试验中 JSON 编码约 91.5%、SHA 约 8.5%；分阶段保留 bytes 列表，内存行为不同，不能将其绝对耗时直接代替上表。4 进程 parent CPU≈0.26s，接近 0.38s 墙钟，说明串行 pickle/供给已限制收益。Windows spawn 行为、P/E 核调度与内存峰值仍须在宿主测试；本实验不是 Windows 性能承诺。不要把 657MB JSON 展开的整棵 Python 对象发给每个 worker。

“GIL 所以多线程无用”过于绝对：大块输入的 hashlib 会释放 GIL，见 [Python 3.12 官方文档](https://docs.python.org/3.12/library/hashlib.html)。本热点的线程收益接近噪声，是因为 JSON 编码主导。并行逐 plan 摘要可保摘要；**拼接分块 SHA 不能替代完整 canonical 数组的 SHA**。保原身份须最终流式散列原规范字节；改摘要树则要版本化合同与下游验证。

**实测三：缓存之后，候选验证与时钟解析原型**

prototype.py（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/mq-audit/prototype.py`，未入库） 仅在 scratch 运行上下文内替换候选路径，退出恢复原函数：对 `BUY/VALIDATE_CANDIDATE` 直接验证 frozen order，不生成随后丢弃的完整 intent，不做其两次自哈希；所有候选仍验字段、身份、PIT、单位、正价/正量、有限值、权重和 100 股整手。原 `_step` 继续负责 eligibility、重复候选、持仓/score 关系、plan/state/source/时钟和风险门禁；实际发出的买卖意图仍走原 `_intent` 与最终整体校验。另一部分是每次 build 内、最多 4,096 项的 timestamp 缓存，异常不缓存、非字符串仍调用原检查。

| 5 天 portfolio build，普通计时中位秒 | 默认 | plan cache | cache+时钟缓存 | cache+直接候选验证 | 两项组合 |
|---|---:|---:|---:|---:|---:|
| full，1,000 证券、双臂 | 16.15484 | 0.47581 | 0.37010 | 0.29507 | 0.21310 |
| control_only，1,000 证券、每日轮转 | 本组未重复默认 | 0.33669 | 0.27060 | 0.17755 | 0.14393 |

另把同一原型作用于共用 `_step` 的 C1：1,000证券×5天，3次交替普通计时，cache **0.38391s → direct_memo 0.19111s，2.01×**；完整生成产品摘要一致且输入未改变。见 生成验证脚本（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/bench_candidate_generation.py`，未入库） 与结果（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/bench_candidate_generation.json`，未入库）。这组是独立追加测量，不能拿不同批次的中位数作精确连乘。

full cache 对默认 **33.95×**；组合对 cache **2.23×**、对默认 **75.81×**。control_only 组合对 cache **2.34×**。这些是 build API 耗时，包含 snapshot 验证与分数整理，排除文件 I/O；不能直接当整包加速。full 输入为静态分数、P-BASE 首日后无买入槽，P-CHASE 仍换仓；control_only 是持续轮转。两组不可不注明输入差异就相乘。

full 的 build profile 默认 `_step` 占 97.61%、score_days 1.98%、snapshot 检查 0.18%、P-REF 0.17%；cache 后对应 66.89%/28.01%/2.18%/2.17%。组合后 deepcopy 累计占约 49.18%，主要是分数逐行复制与 state_record 的整 plan 复制。**优化后的瓶颈已经改变，应先研究不可变数据所有权与去复制，再决定是否改语言。** 这些仍是 profile 比例，不是无 profiler 的精确 Amdahl 参数。

validation.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/mq-audit/validation.json`，未入库） 中 **54 组差分通过**：6 组 full/control_only × 10/3、20/3、50/5 完整 products 字节相同且输入不变；44 组未入选候选失效字段均拒绝、status 一致；4 组合法额外字段/数值边界一致。多处错误同时存在时的第一条错误文本没有证明一致。生产化应提炼共享 `validate_frozen_order`，让候选与实际意图共用规则，避免长期复制 validator。原型与明细：findings（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/mq-audit/findings.md`，未入库）、summary（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/mq-audit/summary.json`，未入库）、各 `.prof/.profile.txt`。

**完整磁盘链路的阶段账与外推**

另以 300 证券 × 5 天做 3 轮交替 reference/cache 的 `rule main → freeze_snapshot → run_snapshot`，每次全新 immutable 输出目录，包含读入、校验、JSON/CSV、写入和回读；输入 fixture 构造、进程启动和 B 时钟准备不计时。不是绕过 CLI 验证的内存计时。缓存开关两端同时启用，freeze 原样保留。

| 阶段 | 默认平均秒 / 占比 | cache 平均秒 / 占比 |
|---|---:|---:|
| C1 rule（含读写） | 1.31438 / 49.85% | 0.14767 / 38.04% |
| C2 freeze（含读写/回读） | 0.08455 / 3.21% | 0.08654 / 22.29% |
| C3 portfolio（含读写） | 1.23764 / 46.94% | 0.15396 / 39.66% |
| 平均合计 | 2.63657 | 0.38818 |

整条链**总时中位数 2.63101 → 0.38912s，6.76×**；三次范围分别 2.612–2.666s、0.369–0.406s。表内为平均值方便阶段占比相加，整链加速使用总时中位数。生成+build 的内部计算占整链从 93.84% 降到 56.50%；其余读入/整包校验/编码/回读等由约 0.162s 基本不变为约 0.169s，缓存后成为 43.50%。**不能把计算核的 40×当所有输入规模下端到端的 40×。**

粗阶段明细中位数：rule 输入读/parse/hash 约 0.014s，rule bundle 编码/写/回读约 0.011s；portfolio load/validate 约 0.026s；freeze 约 0.087s，含多次 parse/canonical/hash。不能把这些复合阶段统称“磁盘 I/O”；本机文件约 MB 级且热页缓存，未测 fsync 或 657MB 大包的 cold I/O。生产需补磁盘吞吐、峰值 RSS/Windows private bytes、GC 与大对象复制。原始数据：pipeline-repeats/results.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/pipeline-repeats/results.json`，未入库）。

外推分两种，均为**条件演算**：

- 对同类轮转输入，`T_ref(D,C)≈14.880×(D/5)×(C/1000)²`，`T_cache(D,C)≈0.36792×(D/5)×(C/1000)` 秒，适用于候选量足够大时的生成计算部分。假设 D=243、C=5,000，则为约 **5.02h → 89s**。C=5,000 只是现有 Track B 文档提出、尚未在本机全量核实的假设；本模型未覆盖整包读写、内存阈值、Windows、P/E 核和真实候选分布。它解释“为何能出现数小时”，不是承诺全流程 89 秒。
- 用较保守的已测 1,000 规模倍率做预算例：笔记 C1 381min/40.44≈9.4min，C3 的运行中下界 286min/33.95≈8.4min、历史 432min/33.95≈12.7min，再加 B/C2 约 5min，得到 **约 23–27min 的试跑目标**。这不是置信区间或 4090 预测，C3 也尚无此次完成值；其中 I/O 本不该被同比缩放，真实目标必须由宿主 5/20 日测量校准。

宿主外推应记录每日 `(候选数C、plan规范字节P、intent数、plain wall、CPU、RSS)`，拟合默认 `aΣ(C×P)+bΣC+c×文件字节` 与优化 `a'ΣP+b'ΣC+c'×文件字节`；用第一段 5 日拟合、后续 20 日核验误差，再预测 243 日。保持真实 calendar/下一 session，连续段从初态开始或使用审定 checkpoint。不能对“2470条最终意图”按行线性外推数百万未选候选的工作。

**下游回放正确性：已做与未做**

reference 与 cache 分别运行完整 MQ 生成/freeze/portfolio 管线；第三份包复用 cache 的已冻结 snapshot，仅把 portfolio 切到 direct_memo。三份包随后调用未修改的 BT `load_bundle` 与 `replay`，M-REF/M-LAG 两模式。数据是 **300 证券 × 5 天、1,500 个 score、90 个 intent、70 个实际涉及证券、1,750 根显式合成 bar**；bar 容量 100,000 股，约 190,000 股订单会分批成交，共 245 fills。比较器保留行序，不先排序掩盖身份变更导致的执行先后变化。

| 对比项 | 本次结果 |
|---|---|
| 分数原值与每日 `(-score,instrument)` 完整排名 | 全部一致 |
| frozen intents、constraints、初态、reference_states | 语义逐字段一致；业务产品/意图摘要也一致 |
| orders 状态、逐笔 fills 数量/价格/费用/现金、daily NAV/持仓 | 全部一致，不使用数值容差或舍入 |
| M-REF | NAV 1e8 → 100392444.99999999；净收益 0.0039244499999999015；换手 0.7821433203474197 |
| M-LAG | NAV 1e8 → 100293151.99999999；净收益 0.0029315199999999215；换手 0.7832226245214144 |

回执：wire-replay-result.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-replay-result.json`，未入库）；可复用比较器：replay_compare.py（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/replay_compare.py`，未入库）；完整生成脚本：generate_wire_replay.py（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/generate_wire_replay.py`，未入库）。这些收益只为验证等价，不是策略收益证据。合成费用为零、尾日 next-session 超出五天回放窗口，三方案均保留相同未成交意图；全量验收必须覆盖真实非零费、尾 session、涨跌停/T+1/缺 bar 等边界，不能用此替代真实市场验收。

同时做了比较器正负对照：CSV quoting 改变导致字节不同，但合法重登记后回放等价；另一组合法重 seal 的 bar 价格 11→12，被比较器检测出逐笔成交、NAV 和 summary 差异，即使某个最终净收益仍为零也不会漏掉。见 selftest-result.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/selftest-result.json`，未入库）。

差异来源必须明确登记：

- cache CLI 新增 `research_acceleration: TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW`；不同输出目录改变 URI/run 身份，metadata/snapshot/manifest 哈希因此不同。这些不是 score、plan 业务字段、数量、现金或成交规则漂移。不能为了 byte-diff 通过而删研究标记。
- 通用比较器仅在双方通过官方 validator 后，剔除/映射列出的 hash/intent/order/run 身份；真实项目改 hash/格式时必须另交身份变化表。本次核心 intent hash 仍相同，业务输出没有数值差异。
- **发现跨平台合同身份问题**：MQ `contract_hash()` 对合同文档原始字节取 SHA；Linux LF 为 `fce3d6ab…`，相同文本转 CRLF 恰为 BT 锁定的 `c6b85b9b…`。为模拟 4090，本实验只在 `scratch/bt-review/mq-wire/` 复制必要 MQ 模块，并将合同副本转 CRLF；未改主仓、未改 BT 常量、未绕过校验。记录见 wire-identity.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-identity.json`，未入库）。这说明改 pack 格式/合同 canonicalization 也要明确迁移，不能静默规范化换行。
- 回放包是 frozen 格式的合成数据。M-REF 验证器要求的 `source_kind=lake_bar` 只是该测试中的格式标签；实际 source 明写 `synthetic://fixture-only-not-market-lake`，没有真实湖来源认证。真实准入状态不因这些功能测试解除。

身份审计另见 wire-identity-audit.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-identity-audit.json`，未入库）：reference/cache manifest 恰有 13 处差异，全部由 8 处 URI、2 个源 metadata seal、1 个现有加速标记、2 个 snapshot seal 解释，未知差异为零；cache/direct_memo manifest 原值完全相同。三者 intents/constraints/pref 字节相同，两个完整生成目录的 plans/scores/initial_state/sessions 字节相同。当前比较器的重新验证见 recheck_existing.py（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/recheck_existing.py`，未入库） 与 selftest-current-result.json（仓外工件，Bot VM `/home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/selftest-current-result.json`，未入库）。

**候选方案比较**

收益都标明测量范围。未测项目给的是设计目标或上界分析，不是假装已有速度结果；工程量为熟悉此代码的单人实现/评审估计，不含宿主等待。

| 方案 | 预期/实测收益 | 改动量 | 主要风险与正确性影响 | 验证方法 |
|---|---|---|---|---|
| 两端 step-local plan hash cache | 实测 C1 4.72–40.44×，C3 full1000 33.95×，300规模磁盘链6.76× | 已有开关；接入与证据整理约0.5–1日 | plan 在本 step 中必须只读；不可做跨日 object-id 缓存。只新增研究标记/路径 seal，不改意图身份 | 原有 cache 差分测试 + 相同真实输入小窗/全量回放 |
| 候选直接验证 + run-local 时钟缓存 | 实测 C1在cache上再2.01×，C3再2.23–2.34× | 原型约60行；共享validator生产化与测试约1–2日 | 不能漏未选候选、边界时钟或隐式异常；长期维护两份validator会漂移 | 已有54组 + 下游三包比对；生产补多重错误、非零fee、持仓/资格边界 |
| 去 score/plan deepcopy、复用不可变对象 | 尚未测；以原型后约49% deepcopy profile估算，若这部分快4×，build可能约1.6×，不是端到端承诺 | 约1–3日，需定义数据所有权 | 上游修改共享dict会改变冻结产物；必须不可变表示或明确只读生命周期，不能简单删除所有复制 | 输入修改隔离、输出对象别名/变异测试，完整语义回放、峰值内存 |
| 流式/去重复 pack、按日分片、压缩或列式候选 | 未测；目标是减少大文件parse/encode和内存。若整链中这部分占40%、该部分快2×，整链仅约1.25× | 约3–5日或更多，MQ/BT格式迁移 | 顺序、float/int/NaN/空值、未知字段、hash与意图ID排序、旧消费者兼容；改字节允许，来源须可解释 | 新旧reader对同语义包；独立seal/顺序/错误输入；完整成交/NAV/分数回放 |
| 已去重哈希/纯验证分块多进程 | 本原型2/4/8进程1.12/1.56/1.45×，仅hash阶段；整体通常更小 | 原型几十行；接入、Windows内存与错误归并约2–4日 | pickle/IPC、worker重复加载、内存爆炸、顺序/第一错误不确定；整包SHA不能拼分块摘要 | 逐plan摘要一致 + 2/4/8核和块大小曲线 + 总CPU/RSS + 重跑回放 |
| NumPy/Numba重写TopK/数量/数值核 | 未测，暂不预订收益；先用plain sampling证明该核占比。若仅占10%，即使无限快也最多1.11× | 数值核约1–3日，输入列化另计 | 稳定ties、NaN/缺失held、floor整手、sum/fsum与fastmath、fee/cash边界改变 | tie/边界手算 + 禁fastmath起步 + 持仓/现金逐日对账 + 回放 |
| Rust/PyO3解析/验证/规划核 | 未测；只换SHA预计收益低，需迁移已确认的扫描/复制/JSON热点；目标先要求缓存后整链≥1.2× | 约数日到1–2周，跨平台构建额外 | JSON与Python浮点规范、字符串/时区、异常类别、边界排序、ABI；语言迁移不会自动去掉C² | 跨语言属性差分、fuzz、相同score/rank/qty、完整BT回放；编译/JIT冷启动单列 |
| checkpoint与内容寻址增量缓存 | 追加少量日期时计算量可近似剩余天数；例如243天仅新增1天可省约242天计算，非保证243×整链 | 约2–4日，需缓存身份与恢复协议 | 早期score/时钟/策略/费用/合同改变可能使整个后缀失效；不能复用旧hash冒充新全量生成 | cold全重建 vs warm增量语义回放，破坏缓存/错版本fail-closed，分段接缝验证 |

缓存键必须包括来源数据内容、calendar/时钟规则、strategy/fees、初态/holding_days、规范化/算法版本及相关代码身份。追加日期并非永远独立：原尾日的 next-session 身份或可用时间改变时，尾段也必须失效。本轮合同/时钟变更按现有交接要求全量重新登记；增量只能在边界证实后作为新的实现方式，不能靠修旧 CSV 代替重生成。

**第一刀到第三刀的落地顺序**

1. **第一刀：MQ 两端启用已有 cache，保持原策略与状态链。** 从成功线登记的 carryforward scores、初态、显式 sessions/完整富 metadata 出发，新建输出目录。C1 与 C3 均加 `--cache-plan-hash`，C2 保持原实现。先用同一连续5/20日子集对照默认/缓存，记录C/P/CPU/wall/RSS、全部差异，再用本次完整参考产物作全量基线。已有同输入完整慢包可直接复用为只读基线，无需“为了验证必须再等13h”。目前加速标记仍是 pending review，应保留，不能因此冒称 Mode B ready。
2. **第二刀：提炼共同候选字段校验 + 有界时钟解析缓存。** 以本报告 prototype 为起点，保留真正意图的ID/hash与验收路径；把字段合法性从临时意图构建中剥离。C1/C3的合成差分均已验证；生产化时保留两端独立验收。目标是缓存后build再快约2×、输入错误检测不减，且完整回放无经济/分数差异。按新profile决定是否同批处理只读score/plan复制。
3. **第三刀：依据缓存后全量 profile 处理数据表示与 I/O。** 优先不可变对象复用，接着把重复嵌在rule-manifest/snapshot/portfolio-manifest的大 plan 改成一次存储+可校验引用，按日/arm分片或流式读写。以旧格式适配器导出保持渐进接入，阶段性比较所有seal与回放。仅当纯验证/编码仍是主导且IPC占比可控时引入常驻进程池；Rust/Numba只承接已经证明值得迁移的内核。验收同时看墙钟、总CPU与峰值内存，不能只看“多核都亮了”。

宿主执行时，沿用已核实变量，命令的实质变化只有 C1/C3 的开关；以下列出完整参数形状，不虚构本机不存在的真实数据路径。`$FreezeMetadata` 必须由成功线的富字段 metadata 合成，并重新登记新 plans 的 URI/raw/content hashes 与研究加速标记；不能直接使用历史失败的瘦 metadata。

```powershell
& $Py -m my_scripts.joint_return_rule_intents --scores $Scores --initial-state $Initial --sessions "$Out\sessions.json" --metadata "$Out\metadata.json" --arms P-BASE --topk 50 --n-drop 5 --output-dir "$Out\rules" --cache-plan-hash
if ($LASTEXITCODE -ne 0) { throw 'rule failed' }
& $Py -m my_scripts.joint_return_freeze_snapshot --scores $Scores --initial-state $Initial --plans "$Out\rules\plans.json" --metadata $FreezeMetadata --output "$Out\snapshot.json"
if ($LASTEXITCODE -ne 0) { throw 'freeze failed' }
& $Py -m my_scripts.joint_return_portfolio --snapshot "$Out\snapshot.json" --run-id joint-return-control-only-50-5-cache-review --output-root "$Out\portfolio" --cache-plan-hash
if ($LASTEXITCODE -ne 0) { throw 'portfolio failed' }
```

正式全量回放门槛：先证明两包 scores 每日原值/排名、宇宙、初态、fees、clock/calendar、bars/marks/seals一致，且来源均合法登记；再逐日比较plan/constraints/reference state，逐事件比较orders/fills/费用/现金/持仓，逐日比较NAV/收益/回撤/换手，逐月/全窗summary也比。必须覆盖非零费用、涨跌停、停牌、T+1、部分成交、到期、旧仓残量、拒绝调出、同分排序、缺score/行情与尾session。若改身份或格式，列出旧→新身份映射与原因，保留执行事件顺序，防止ID改变影响有限现金/容量分配。

按既有任务链先做全量约束与2470意图门，再按批准的相同规则收窄614/1891，P-BASE M-LAG对同窗4475 fills研究基线逐笔核对；随后M-REF/M-LAG与cash 1e8/1e9、Mode B真实lake marks。4475只是查错锚点，不是“总数一样即通过”。经济字段任何差异定位最早日期/证券/事件，解释是修正错误、浮点、执行顺序还是数据变化；不能混入“格式变化”白名单。未解释差异或缺真实PIT/尾日数据则不作全量验收通过结论。

**PR #197 逐条评审意见**

| 位置（新笔记行号） | 判断 | 建议改写/补证 |
|---|---|---|
| L11、L22–23：实测11–14h、portfolio≤7.2h、合计上界 | P2，证据类型混用 | “C1完成6h21m，C3截至07:29已运行至少4h46m；总耗时预估约11–14h，最终值待回执”。历史7.2h不是本次上界；附原始日志、PID/开始结束时点与输入身份。 |
| L25：13h仅占1核、其他23核闲置；L11纯Python | P2，推论过度 | CPU/wall≈1只能支持平均约1个逻辑核；系统其他核是否空闲需系统级记录。代码由Python驱动，JSON/hash有原生实现。 |
| L46：状态链不可朴素并行，但只能NumPy/Rust | 前半成立，后半P2 | 保留串行因果约束；列出消冗余、缓存、只读预处理、独立arm等可行加速。无需先重写规划核。 |
| L47：portfolio逐日审计彼此独立 | P2，错误描述实际代码 | 它再次递推state；明确纯检查/状态递推边界与全局门禁，不能直接日并行。 |
| L47、L56：24核压到1/10–1/20、整体5–20× | P2，未证实数字 | 标注待测假设并写Amdahl/IPC/RSS限制；现prototype一次哈希4进程仅1.56×，不能保证整链同倍。先做O(C²)→O(C)更有效。 |
| L48：线程无用 | P2，绝对表述不成立 | 改为“当前JSON主导路径线程无显著实测收益”；引用hashlib释放GIL条件，原生扩展另测。 |
| L54：仅rule开关、未实测、只比plans字节 | P2，遗漏现有能力与证据 | 补portfolio同开关和MQ Track B基准；“4090全量未测”。比较下游成交/NAV/分数及约束，允许并说明研究标记/URI身份差异。 |
| L59：月级前不开刀、负ROI | P2，结论证据不足 | 不把现成开关验证与数天重写混为同一成本。用真实试跑节省/工程工时/重试及人员等待决定后续投入；第一刀现在就值得测。 |
| L12、L31–40：回放优化与生成是不同域 | 保留 | 代码边界支持该结论；本次未复跑4090的789→237.6s，也未验证“每包几十次”频率。文档应区分已登记回放回执与此次生成观察。 |
| L66–71：富metadata、URI精确匹配、成功线scores来源 | 保留流程教训 | URI严格匹配由freeze源码证实；具体失败次数、成功输入和撞车损失仍来自作者回执，本地无原始4090日志可独立核实。 |

建议将结论改为：“慢路径主要嫌疑是每候选重复canonical plan哈希；本机大候选合成profile已验证。先对rule和portfolio同时启用现有cache做真实输入对照；状态链保持串行。全量时间、并行收益和ROI待完成回执及宿主plain测量，暂不写硬上界或月级禁做条件。”

**交付与复现**

主要产物均保留脚本、原始计时、JSON、profile及说明；以下位置均为原 Bot VM 报告目录下的仓外工件，未入库：

| 位置 | 内容 |
|---|---|
| `scratch/rule/` | 三尺度生成、cProfile、完整disk链重复试验、生成与输出hash |
| `scratch/mq-audit/` | 候选/时钟原型、54组差分、三个规模/模式的普通计时及profile |
| `scratch/parallel/` | spawn/threads哈希原型、含IPC/子进程CPU的逐次结果 |
| `scratch/bt-review/` | 三包、显式合成bars、比较器、正负对照、身份差异表、合同CRLF副本 |
| `scratch/mq-tests.log` | MQ原有定向回归：**248 passed in 14.18s** |

BT 相关既有回归 **448 passed、63 skipped**；跳过项来自本机缺少三个历史 handoff oracle 文件，不能把它们算成覆盖。此次没有改BT执行核。54组原型差分、三包BT回放、比较器正负对照均通过；4090真实全量运行仍未执行。

以下脚本与输入/输出路径均为 Bot VM 上的仓外工件，脚本未提交到本仓库。

下面命令在本机可复现核心结果；生成基准必须指定**新的**输出目录，避免覆盖已经封存的包。第一个命令运行约一分钟量级，后两个只读比较现有包。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/box/.venvs/mq-ci/bin/python \
  /home/box/agent-data/pr197-perf-2026-09-25/scratch/rule/bench_rule.py \
  --out-dir /home/box/agent-data/pr197-perf-2026-09-25/scratch/reproduce-rule-new \
  --sizes 100 300 1000 --repeats 3 --profile-n 1000 --pipeline-n 300

PYTHONDONTWRITEBYTECODE=1 /home/box/.venvs/bt-ci/bin/python \
  /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/replay_compare.py \
  --baseline-intents /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-False/portfolio/synthetic-wire-300 \
  --candidate-intents /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-direct_memo/portfolio/synthetic-wire-300 \
  --baseline-bars /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-bars.json \
  --candidate-bars /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-bars.json \
  --baseline-scores /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-False/scores.json \
  --candidate-scores /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/wire-True/scores.json \
  --fill-mode all \
  --out /home/box/agent-data/pr197-perf-2026-09-25/scratch/replay-reproduce.json

PYTHONDONTWRITEBYTECODE=1 /home/box/.venvs/bt-ci/bin/python \
  /home/box/agent-data/pr197-perf-2026-09-25/scratch/bt-review/recheck_existing.py
```

MQ审计/并行原型的完整复现参数在各自 `findings.md`。所有新增 `.py/.md` 均按 UTF-8 无 BOM 编写并检查 NUL=0。本文提出的是可审查的后续落地方案；未修改两主 checkout、未提交/推送、未解除真实研究数据的准入状态。


## Full-data A/B gate

Merge of this default flip is gated on a full-data content-hash A/B on the 4090 machine, to be reported before merge. Use the same inputs with the cache on (the new CLI default) and compare against the existing slow-path products: `plans.json` content hash `e56994d8...`, snapshot `8a2854d8...`, and the portfolio pack `intents.csv` / `constraints.csv` / `pref_check.json` / `manifest.json`. The Bot VM synthetic measurements above do not complete this gate.

Expected differences are the `research_acceleration: TRACK_B_PLAN_HASH_CACHE_PENDING_REVIEW` stamp in rules `metadata.json`, snapshot metadata, and portfolio manifest metadata; output-path URIs (`metadata.inputs.plans.uri` and dependents) and the raw/content seals that embed them; `run_id` in the portfolio manifest; and the snapshot source seal. Preserve and explain these differences.

Required equal: `plans.json` bytes and content hash; `reference_states` / `final_states`; `intents.csv`, `constraints.csv`, and `pref_check.json` bytes; and `intent_hash` / `arm_intent_hashes`. Report all differences and the gate result before merge. Scratch prototypes remain off-repo and are not part of this change.
