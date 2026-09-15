# kimi R1 · 缓存层（b）+ 内存/OOM（e）

> 工程性能 brainstorm，非收益。锚定 HOST §2（#43 handler-cache / expr·dataset-cache / 禁 fetch→parquet）与仓内 `qlib_scripts/task_utils.py::replace_task_handler_with_cache`、`my_scripts/custom_train_backtest.py` handler_init 量级。

---

## 卡 1 · handler-cache digest 键扩面 + HIT/MISS 可观测

**标题**：handler-cache digest 键扩面（gate/窗/filter_pipe/自定义算子）+ 强制 HIT/MISS 日志

**本仓锚点**：HOST #43「同配置 HIT、改 gate/窗 MISS」；`qlib_scripts/task_utils.py` `replace_task_handler_with_cache` 现用 `hash_args(handler)` → `{class}.{hash[:10]}.pkl`；生产路径 `my_scripts/custom_train_backtest.py` handler_init 历史 ~18 min / ~907s。现状一句：键已能挡粗配置漂移，但可观测性与「正确性相关旋钮是否全部入 hash」未写死到训练入口。

**提案**（缓存级 + 纪律级）：
1. 明确 digest 必须覆盖：instruments/起止窗、learn/infer processors、filter_pipe / DropLimitUp / float_cap / CYQ·MA 等 gate、自定义 ops 模块版本指纹、label 定义。
2. 训练/导出入口在 `--handler-cache` 路径打印一行：`HANDLER_CACHE HIT|MISS key=… path=… size_mb=…`；MISS 原因码（键不存在 / 键变 / 文件损坏）。
3. 冒烟：同配置二次跑必须 HIT；单改 gate 或窗必须 MISS（冻结检查可自动化）。

**收益**：砍的是「脏 HIT 导致白训」与「以为 HIT 实际 MISS 再付 ~15–18 min init」的排查墙钟；同配置重跑把 handler_init 从分钟级压到 pickle 加载秒级（HOST 已证路径）。

**成本与风险**：hash 过宽 → 假 MISS、磁盘胀；hash 过窄 → 脏读（正确性事故）。Win 路径分隔与 `file://` 规范化要统一，否则同机 HIT 变 MISS。

**冻结检查**：
- 同 argv 二次：日志 HIT，handler_init 墙钟 ≪ 首次。
- 只改 `--float-cap` / 回测窗一端：必须 MISS。
- 不改 topk/过滤默认（收益纪律另册）。

**对抗预填**：
- 「hash 截断 10 字符会撞」→ 保留全长 hex 文件名或加短校验后缀；登记碰撞率监控即可，不阻塞采纳。
- 「再引入 fetch→parquet 做对照更快」→ **否决**（HOST 硬纪律 4，已有 OOM 先例）。

**建议裁决**：裁剪后采纳（先落地 HIT/MISS 日志 + 键清单文档化；全量键扩面与单测合批进下一片，勿一片一跑耗死）。

**重提条件**：若生产日志出现「配置已变但仍 HIT」或「同配置连续 MISS」，立即升级为必做。

---

## 卡 2 · 缓存分层协议：handler 主缓存 vs expr/dataset 辅缓存

**标题**：统一失效协议——gate/窗变只信 handler-cache；expr/dataset-cache 降级为同配置 Win 热重启辅层

**本仓锚点**：HOST「`--expr-cache --dataset-cache` 仅同配置 Win 重跑；gate/窗变优先 handler-cache」；`qlib_scripts/qlib_14.py` 曾试验 `DiskExpressionCache` / `DiskDatasetCache`（注释掉、易踩坑）；#43 主路径是 `to_pickle(dump_all=True)` 单文件。

**提案**（缓存级 + 调度级）：
1. 写死优先级：正确性相关旋钮变化 → **只用** handler-cache 失效；禁止指望 expr/dataset 层自动跟着变。
2. 辅层适用面收窄：同一 Win 会话、同一 digest、kernels=1 的「崩了重跑 / mlflow 逃生后再训」；并在 CLI help 写明。
3. 数据 bin 刷新（`refresh_mydata` / dump_all(8) swap）后：提供一键 `--cache-purge` 或按 qlib_dir inode/mtime 指纹使 handler+expr+dataset 全层 MISS（脏标记）。

**收益**：减少「开了三层缓存却因失效语义不清白付整轮 init」；sweep/重跑场景把「同配置二次」稳定压到加载级；避免错误依赖辅层导致静默脏特征。

**成本与风险**：purge 过猛 → 磁盘与首次墙钟回退；指纹若只看 mtime 可能假 MISS。Win spawn 下多进程同时写同 cache 目录需互斥（文件锁或原子 rename）。

**冻结检查**：改 gate 后即使 `--expr-cache` 开着，特征/样本数必须与冷启动一致（对拍一小窗）。bin swap 后无 purge 不得 HIT。

**对抗预填**：
- 「全部合成一个超级缓存」→ 否决过度设计；分层 + 明确优先级更可证伪。
- 「Linux CI 也默认开 dataset-cache」→ 裁剪：CI 只烟测 HIT/MISS 逻辑，真体积与 Win 路径留宿主。

**建议裁决**：采纳（协议与 purge/指纹；不在本轮改产品默认开哪些 cache）。

**重提条件**：若 bin 日更后出现「handler HIT 但特征列漂移」，把 qlib_dir 指纹升为强制键分量。

---

## 卡 3 · 禁 fetch→parquet 硬化 + pickle 体积/峰值 RSS 护栏

**标题**：固化「禁 fetch 落巨型 parquet」并给 dump_all pickle 加体积与加载峰值护栏

**本仓锚点**：HOST 硬纪律 4「禁止用 `fetch()` 落巨型 parquet 再拷（已 OOM 先例）」；#43 选定 `to_pickle(dump_all=True)` 单文件；`custom_train_backtest` 仍有 `handler.fetch(col_set="feature")` 用于对齐/导出旁路——大宇宙×长窗时易双峰内存（handler 对象 + fetch DataFrame）。

**提案**（IO级 + 纪律级 + 内存级）：
1. 代码/文档双禁：任何「cache 导出」路径不得 `fetch().to_parquet` / 整表 `to_csv`；CI grep 门禁或包装函数直接 raise。
2. handler-cache 写入后记录 `size_mb`；超过阈值（建议按机器档：如 4/8/16 GB）警告或拒绝，引导缩窗/缩宇宙而非换 parquet。
3. 加载路径：先读元数据（行数/列数/size），再 `pickle.load`；可选 `resource`/`psutil` 打点峰值 RSS 写入 manifest，便于 OOM 复盘。
4. 旁路 `fetch` 仅允许小样本冒烟（行数上限），全量特征导出走已有分块/池导出，不经巨型中间表。

**收益**：直接降低「大宇宙长窗」上的 OOM 复发率；把失败从「跑到 40 min 炸」前移到「写 cache 时拒」；manifest 峰值便于定并行度上限（见卡 4）。

**成本与风险**：阈值拍脑袋会误杀合法长窗；需按 Win 宿主实测分档。grep 门禁可能误伤测试夹具——允许 `my_tests/` 白名单。

**冻结检查**：故意构造超阈 pickle → 警告/拒绝且不写坏半文件（原子 rename）。小窗回归仍 HIT。不得改过滤默认。

**对抗预填**：
- 「parquet 可列裁剪更省」→ 否决作 cache 格式；省内存应靠缩键/分片 pickle，不靠 fetch 落盘。
- 「mem_cache_size=10 一开就好」→ 否决盲开（`qlib_14` 等历史注释表明未验证）；登记远期与 RSS 护栏联动后再议。

**建议裁决**：采纳（禁令硬化 + size/RSS 打点）；阈值数值先警告后强制。

**重提条件**：再出现一次 fetch→中间落盘 OOM，或 pickle > 宿主 RAM/2，则阈值改强制并拆分片方案（卡 5）。

---

## 卡 4 · 内存预算驱动的并行度上限（handler 份数 × kernels）

**标题**：按 handler-cache 体积与 RSS 预算自动钳制并行度，防 sweep/多臂 OOM

**本仓锚点**：HOST e「大宇宙、长窗、pickle 体积、并行度上限」；过滤/训练侧 kernels>1 在 Win 小查询曾极慢（#39/#43），且多进程×大 handler 会乘性吃 RAM；`dump_bin --max_workers` 已钉 8（16 进程池回收死锁）——说明「并行度有宿主上限」已有先例。

**提案**（调度级 + 内存级）：
1. 估算：`peak ≈ n_parallel * (pickle_size * load_factor + fetch_peak)`；`load_factor` 初值 2–3（反序列化膨胀）。
2. CLI/sweep：`--mem-budget-gb`（默认取机器可用 RAM 某一比例）→ 反推 `max_parallel_handlers`；与 kernels=1 默认正交（kernels 仍按查询粒度另议，本卡只管「同时活着的大数据结构份数」）。
3. 合批验证纪律：涉及 handler_init 的片合批跑（HOST §1.5），并在合批脚本里读同一预算，避免一片一跑与盲目并行两头踩。

**收益**：砍的是 sweep/多配置「一次多臂」时的 OOM 与 Win 换页导致的墙钟爆炸；让「一次 init 多配置」在内存上可规划，而不是撞了再砍臂。

**成本与风险**：估低 → 仍 OOM；估高 → 吞吐偏低。Linux VM 与 Win 宿主 RAM 差异大，预算必须读运行时宿主，不能写死在 CI 数字里。

**冻结检查**：在预算内跑 2 臂 vs 超预算请求 8 臂 → 后者自动降到 N 且日志明示。不改变单臂收益向参数。

**对抗预填**：
- 「为快把 kernels 拉回 16 且并行 4 臂」→ 否决（与 #43 证据冲突，且乘性 OOM）。
- 「内存不够就开 swap」→ 否决作策略；只作逃生观察。

**建议裁决**：登记远期（依赖卡 3 的 size/RSS 打点落地后再做自动钳制）；本轮可先文档化手工公式。

**重提条件**：卡 3 打点稳定 ≥1 周，或 sweep 再爆一次多臂 OOM。

---

## 卡 5 · 超大窗 handler 分片 pickle（远期） vs 单文件 dump_all

**标题**：长窗/全宇宙下 dump_all 单文件的分片或惰性加载——仅当体积护栏不够时启用

**本仓锚点**：#43 现状「单文件 `to_pickle(dump_all=True)`」正确且简单；OOM 与磁盘峰值随窗长/宇宙线性（到超线性）涨；`task_utils` 缓存粒度为整 handler。

**提案**（缓存级 + IO级，远期）：
1. 保持默认单文件；仅当 `size_mb` 超硬阈时，按日历年或 learn/infer 段切成多 pickle，manifest 列分片列表。
2. Dataset 侧按需 load 当前段，用完释放；禁止一次性把全部分片装进 RAM。
3. digest 仍是「整配置一键」；任一分片缺失 → 整键 MISS 重筑。

**收益**：把「不能跑的长窗」变「可跑但首构更慢」；潜在节省加载峰值 RSS 一半以上（视分段）。

**成本与风险**：实现复杂、易脏读、Win 文件锁与半写入；与 qlib Dataset 假设耦合深。收益未证前不宜动默认。

**冻结检查**：分段 HIT 后任抽两段特征 vs 单文件全量对拍；删一分片必须全键 MISS。

**对抗预填**：
- 「直接上 memmap/arrow 换掉 pickle」→ 登记更远；先分片 pickle，避免格式战争。
- 「为省内存关掉正确性 gate」→ **否决**（HOST g / 收益纪律另册）。

**建议裁决**：登记远期（卡 3 护栏不够用再立项）；本轮不改代码。

**重提条件**：生产 handler-cache 单文件稳定 > 宿主 RAM/3，或卡 3 强制阈频繁误杀合法实验窗。

---

## R1 小结（kimi）

| # | 标题 | 方向 | 建议裁决 |
|---|------|------|----------|
| 1 | handler-cache digest 扩面 + HIT/MISS 可观测 | b | 裁剪后采纳 |
| 2 | handler vs expr/dataset 失效协议 + purge | b | 采纳 |
| 3 | 禁 fetch→parquet 硬化 + pickle/RSS 护栏 | e（兼 b 纪律） | 采纳 |
| 4 | 内存预算钳制并行度 | e | 登记远期 |
| 5 | 超大窗分片 pickle | b+e | 登记远期 |
