# Host 收敛 · R2-live · MyQuant qlib **工程性能**（2026-09-15 真 CLI）

**来源**：`r2-live/{grok,kimi,codex,cursor}.md`（真 CLI 重开；非 R1 复述）  
**Roster**：grok / cursor kimi-k2.7-code / codex / cursor sonnet  
**结论一句话**：**下一刀仍是少付 handler_init、少打 bar 内 D.features、让缓存可观测——不是把 kernels 开回去，也不是为快关掉正确性 gate。**

与收益册正交：`../2026-09-15-qlib-perf-brainstorm/` 管年化/名单；本册只管墙钟/吞吐/OOM。相对 R1 `SYNTHESIS.md`：本文件**只据 r2-live 重新裁决**；R1 已锁项若本轮无新锚点则降为「仍有效、不重开」。

---

## 四态裁决总表

### P0 · 采纳（先做，不改收益默认）

| ID | 来源 | 标题 | 裁决依据 |
|----|------|------|----------|
| P0-1 | grok-1 ≈ cursor-1 | **全生产入口显式 `kernels=1`**：清 `custom_train_backtest.py:97` 的 `kernels=16`；`predict_extended` / `sweep_live_adapter` / `feature_experiments` 漏传一律钉 1；缺 `kernels=` 即失败 | #43 红利点从未接到漏网入口；上游默认≈`NUM_USABLE_CPU`，Win 上等同盲抬；本轮 HEAD 核验仍活 |
| P0-2 | kimi-5 ≈ codex-1 | **一次 handler_init → 多臂消费**：ranking sweep 先 `replace_task_handler_with_cache` 一次，grid 只改策略 kwargs；manifest 标 `shared_handler_cache_key` / `INIT_ONCE` | M×~18 min → 1×init；HOST 硬纪律 5；跨窗禁止硬共享 |
| P0-3 | grok-3 | **return-gate 双单日 `D.features` 合一 + 补足改差量**（绑 kernels=1）；语义钉现行双日点查，禁照搬 old 的 groupby first/last | 「极致性能」把一次区间拆成两次单日 = 负优化；最坏 4×`D.features`/bar；#40 后下一刀 bar IO |
| P0-4 | kimi-1 + kimi-2 | **handler-cache 可观测 + digest 扩键**：HIT/MISS 结构化日志进 run-manifest；digest 含自定义算子源码 hash + 数据字段 schema；改 gate/窗/算子/字段必 miss | 硬纪律 3；防「改了 SMA 仍 HIT」脏读；同配置真省 15–18 min 可审计 |
| P0-5 | codex-3 | **父任务承担共享耗时**：批次父记录 `preflight→handler→fit→predict→产物→各臂`；各臂只记独占并引用父 ID；缺失计时标未知，禁 `total_seconds: 0` | 停「零秒 sweep」与重复摊账；失败后少跑已完成臂 |

### P1 · 裁剪后采纳（施工单有边界）

| ID | 来源 | 标题 | 裁剪条件 |
|----|------|------|----------|
| P1-1 | grok-2 | **三钮分账**：`kernels`（features 进程池，Win 默认 1）≠ `dump max_workers`（刷数默认 8）≠ `LGB num_threads`（树内线程）；kernels=1 **不依赖 Redis 存活** | 任一 PR 只动一列；禁「为 Redis 缓存而抬 kernels」 |
| P1-2 | cursor-2 | **Redis 静默降级可见**：启动打一行 连接成功/失败/降级；与 #43 pickle handler-cache 正交，各尽可证伪义务 | 只要日志，不做连接池重构、不改密码卫生（出本册范围） |
| P1-3 | kimi-4 | **训练入口默认关闭全量 `handler.fetch("feature")` 预览**：`--preview-rows` 默认 0；列名走 `get_cols`，禁物化全矩阵 | 消 handler/prepare 双峰内存；生产/CI 显式 0 |
| P1-4 | kimi-3 | **peak_rss_mb + pickle size_mb 护栏进 manifest**；写 cache 超阈默认 warn | 阈值按 Win 分档；fatal 待实测一周或再爆 OOM |
| P1-5 | codex-2 | **预测产物作续跑入口**：export/二次 sweep 只读 pred；复用键含 gate/窗/模型/代码 digest；先写后标完成 | 接通已有 `SignalRecord`/`export_daily_pool`；禁 fetch→巨 parquet |
| P1-6 | grok-4 | **bar 调用谱先量后预载**：短窗 `timing_interval_steps=1` + always-on 计数（`df_calls`/`tradable_calls`/`deal_price_calls`…）；exchange 逐股 quote ≥20% bar 再做当日候选预载 | 预载禁巨 parquet、禁偷渡训练 Quantile；先做完 P0-3 |
| P1-7 | codex-4 | **同 pred 按日分组一次**：sweep/导出少重复 `xs`/全表扫描排序；进程内复用，不新增磁盘层 | 不改截断算法/`nlargest`；中性化不同配置不共享排名 |
| P1-8 | cursor-3 | **CI 给 pinned `79633dd9` 源码安装加 `actions/cache`**：key 绑 `{OS}-{py}-79633dd9-{reqs hash}` | 省 CI 周转，**不计**宿主训练墙钟；改 sha 必 miss |

### P2 · 登记远期

| ID | 来源 | 标题 | 重提条件 |
|----|------|------|----------|
| P2-1 | kimi-1 TTL 部分 | handler-cache 磁盘 TTL/强制配额删除 | 连续两次同配置 miss，或缓存目录 > 宿主剩余盘 30% |
| P2-2 | cursor-5 | CI「manifest 结构契约」烟测（mock，不跑真 init） | 等 P0-5/`timings.nodes` schema 落地后升 P1 |
| P2-3 | grok-1 自适应 / R1 P2-4 | 大查询 Win 粒度扫描后写自适应 kernels 表 | ≥3 代表查询 kernels>1 稳定 ≥1.5× 且无死锁；**默认仍 1** |
| P2-4 | R1 遗留（本轮无新卡） | 内存预算钳制并行臂数 / 超大窗分片 pickle | P1-4 RSS 稳定或再爆多臂 OOM；单文件 > RAM/3 |

### N · 否决（写满，防再提）

| ID | 来源 | 否决动作 | 证据 | 重提条件 |
|----|------|----------|------|----------|
| N1 | grok-5 / cursor 精神 / R1 | 默认抬 kernels / 盲拉 n_jobs>1「冲吞吐」；漏传 `kernels=` 指望上游默认已是 1 | Win 小查询 29s→0.09s；Loading 52min→405s；上游默认≈近满核 | 仅 P2-3 协议下的自适应；默认仍 1 |
| N2 | grok-5 | 为快关 return gate / 四开关 / chip-parity；放宽 15% 阈值少打 `D.features` | 硬纪律 1；收益纪律另册 | 无「关 gate」通道 |
| N3 | grok-5 / kimi | fetch→巨型 parquet 作 cache；未出谱就加 Redis/parquet 二级缓存 | 已 OOM；#43 钉 pickle `dump_all` | 无；分片 pickle 走 P2-4 |
| N4 | grok-5 | 把训练 COST-KDJ `Quantile` 删掉「图快」；或把 `$zhangting` 改回价格模式当加速 | 改的是 Alpha/正确性，不是 eng-perf；会在 handler_init 再买一轮 `D.features` | 特征替换走独立 chip-parity PR；数据修复另册 |
| N5 | cursor-4 | 为省 CI 时间，把 pinned-commit 源码安装换成 PyPI 发布包 | §2 全表锚点绑 `79633dd9`；换基准＝历史墙钟作废 | 独立升基准 commit + 重跑 §2 全表 |
| N6 | codex 对抗 / R1 | 每臂独立进程重训「更干净」；用 Linux/CI 墙钟写 Win 预算 | 白付 N×Loading；硬纪律 2 | 一次 init 落 pred、多进程只读；Win+golden 短窗另议 |
| N7 | grok-2 对抗 | 把 dump=8 或 `num_threads=20` 抄进 `qlib.init(kernels=)`；「不开 Redis 就不算用 qlib」 | 税表不同；kernels=1 下 Redis 对墙钟无正贡献 | 仅 Win 税表某档 ≥1.5× 且锁等待≈0 时作实验档 |

---

## 还能抬哪一截？Host 判断（据 r2-live）

1. **最大未兑现红利（本轮新钉死）**：#43「kernels=1」测过但**没落到默认**——`custom_train_backtest.py` 仍 `kernels=16`，另三入口漏传 → 上游近满核。P0-1 是纪律债，不是新加速曲线；不还债则后续一切 bar/init 优化可被一次盲抬打回 29s/52min 档。  
2. **调度层仍是大头**：同窗 ranking 网格一次 init（P0-2）+ 父/臂计时诚实（P0-5）+ pred 续跑（P1-5）把「再付 15–50+ min」压到「一次构建 + 读产物」。Codex 提醒：已在单进程缓存的不重复计功。  
3. **过滤 bar（#40 之后）**：~3.6s/bar 下一刀是 return-gate 合并 + 差量补足（P0-3），再按调用谱决定 exchange 预载（P1-6）；**不是**再拧 kernels。  
4. **缓存可观测**：HIT/MISS + 算子/schema digest（P0-4）、Redis 降级可见（P1-2）、禁脏格式（N3）保住 #43，避免假 HIT / 假裸跑。  
5. **内存便宜刀**：关全量 fetch 预览（P1-3）消双峰；RSS/size 打点（P1-4）为远期钳制喂数。  
6. **CI 只省周转**：P1-8 缓存同一 pinned commit；N5 否决换发布包。Linux/CI 数字仍不得写进 Win 预算。  
7. **明确不能假装抬过的**：盲抬 kernels、关正确性门、fetch 巨文件、训练 Quantile/涨停字段「顺手」改语义、三钮混用。

已落地锚点（勿回退）：kernels=1 小查询与 Loading 证据；#40 close cache + CYQ 跳过 Quantile（41.6→7.2 min）；#43 handler-cache pickle；`host_env` 入口清单（cursor 本轮确认已落地，不重开）。

---

## 建议执行序（给人裁；本 brainstorm 不改代码）

1. **纪律零/一行代码**：P0-1 全入口钉 `kernels=1` + 清 16；N1–N7 写进 followups；P1-2 Redis 一行可见日志。  
2. **可观测低成本**：P0-4 HIT/MISS+digest；P0-5 父/臂 timings；P1-4 RSS/size 打点。  
3. **调度契约**：P0-2 一次 init 多臂 → P1-5 pred 续跑 → P1-7 按日分组。  
4. **bar IO**：P0-3 return-gate 合并（绑 kernels=1）→ P1-6 调用谱 → 按谱预载。  
5. **内存与三钮**：P1-3 关全量 preview；P1-1 三钮分账文档/门禁。  
6. **CI 基建**：P1-8 pinned-commit cache；P2-2 等 schema 后契约烟测。  
7. **远期**：P2-1/P2-3/P2-4 按重提条件触发，不抢跑。

合批验收（HOST 硬纪律 5）：凡涉 handler_init 的片合批跑 Win——一次冷启动、多臂共享、同配置 HIT、改 gate/窗 MISS、下游失败恢复；MISS 可先查键与调度决策，避免每个反例整轮 init。

产物路径：`docs/reviews/2026-09-15-qlib-eng-perf-brainstorm/SYNTHESIS-r2-live.md`
