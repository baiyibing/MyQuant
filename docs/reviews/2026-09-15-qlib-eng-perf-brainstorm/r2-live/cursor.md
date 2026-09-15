# R2-live · cursor · 方向 f/g：宿主/CI 分工 + 自由发挥与扫漏否决

**Agent**：cursor（真 CLI R2-live，只读不改代码）
**主领**：f 宿主/CI 分工；g 自由发挥 + 扫漏否决
**与 R1 关系**：`r1/cursor.md`（5 卡）已裁入 `SYNTHESIS.md`/`TASKS.md`（P1-7 Win 定案、P0-3 preflight、N1 盲抬 kernels、N2 关 gate、N4 Linux 数字当预算、N6 mlflow 塞 CI、P2-3 合批边界）。本轮不重复这些结论，只汇报**重新核对当前 HEAD 后发现的新锚点/新漏洞**，并据此出卡。
**本轮新增核验**（均为只读命令，未改任何文件）：
- `my_scripts/custom_train_backtest.py:97` 仍是 `qlib.init(..., kernels=16, ...)`——**这正是产出 #43「16-kernel Loading ~52 min」证据的那份配置，至今未改**。
- `feature_experiments.py` / `predict_extended.py` / `sweep_live_adapter.py` / `test_zhangting_filter.py` 的 `qlib.init(...)` **都不传 `kernels`**，而已安装 qlib `config.py:182` 默认 `"kernels": NUM_USABLE_CPU`（`config.py:147`：`max(cpu_count()-2, 1)`）——即这几个入口在真机上默认吃满近全核，不是 1。
- `custom_train_backtest.py` 里 `redis_host='127.0.0.1', redis_port=6379, redis_password='123456'` 硬编码；脚本自带注释承认「Redis 连接失败会自动降级为不使用缓存，可能影响性能但不报错」——即**静默降级，无 HIT/MISS 信号**。
- `.github/workflows/ci.yml`：每次 CI 都 `git clone` qlib 仓库 + `git checkout 79633dd9` + `pip install -e qlib-dev`，**无 `actions/cache`**；同一注释里已明文「qlib 按开发基准 commit 源码安装…勿用发布包」。
- `plan-followups-env-and-manifest-2026-09-13.md` 任务 1 的 `host_env` 覆盖清单核对：`custom_train_backtest.py`/`sweep_live_adapter.py`/`feature_experiments.py`/`sweep_ranking.py`/`export_daily_pool.py` 均已 `import host_env`（R1 卡 2 的门禁诉求**已落地**，本轮不重开，仅备注确认）。

---

## 卡 1 · 训练主入口 `kernels=16` 硬编码仍活着——已测锚点未落地，天天在盲抬

- **标题**：`custom_train_backtest.py:97` 的 `kernels=16` 与「已锁定 kernels=1」结论正面冲突，且未被任何测试/CI 挡住
- **本仓锚点**：`my_scripts/custom_train_backtest.py:97` `qlib.init(..., kernels=16, ...)`；`HOST.md` §2 锚点「#43 train kernels=1：16-kernel Loading ~52 min miss vs kernels=1 ~405s bare-read」——**这条证据本身就是拿这份配置测出来的**，测完之后代码没有跟着改回 1。`git log`（`95caaa8`/`2834338`/`f7c6bf3` 等近期提交）显示这行自更早版本起从未被触碰。`my_tests/`、`ci.yml` 均不执行这个入口，无法拦截。
- **提案**（纪律级/否决现状）：登记为**必须清理的默认值**——把 `kernels=16` 改为可通过 CLI/环境变量覆盖、默认 `1` 的显式参数；本轮不动代码，只把这条列为下一个小 PR 的头号候选，并建议在改之前先跑一次同窗口 A/B（kernels=1 vs 16）复核 #43 数字仍成立（机器可能已换）。
- **收益**：直接消灾——防止任何人下一次真跑训练时，在毫无察觉的情况下重新支付 ~52 min 级 Loading 税；把 #43 的 7×+ 红利真正兑现到「默认」而不是「测过但没生效」。
- **成本与风险**：改动本身是一行参数、零逻辑风险；风险点是「机器已换」——若开发机核数/磁盘变了，1 未必仍最优，故要求改前先 A/B，不能直接拍 1。
- **冻结检查**：不碰 topk/过滤默认（硬纪律 1）；这是恢复已验证结论，不是新猜测。
- **对抗预填**：「这行早就该改了，不算新发现」——同意结论不新，但**现状确认**是新的（本轮才核实它今天仍在 HEAD 上），且此前所有卡都只说「仍可见 kernels=16 类默认残留语境」这种模糊表述，没钉过精确 file:line；「反正没人用这个默认」——`custom_train_backtest.py` 是仓内唯一命名为训练入口的脚本，大概率就是日常真跑的那一份。
- **建议裁决**：**采纳**（登记为后续小 PR：改默认值 + 加一条单测断言 `kernels` 的调用参数，防再回退）
- **重提条件**：若小 PR 落地后单测能断言默认值且 A/B 确认 1 仍更快，本卡关闭；若 A/B 显示当前机器上 >1 更优，转给 grok 的 a 车道走「粒度扫描后写自适应表」流程（P2-4），不由本卡直接改默认。

---

## 卡 2 · 扫漏：Redis 静默降级破坏「缓存必须可证伪」硬纪律

- **标题**：训练入口把 Redis 当隐性缓存层接进来，连不上时静默降级、无 HIT/MISS 信号，正是硬纪律 3 要防的那种「看不见的假加速/假一致」
- **本仓锚点**：`custom_train_backtest.py` 里 `redis_host='127.0.0.1'`、`redis_port=6379`、`redis_password='123456'` 硬编码，且脚本注释自己写明「如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误」；`HOST.md` 硬纪律 3「缓存必须可证伪：HIT/MISS、digest 键、改 gate/窗必须 miss」。当前无任何日志/打点告诉使用者这次跑的到底是「Redis 命中」「Redis 未命中」还是「Redis 根本没连上」。
- **提案**（IO 级/纪律级，g 扫漏）：否决「继续把这当作静默细节放着不管」的现状；登记一条最小可观测性诉求——启动时打一行日志（连接成功/失败/降级），失败时明确标出「本次无 Redis 缓存」而不是悄悄吞掉。不要求现在就拆掉 Redis 或改连接参数，只要求**可见**。同时提醒：这条 Redis 路径与 #43 的 `--handler-cache`（pickle digest）是两套不同缓存，不能互相顶替对方的可证伪义务。
- **收益**：防止「以为有缓存加速、实际全程裸跑」或反过来「以为裸跑、实际吃了脏 Redis 缓存」两种误判浪费复测时间；跟 CI/Win 双跑场景尤其相关——CI runner 上大概率没有本机 Redis，会静默降级，若日志不显式，排错者会误判「CI 也走了缓存路径」。
- **成本与风险**：加一行日志几乎零成本；风险是有人把这条卡误读成「现在就要重构缓存架构」——不是，本卡只要可观测性，不动连接逻辑，也不改 handler-cache digest 语义（正交于 kimi 的 b 车道）。
- **冻结检查**：直接服务硬纪律 3；不新增缓存层，不改现有 digest 键设计。
- **对抗预填**：「密码硬编码写在源码里也是个问题」——是安全/工程卫生问题，但不在本 host 范围（墙钟/吞吐/OOM），不占本卡篇幅，留给别的复盘；「Redis 降级本来就是 qlib 官方行为，不该管」——官方行为可以保留，本卡只要求**暴露**这个行为发生与否，不要求改行为。
- **建议裁决**：**裁剪后采纳**（只要「启动时打一行可见日志」，不做连接池重构、不做失败重试）
- **重提条件**：若发现 Redis 命中/降级状态确实已有等效日志（本次核验未找到，若后续有人指出遗漏位置需重查），本卡降级为登记远期或撤销；若之后要设计正式的多级缓存可观测面板，归并入 kimi b 车道的失效协议设计，不由本卡单独扩张。

---

## 卡 3 · CI `git clone` + `pip install -e qlib-dev` 每次全量重来，无缓存吃掉 30 min 预算的一截

- **标题**：给 CI 加 pinned-commit 精确绑定的构建缓存，省下的是 CI 周转墙钟，不是宿主训练墙钟——两者不可混为一谈
- **本仓锚点**：`.github/workflows/ci.yml`：`windows-latest` + `timeout-minutes: 30`，每次 job 都执行 `git clone https://github.com/microsoft/qlib.git qlib-dev` → `git -C qlib-dev checkout 79633dd9` → `pip install -e qlib-dev` → `pip install -r requirements.txt pytest`，无 `actions/cache` 介入；同文件注释已写明「qlib 按开发基准 commit 源码安装（requirements.txt 注明的口径，勿用发布包）」。这是纪律已有、执行未省时的典型例子。
- **提案**（调度级，f 宿主/CI 分工）：给这段加 `actions/cache`，缓存 key 精确绑定 `{OS}-{python-version}-79633dd9-{requirements.txt 内容 hash}`；commit sha 或 requirements 变化即 miss 重装（可证伪性对齐硬纪律 3 的精神，虽然这是 CI 基础设施缓存而非数据缓存）。**不引入**任何「拉最新 / 拉发布包」的捷径。
- **收益**：省下的是每次 PR 的 CI 排队/运行时间（clone+编译这段目前是固定税），把 30 min 预算里更多份额让给真正要看的 pytest 信号，降低「pytest 本身没变慢，但 CI 因为固定开销顶到 timeout」的误报概率。**明确不代表**宿主训练/回测墙钟有任何变化（呼应硬纪律 2、R1 已否决 N4：Linux/CI 数字不能写进宿主预算）。
- **成本与风险**：`actions/cache` 配置成本低；主要风险是**缓存键选错导致正确性事故**——如果 key 没绑死 commit sha，可能出现「locally 改了 qlib-dev 内容但 key 未变 → CI 用旧缓存跑，测试结果与预期 qlib 版本不符」这种隐性错误；必须把 pinned commit sha 写进 key，而不是用 `qlib-dev` 目录内容做弱哈希。
- **冻结检查**：不触碰 pytest 用例本身；不改「按 commit 源码安装、禁发布包」的既有纪律；不把这当作产品墙钟收益登记。
- **对抗预填**：「CI 又不是宿主主战场，管它多久」——CI 周转时间仍占工程带宽（PR 反馈延迟），且 30 min 硬顶意味着固定开销越大、留给真实信号的余量越小；「不如直接换成 pip 官方发布包更快」——**这正是卡 4 要否决的动作**，两卡配套读。
- **建议裁决**：**裁剪后采纳**（登记为一个独立、小的 CI 基础设施 PR；必须在 key 里锁死 commit sha，且合入前跑一次「改 commit sha 触发 miss」的验证）
- **重提条件**：若 GitHub Actions 侧 `actions/cache` 对 `pip install -e` 场景命中率差（源码编辑安装模式常见问题），或缓存导致过一次「跑的其实是旧 qlib」的事故，立即否决并回退到无缓存现状。

---

## 卡 4 · 否决：为省 CI 时间，把 pinned-commit 源码安装换成官方发布包

- **标题**：否决「CI 太慢 → 改用 `pip install qlib` 发布包代替 79633dd9 源码安装」这条捷径
- **本仓锚点**：`.github/workflows/ci.yml` 现状本身已把纪律写进注释——「qlib 按开发基准 commit 源码安装（requirements.txt 注明的口径，勿用发布包）」；`HOST.md` §2 全部锚点（kernels=1、#40、#43 等）都是**针对这个 pinned commit 版本**测出来的数字，换成官方发布版本，qlib 内部实现细节（缓存路径、`D.features` 行为、`kernels`/进程池语义）都可能不同，之前所有墙钟锚点当场失效，且没人会在换版本当天重新全套复测。
- **提案**（纪律级/否决）：明确否决任何以「CI/安装更快」为理由，把 `qlib-dev` 源码安装换成 PyPI 发布包、或换成别的 commit 而不同步重新核验 §2 全表锚点的提案。加速 CI 只能走卡 3 的「缓存同一 pinned commit 的构建产物」路径，不能走「换掉基准版本」路径。
- **收益**：保住整套已测锚点（kernels=1 系列、#40 7.5×、#43 handler-cache 语义）的有效性；防止「CI 变快了，但所有历史性能数字全部作废却没人发现」这种隐性事故。
- **成本与风险**：否决本身零成本；唯一风险是长期看 `pip install -e` 从源码编译确实比装轮子慢——但这属于「用缓存换速度」（卡 3），不是「换基准换速度」（本卡否决的对象），两者手段不能混淆。
- **冻结检查**：与硬纪律 2（Win 主战场定案）、硬纪律 3（缓存可证伪）间接呼应——换基准版本等于把所有「同配置」的隐含前提（同 qlib 版本）悄悄改了，破坏可比性。
- **对抗预填**：「发布包也是 79633dd9 之后的某个稳定版，应该差不太多」——`config.py` 里 `NUM_USABLE_CPU`/`kernels` 默认值、handler/expr cache 实现细节历史上跨版本变过，「差不太多」不能替代重测；「只在 CI 里换，宿主仍用源码版」——CI 若跑不同版本，其「契约烟测」职责本身就失真，等于卡 1（R1）里说的「CI 过 ≠ 宿主墙钟过」又叠了一层「CI 过的甚至不是同一个 qlib」。
- **建议裁决**：**否决**
- **重提条件**：仅当团队主动决定升级基准 qlib commit（走独立评审/PR，不由本 perf brainstorm 发起），且升级后重跑 §2 全部已锁定锚点确认数量级未变，才可以在新基准上讨论安装方式优化；否则维持源码 pinned 安装。

---

## 卡 5 · 登记远期：CI 加「manifest 结构契约」烟测，但不跑真实 init/训练

- **标题**：等 Codex 的 `timings.nodes` 标准化落地后，CI 该验的是 schema 而不是秒数
- **本仓锚点**：`TASKS.md` P0-2「manifest `timings.nodes` 标准化（Loading/handler_init/fit/predict/export/arms）」尚待 Codex 车道落地；`ci.yml` 现状只跑 `my_tests` + `test_zhangting_filter.py`，没有任何针对 manifest 输出结构的断言；`docs/plan-followups-env-and-manifest-2026-09-13.md` 任务 2 已有 `git_branch`/`git_dirty` 字段的单测模式（mock `git rev-parse`），可复用同款「mock 输入、断言字段」思路。
- **提案**（f 宿主/CI 分工，登记远期）：一旦 P0-2 落地，CI 侧只做**结构契约**——用极小 fixture/mock 走一遍 manifest 写出路径，断言 `timings.nodes` 里该有的键（`handler_init`/`fit`/`predict`/`export`/`arms` 等）都在，不要求数值、不要求真跑 handler_init。这与卡 1（R1）「CI 只保契约、不塞长墙钟 job」是同一条边界的延伸。
- **收益**：为 P0-2 提供一层「字段没被后续改动误删」的回归防护，防止 manifest 契约悄悄漂移导致 followups/roadmap 回写脚本读不到字段却没人发现；零新增墙钟成本（mock 跑法本身很快）。
- **成本与风险**：目前 P0-2 本身还没实现，本卡内容依赖其接口设计，暂不能定具体断言项；风险是抢跑设计细节，越界进 Codex 的 d 车道。
- **冻结检查**：不预先定义 `timings.nodes` 的字段清单（那是 d 车道的活）；不在 CI 里跑真实 handler_init。
- **对抗预填**：「没有实现就不该先写 CI 卡」——本卡不实现，只预占「CI 该做什么、不该做什么」的边界位置，避免 P0-2 落地时又要重新吵一遍「要不要在 CI 里跑真的 init 来验 timings」。
- **建议裁决**：**登记远期**（P2；待 P0-2 有具体 schema 后转为 P1 任务书）
- **重提条件**：`timings.nodes` 字段清单确定后，本卡自动升级为可执行的小 PR 候选；若 P0-2 长期不落地，本卡随之搁置，不单独推进。

---

## 本 lane 小结（R2-live，供 Host 汇总）

| 卡 | 方向 | 类型 | 建议裁决 | 与 R1 关系 |
|---|---|---|---|---|
| 卡 1 | g 扫漏 | 训练入口默认值 | 采纳 | 新发现（file:line 级核验，非 R1 泛泛提及） |
| 卡 2 | g 扫漏 | 缓存可证伪 | 裁剪后采纳 | 新发现（Redis 静默降级，R1 未覆盖） |
| 卡 3 | f 宿主/CI 分工 | CI 基建缓存 | 裁剪后采纳 | 新发现（qlib-dev 安装无缓存） |
| 卡 4 | g 扫漏否决 | 否决换基准换速度 | 否决 | 新发现，但精神呼应 R1 N4/硬纪律 2 |
| 卡 5 | f 宿主/CI 分工 | 契约烟测边界 | 登记远期 | 承接 R1 卡1 边界 + Codex P0-2 |

**边界声明**：不重复 R1 已裁的 5 张卡（Win 定案、mlflow preflight、盲抬 kernels 否决、关 gate 否决、合批边界）；本轮全部基于对当前 HEAD 的只读复核，卡 1/2/3 是**代码现状与已测结论不一致**的具体证据（比 R1 更具体到 file:line），卡 4/5 是新场景下的否决与远期登记。不抢 grok（a/c）、kimi（b/e）、Codex（d）车道。
