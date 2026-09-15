# Host 收敛 · MyQuant qlib **工程性能**还能抬哪一截（2026-09-15）

**R1 来源**：`r1/{grok,kimi,codex,cursor}.md`（四家均落盘）  
**R2**：host 交叉合并（未再开第二轮 CLI）  
**结论一句话**：**能再抬，但下一刀是「调度少付 init + bar 内少打 D.features + 缓存可观测」；不是把 kernels 开回去，也不是为快关 gate。**

与收益册正交：`../2026-09-15-qlib-perf-brainstorm/` 管年化/名单；本册只管墙钟/吞吐/OOM。

---

## 四态裁决总表

### P0 · 采纳（先做，不改收益默认）

| ID | 来源 | 标题 | 裁决依据 |
|----|------|------|----------|
| P0-1 | codex-1 ≈ cursor-5 | **一次 handler_init → 多臂消费**契约（train/sweep/export；日志 `INIT_ONCE`/`ARM_ONLY`） | N×~18min → 1×init；HOST 硬纪律 5 |
| P0-2 | codex-2 | **manifest `timings.nodes` 标准化**（Loading/handler_init/fit/predict/export/arms） | 可证伪调度；区分 cache HIT vs 重复 Loading |
| P0-3 | codex-4 ≈ cursor-2 | **init 前 preflight**（host_env / mlflow 逃生口 / 段校验 / 单实例锁） | 防再白付 ~17 min；失败快返回 |
| P0-4 | grok-3 | **return-gate 双 `D.features` 合一 + 同 bar 补足差量**（绑 kernels=1） | #40 后下一刀 bar IO；名单 digest 不变 |
| P0-5 | kimi-2 | **handler vs expr/dataset 失效协议 + bin 刷新 purge** | gate/窗变只信 handler-cache；防脏 HIT |

### P1 · 裁剪后采纳（施工单有边界）

| ID | 来源 | 标题 | 裁剪条件 |
|----|------|------|----------|
| P1-1 | grok-1 ≈ cursor-3 | **默认 kernels=1**；清入口硬编码 16；自适应抬升**只实验不进默认** | 须 Win 对照表；小查询硬禁止 >1 |
| P1-2 | grok-2 | **ProcessPool 税表**进 manifest（spawn/task/join）；税高自动降 1 | 埋点浅；τ 可先松 |
| P1-3 | kimi-1 | **handler-cache HIT/MISS 日志 + digest 键清单文档化** | 全量键扩面合批进下一片，勿一片一跑 |
| P1-4 | kimi-3 | **禁 fetch→parquet 硬化 + pickle size/RSS 打点**（先警告后强制） | 阈值按 Win 宿主分档；测试白名单 |
| P1-5 | codex-3 | **`--pred-from` 落盘交接**：export/二次 sweep 零二次 Loading | 先 CSV+manifest 链；禁新巨型格式 |
| P1-6 | grok-4 | **四开关资格链 bar 调用谱盘点**（先量后预载） | 预载不得偷渡训练特征；禁巨 parquet |
| P1-7 | cursor-1 | **墙钟定案钉 Win**；CI/Linux 只契约烟测 | 禁止 CI 塞长墙钟 job |

### P2 · 登记远期

| ID | 来源 | 标题 | 重提条件 |
|----|------|------|----------|
| P2-1 | kimi-4 | 内存预算钳制并行臂数 | P1-4 RSS 打点稳定或再爆多臂 OOM |
| P2-2 | kimi-5 | 超大窗分片 pickle | 单文件 > RAM/3 或护栏误杀合法窗 |
| P2-3 | cursor-5 边界 | 宿主合批 vs CI 永不承担合批墙钟（细节归 P0-1） | 已并入 P0-1；仅留 diag-only 标签文档 |
| P2-4 | grok-1 自适应部分 | 大查询 Win 粒度扫描后写自适应表 | ≥3 代表查询 kernels>1 稳定 ≥1.5× 且无死锁 |

### N · 否决（写满，防再提）

| ID | 来源 | 否决动作 | 证据 | 重提条件 |
|----|------|----------|------|----------|
| N1 | grok-5 / cursor-3 | 默认 kernels / 盲拉 n_jobs>1「冲吞吐」 | Win 小查询 29s→0.09s；Loading 52min→405s | 仅 P2-4 协议下的自适应，默认仍 1 |
| N2 | grok-5 / cursor-4 | 为快关 return gate / 四开关 / chip-parity | #40 对齐后加速才可信；硬纪律 1 | 无「关 gate」通道；等价更快断言另 PR |
| N3 | grok-5 / kimi-3 | fetch→巨型 parquet 作 cache | 已 OOM；#43 钉 pickle dump_all | 无；分片 pickle 走 P2-2 |
| N4 | cursor-1 | 用 Linux/CI 墙钟数字写预算或「采纳」收益栏 | 硬纪律 2；CI 30 min 无长窗数据 | 自托管 Win+golden 短窗另议 |
| N5 | codex 对抗 | 每臂独立进程重训「更干净」 | 白付 N×Loading | 内存上限时改为一次 init 落 pred、多进程只读 |
| N6 | cursor-2 对抗 | 关 mlflow / 把宿主 Loading 塞进 CI 探活 | maintenance 事故；CI 30 min | 入口 host_env + mock 探活 |

---

## 还能抬哪一截？Host 判断

1. **调度层（最大头）**：重复 handler_init / Loading 仍是 N 倍税。P0-1 + P1-5 把 sweep/export 从「再付 15–50+ min」压到「一次构建 + 读产物」。  
2. **过滤 bar 层（#40 之后）**：~3.6s/bar 里下一刀是 return-gate 合并查询（P0-4）+ 调用谱后再预载（P1-6），不是再拧 kernels。  
3. **缓存可观测（防假快）**：HIT/MISS、失效协议、禁脏格式（P0-5、P1-3、P1-4）保住 #43 红利，避免「以为 HIT 实则白训」。  
4. **防护型**：preflight（P0-3）与 Win 定案（P1-7）不创造新加速曲线，但阻止整轮作废与假加速合入。  
5. **明确不能假装抬过的**：盲抬 kernels、关正确性门、fetch 巨文件、Linux 数字当 Win 预算。

已落地锚点（勿回退）：kernels=1 小查询与 Loading；#40 close cache + CYQ 跳过 Quantile（41.6→7.2 min）；#43 handler-cache pickle。

---

## 建议执行序（给人裁；本 brainstorm 不改代码）

1. **纪律零代码**：P1-7 跑在哪表；N1–N6 写进 followups；入口 host_env 清单（P0-3 文档半）。  
2. **低成本施工**：P0-2 timings 节点 + P0-3 preflight + P1-3 HIT/MISS 日志。  
3. **调度契约**：P0-1 一次 init 多臂 + P1-5 `--pred-from` 链。  
4. **bar IO**：P0-4 return-gate 合并（绑 kernels=1）→ 再 P1-6 调用谱。  
5. **kernels 债**：P1-1 清硬编码 16 + P1-2 税表；自适应仅 P2-4。  
6. **内存远期**：P1-4 打点 → P2-1/P2-2。

产物路径：`docs/reviews/2026-09-15-qlib-eng-perf-brainstorm/`
