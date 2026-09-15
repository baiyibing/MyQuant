# R1 · cursor · 方向 f/g：宿主/CI 分工 + 自由发挥与扫漏否决（共 5 张想法卡）

**Agent**：cursor（只读，不改代码）  
**主领**：f 宿主/CI 分工；g 自由发挥 + 扫漏否决（例：「盲目拉高 kernels」「为快关掉正确性 gate」）  
**依据**：`HOST.md` 全文（硬纪律 §1：Win 主战场、缓存可证伪、禁 fetch→parquet、合批验证；锚点 §2：kernels=1 墙钟、#40/#43、mlflow ~17 min 白付；方向 f/g）；`docs/plan-followups-env-and-manifest-2026-09-13.md`（mlflow file-store maintenance 事故）；`my_scripts/host_env.py`（`MLFLOW_ALLOW_FILE_STORE` 逃生口）；`.github/workflows/ci.yml`（`windows-latest` + `timeout-minutes: 30` + 全量 pytest）；`docs/chip-parity-gate.md`；`docs/plan-three-repo-roadmap-2026-09-12.md`（Win spawn / `if __name__` 教训）  
**纪律**：本轮不改产品代码、不重训、不跑长实验；只出想法卡。

---

## 卡 1 · 宿主/CI 分工矩阵：何物必须 Win 真跑，何物只配 Linux 烟测

- **标题**：把「墙钟结论」钉在 Win 宿主；Linux VM / CI 只做契约烟测，禁止用后者数字当预算
- **本仓锚点**：`HOST.md` 硬纪律 2「Windows 宿主是主战场：进程池固定开销、spawn、路径；Linux VM 可作对照但多数真跑在 Win」；已测锚点 Win kernels>1 小查询 29s→kernels=1 0.09s、过滤 ~100s/bar→3.6s/bar、#43 16-kernel Loading ~52 min vs kernels=1 ~405s——这些量级**只在 Win 复现才有裁决权**。CI 现状：`.github/workflows/ci.yml` 已是 `windows-latest` + 30 min pytest，**不含** handler_init / 过滤回测 / sweep 墙钟。
- **提案**（纪律级/调度级）：书面固化三档分工——① **Win 宿主必跑**：任何声称「更快」的 kernels/缓存/过滤路径改动，验收墙钟必须在本机 Win 用同一 digest/窗复测（HIT 与 MISS 各至少一次）；② **CI（Win GHA）**：只保契约——`host_env` setdefault、handler-cache digest 键单测、filter/kernels 默认断言、spawn/`freeze_support` 烟测；超时继续 ≤30 min，禁止把「一整轮过滤回测」塞进 CI；③ **Linux VM**：仅作跨平台对照与脚本可启动烟测，**不得**用其 Loading/bar 秒数写进「采纳」收益栏或路线图预算。产出物可以是一页「跑在哪」表挂进 followups/roadmap，而非改产品代码。
- **收益**：避免再出现「Linux 上看起来快、Win 上 spawn 池把小查询打回 29s」的假加速；把工程带宽从「两边都测一遍墙钟」收束到「Win 定案、CI 防回归」。不直接砍 init/bar，但防止错误优化浪费整轮（~4.6h 级过滤轮、~18 min handler_init）重测。
- **成本与风险**：文档/纪律成本低；风险是 GHA `windows-latest` 与本机 Win 路径/盘符/杀软仍可能差一截——CI 绿≠宿主墙钟过。必须明确：CI 过只证明「没把默认 kernels/逃生口弄坏」，不证明「更快」。
- **冻结检查**：维护硬纪律 2；不触碰 topk/过滤默认（硬纪律 1）；不把长实验塞进 CI。
- **对抗预填**：「CI 已经是 windows-latest，再区分宿主没意义」——CI 无本机数据宇宙、无长窗、30 min 硬顶，量不出 #40/#43 那种 7×/52 min 级差；「Linux 烟测数字先拿来排优先级」——可作线索，不可作裁决依据。
- **建议裁决**：裁剪后采纳（采纳「三档分工书面化」；裁掉任何「在 CI 里加长墙钟 job」的冲动）
- **重提条件**：若未来有自托管 Win runner + 只读数据夹 + 可证伪的短 golden 窗（≤数分钟、固定 digest），才允许讨论「CI 附带微型墙钟回归」；否则维持现状。

---

## 卡 2 · mlflow / 超时逃生口：宿主长跑前强制 host_env，CI 只验契约不验墙钟

- **标题**：防再白付 ~17 min init——入口门禁 + 超时语义与 CI 30 min 脱钩
- **本仓锚点**：`HOST.md` §2 mlflow 事故「file-store maintenance 白付 ~17 min init」；`docs/plan-followups-env-and-manifest-2026-09-13.md` 任务 1（已合 `host_env.py`，`MLFLOW_ALLOW_FILE_STORE=true`）；`my_scripts/host_env.py` + 各入口「任何 qlib import 之前」import；CI `timeout-minutes: 30` 只罩 pytest。风险形态：新入口脚本漏 import → 又一次 maintenance 死在 init 后；或把「宿主长跑超时」误绑到 CI 30 min 语义上，导致要么 CI 被拖死、要么宿主误用过短超时砍合法 Loading。
- **提案**（纪律级/IO 级）：① 维护「入口清单」门禁（单测或 grep 验收）：凡触碰 qlib/mlflow 的 `my_scripts/*` 入口必须在首个 qlib import 前 `import host_env`；新增脚本进清单；② **宿主长跑超时**与 **CI 超时**分表记录——宿主侧允许 handler_init / 过滤轮按历史量级（~15–60+ min）设软超时+可中断检查点，CI 继续 30 min 只跑单测；③ 禁止「为省事在 CI 里起一段真 init 探活 mlflow」——探活用假路径/单测 mock file-store 即可。
- **收益**：直接避免重复事故形态（已付过的 ~17 min init 白烧）；减少「脚本能跑但环境半残」导致的整轮作废。对 bar/整轮墙钟是防护型收益，不是新加速曲线。
- **成本与风险**：清单与单测维护成本低；风险是 setdefault 不覆盖用户已设值——若有人显式关掉逃生口，门禁拦不住（应文档标明「显式关闭=自担 maintenance」）。Win/Linux 上 mlflow 行为可能略异，但本仓主战场在 Win，以 Win 为准。
- **冻结检查**：不改缓存 digest 语义；不放宽正确性 gate；与硬纪律 3（缓存可证伪）正交。
- **对抗预填**：「followups 已合，卡已过时」——已合的是根治补丁，本卡要的是**防回归分工**（新入口漏接 + 超时语义混淆）仍会发生；「把 MLFLOW 逃生口写进 CI env 全局」——可以，但仍不能替代入口 import 顺序纪律。
- **建议裁决**：采纳（纪律/验收级；本轮仍不改产品逻辑，只登记「入口清单门禁 + 双超时表」为后续小 PR 候选）
- **重提条件**：若再出现一次「漏 import host_env / maintenance 白付 init」或「有人把宿主 Loading 塞进 CI 触发 30 min kill」，立即升级为阻断合入的检查项。

---

## 卡 3 · 否决：盲目拉高 kernels / 默认 n_jobs>1「冲吞吐」

- **标题**：否决「kernels 开大就快」——Win 小查询与 Loading 已证伪
- **本仓锚点**：`HOST.md` §2：Win 单日 50 股 `D.features` kernels>1 ~**29s** → kernels=1 **0.09s**；过滤开过滤曾 ~**100s/bar** → kernels=1 ~**3.6s/bar**；#43 train 16-kernel Loading ~**52 min miss** vs kernels=1 ~**405s**。硬纪律 2 点名进程池固定开销、spawn。`custom_train_backtest.py` 历史上仍可见 `kernels=16` 类默认残留语境；路线图记 Win spawn 无 `if __name__` 会 worker 递归。
- **提案**（纪律级/否决）：明确否决本轮任何「为工程性能把默认 kernels / 进程池并行度盲目调回 >1」或「按 CPU 核数自动拉满」的提案；否决「先在 Linux VM 上看 pool 加速再回写 Win 默认」。允许讨论的唯一开口见重提条件（按**查询粒度**自适应，且必须 Win A/B）。
- **收益**：锁住已落地的数量级胜利（过滤 bar ~30×、Loading ~7×+），防止下一轮「好心优化」把默认改回去后整轮从 7.2 min 打回 40+ min。
- **成本与风险**：零实现成本；风险是极大宇宙/大批量特征拼接在**单进程**上可能更慢——但现有证据显示 Win 上小查询与 Loading 被 pool 固定开销主导，默认 >1 是净负。自适应需另案，不能借「否决默认>1」偷渡「先改默认再测」。
- **冻结检查**：直接服务硬纪律 2；不改收益侧 topk/过滤默认。
- **对抗预填**：「机器更强了 / SSD 更快了，旧 29s 锚点过时」——可以重测，但重测协议必须是 Win、同查询粒度、kernels=1 vs N 对照，不能凭体感改默认；「导出/sweep 多臂该并行」——那是**臂间**进程编排（Codex d 车道），不是把 qlib 内部 `kernels` 拉高，二者不可混为一谈。
- **建议裁决**：否决
- **重提条件**：在 Win 宿主上对「单次 D.features 标的数 / 日期跨度」做粒度扫描，找到**稳定** kernels>1 更快的区间（至少 3 个代表性查询、含 HIT/MISS），并证明不影响过滤 bar 与 handler_init 的回归默认；通过后只允许「自适应策略」登记，仍默认 1。

---

## 卡 4 · 否决：为墙钟关掉正确性 gate / 跳过缓存证伪

- **标题**：否决「先关掉 return gate / chip-parity / digest MISS 检查跑快点再说」
- **本仓锚点**：`HOST.md` 硬纪律 3「缓存必须可证伪：HIT/MISS、digest 键、改 gate/窗必须 miss」；§2 #40「return gate 对齐后真正生效」才让 close cache + CYQ 跳过 Quantile 的 41.6→7.2 min 可信；#43 handler-cache「同配置 HIT、改 gate/窗 MISS」；禁 fetch→parquet（已 OOM）。`docs/chip-parity-gate.md` 为晋升/可比性门，不是可选装饰。g 方向点名示例即「为快关掉正确性 gate」。
- **提案**（纪律级/否决）：否决一切以「工程加速」为理由的下列动作——① 关闭或绕过 return/过滤相关正确性 gate；② 跳过 handler-cache digest 的故意 MISS 用例；③ 用「只测 HIT 路径」冒充缓存验收；④ 为减 IO 恢复 `fetch()`→巨型 parquet；⑤ 把 chip-parity / 单测失败标成 skip 以换 CI 绿。加速只能发生在**门仍然关上**的前提下（预载、跳过重复 Quantile、kernels=1、合批 init 等已证明路径）。
- **收益**：防止「假 7×」——没有 gate 对齐的缓存命中只是脏读加速；一次静默错缓存污染的 sweep 比慢 17 min 更贵。保护已测锚点可复现性。
- **成本与风险**：否决本身零成本；风险是有人把「测量时临时关日志/可视化」也扯进本卡——那些不属正确性 gate，不在否决范围。
- **冻结检查**：强化硬纪律 1（快≠改默认过滤）、3（可证伪）、4（禁 parquet 落盘）。
- **对抗预填**：「gate 太慢，先出数再对齐」——#40 已证明不对齐时优化「看起来」无效；「MISS 用例每次多跑一遍 init」——这是证伪成本，可用小 fixture/短窗，不可删除；「chip-parity 已判不可比，门没用了」——门的价值是挡住错误晋升，关闭它不会让训练变快，只让错误变快。
- **建议裁决**：否决
- **重提条件**：无「关掉 gate」重提通道。若某 gate 经证明确属重复且与墙钟无关，可提案**合并/下沉为更快的等价断言**，但必须保留「改配置必 MISS / 错配置必失败」的可证伪性，并走独立小 PR + 单测，不得以 perf brainstorm 直接删门。

---

## 卡 5 · 登记远期：合批验证调度与「一片一跑」逃生口标签（宿主侧）

- **标题**：宿主 sweep/验证默认合批；CI 永不承担合批墙钟
- **本仓锚点**：`HOST.md` 硬纪律 5「涉及 handler_init 的片合批跑，一片一跑会耗死」；handler_init 历史 ~18 min / ~907s；model_fit ~5.6s 可忽略；mlflow 事故叠加在「付完 init 才死」。方向 f 与 d（Codex：一次 init 多臂）交界——本卡只钉**宿主 vs CI 谁跑合批**，不设计多臂 API。
- **提案**（调度级/纪律级）：① 文档规定：凡触碰 handler_init 的验证矩阵，宿主默认「一次 init → 多配置」，禁止日常「一片一跑」除非标签 `diag-only`（诊断/定位用）；② CI 继续只跑无 init 的单元/契约测；③ 合批失败时的逃生口（mlflow/磁盘/OOM）必须在 init 前检查（呼应卡 2），避免付满 ~18 min 再炸。
- **收益**：把 sweep/多开关验证的墙钟从「N × init」压回「1 × init + N × 便宜段（fit/回测臂）」；与 #43 handler-cache HIT 叠加时收益更大。具体砍的是重复 Loading/init，不是 bar 内微优化。
- **成本与风险**：与 Codex d 车道可能重叠——若 `codex.md` 已有更细的多臂调度卡，本卡应降级为「宿主/CI 边界附议」以免双计；合批排错难度高于一片一跑，需要保留 `diag-only` 逃生标签以免定位不能。
- **冻结检查**：硬纪律 5；不改收益默认；缓存键变则整批 MISS（硬纪律 3）。
- **对抗预填**：「合批不好对比单片日志」——用 manifest 节点计时（followups 已有 commit/启动时 HEAD 方向）按臂切片，而不是退回一片一跑；「CI 偶发跑一片超短窗」——若无数据宇宙则无意义，且撞 30 min 顶，拒绝。
- **建议裁决**：登记远期（P2；待与 Codex d 输出对表后，保留「宿主合批 / CI 不合批」边界句，细节调度归 d）
- **重提条件**：`r1/codex.md` 落地后若已覆盖「一次 init 多臂」，本卡只抽「CI 永不合批墙钟 + diag-only 标签」进 SYNTHESIS；若 Codex 未覆盖合批，则升为 P1 任务书草案（仍本轮不改代码）。

---

## 本 lane 小结（供 R2/R3；R1 先猜，非终裁）

| 卡 | 方向 | 类型 | 建议裁决 |
|---|---|---|---|
| 卡 1 | f 宿主/CI 分工 | 纪律/调度 | 裁剪后采纳 |
| 卡 2 | f 超时与 mlflow 逃生口 | 纪律/IO | 采纳 |
| 卡 3 | g 扫漏否决 | 否决（盲目 kernels>1） | 否决 |
| 卡 4 | g 扫漏否决 | 否决（关正确性 gate） | 否决 |
| 卡 5 | f∩d 合批边界 | 调度 | 登记远期 P2 |

边界：不抢 grok（a kernels 自适应细节 / c 过滤热点具体 IO）、不抢 kimi（b 缓存键设计 / e OOM 结构）、不抢 Codex（d 多臂 API/manifest 节点）；本文件钉 Win vs Linux/CI 的裁决权、超时语义，并预否决两条经典假加速。
