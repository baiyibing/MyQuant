# Joint return v1：R0 合同 / R1 MQ 快照接口

状态：本刀交付 R0 与 MQ R1 data-free；BT R1 下一刀。真实输入 `INPUT_BLOCKED`，分钟链 `NOT_RUN`，新收益、成交率、滑点与 Sharpe 均待实测。

SSOT：[联合实施计划](../2026-09-19-joint-return-implementation-plan.md) §3、R0/R1、F-R2–F-R12；来源与缺口见 [input-register](input-register.md)，门禁见 [acceptance](acceptance.md)。本次用户令覆盖旧计划的 docs-only 派工限制与旧 MQ 实施基线；其余冻结边界继承。

## 1. 代码与有限范围

| 项 | 固定值 |
|---|---|
| IMPLEMENTATION_BASE_MQ | `4e4368b274ada2e27da5902f7420aa5a8ae5950c` |
| IMPLEMENTATION_BASE_BT | `1049b904bdd818dbb79f51f1830a008c8f83b141` |
| 计划文档自己的旧 MQ 基线（仅溯源） | `0cfd91b834bd941682d5824fdf8a85b19d890a88` |
| 完整 control recorder | `8a061ea428e04bb3a199a485ade49d0e` |
| 共同宇宙 candidate recorder | `d03e8ffcb6d14668b4d6fc2b192bc8c7`；候选 score 禁止作为输入 |
| 原 sidecar SHA-256 | `27320f8b7f6de3854802f97325f682039732470ce387f21bc9cd6c3083b7b348` |
| MQ-PJSON 原字节 SHA-256 | `22d86384e7d4fcf82586e51fce4a212309baeab584e5cbb64054788460035e82` |
| MQ-PJSON 规范内容 SHA-256 | `d9b503fa40937c6b870fc4b0bf9285e2ca53f0465af223f529f2e854712ae6f8` |
| 有限组合 / fill 清单 | P-REF 单列诊断；P-BASE、P-CHASE 各配 M-REF、M-LAG；MQ 不运行 fill |

本刀 MQ 白名单仅：

- `docs/reviews/joint-return-v1/contract.md`
- `docs/reviews/joint-return-v1/input-register.md`
- `docs/reviews/joint-return-v1/acceptance.md`
- `my_scripts/joint_return_contract.py`
- `my_scripts/joint_return_portfolio.py`
- `tests/test_joint_return_portfolio.py`

BT 下一刀拟白名单：`backtest/research/joint_return_replay.py`、`scripts/research/run_joint_return_replay.py`、`tests/test_joint_return_replay.py`。本刀不写 BT 文件。sibling 工作区 HEAD `41f3d11a34c665cc8a21b3e1d351b9e06b0466b5` 仅作差异登记，事实按固定 BT 对象读取；不 checkout/pull。后续 R2–R6 另行派工，不在此白名单。

运行 manifest 必填 MQ/BT 两个实际 40 位 `code_shas` 和上述两个 `implementation_bases`；合成 fixture 使用基线 SHA 仅演示字段，不能冒充实际运行提交。实际提交由 PR 与宿主回执登记，文档不自引用自身提交 SHA。

## 2. 字节、排序与配对

所有文本 UTF-8、无 BOM、NUL=0。JSON 拒绝重复 key、NaN、Infinity。规范 JSON：`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` 的 UTF-8 字节，无尾 LF。对象按 key 排序，数组保留语义次序；原始数字不改写，`1` 与 `1.0` 的原值表示分别保留。`content_sha256` 是上述字节 SHA-256；`raw_sha256` 是文件实际字节 SHA-256。磁盘 JSON 末尾一个 LF，故两种 hash 通常不同。

`contract_hash` 是本 `contract.md` 原始 UTF-8 文件字节 SHA-256，绑定本合同全部定义；它不是 recorder 短 ID，也不是代码哈希。BT 必须固定同一文档字节/hash，不能从移动分支取值。合同改动使旧快照拒绝，需重新验收。

scores 按日期升序、日期内 `score desc, instrument asc` 稳定排序；实现使用 Python stable sort，与唯一复合键的 mergesort 结果一致，不改 score。重复 `(date,instrument)` 拒绝，不隐式去重/去 NA。instrument 保留原串，不隐式大小写转换。

intents 按 `(arm_id, decision_at, side_order, instrument, intent_id)`，SELL 的 side_order=0，BUY=1。constraints 按 `(date,arm_id,instrument,status,reason)`。CSV 首行为固定字段顺序，RFC4180 引号、LF 换行；**每个单元格均为规范 JSON 标量**（字符串有 JSON 引号，数字是数字，缺值为 `null`），先 CSV 解码，再 JSON 解码，禁止 pandas 自动类型推断。`read_intents` 校验列集合、顺序、类型、重复 ID 与时点，往返保留全部意图字段。

`intent_id` 为除自身外的整条意图规范 hash。`intent_hash` 为排序后全表规范 hash；另存各 `arm_intent_hashes`。跨仓配对键：`(run_id, contract_hash, arm_id, arm_intent_hash, fill_id)`。同一臂两个 fill 必须固定原始数量、参考状态、原始计划 hash、费用、资金与触发；跨 P-BASE/P-CHASE 不称为同信号。BT 先校验 raw/content hashes、代码基线与意图身份，再消费，不能重新选票或重算原始目标数量。

## 3. 显式快照与来源

唯一输入为调用者给出的 JSON 文件。入口：`python -m my_scripts.joint_return_portfolio --snapshot PATH --run-id ID [--output-root ROOT]`；不搜索 recorder、湖、缓存或旧机器目录，无最近版本回落。纯函数 `build_portfolio(snapshot)` 使用同一校验路径。

顶层必需 `schema_version="joint-return-v1"`、`kind="synthetic"|"frozen"`、`metadata`、`scores`、`initial_state`、`plans`、`pref`。所有业务时点为固定秒精度 ISO8601 `YYYY-MM-DDTHH:MM:SS+08:00`，时区 Asia/Shanghai；日期 `YYYY-MM-DD`。无时区、未来已知值、重复或缺失键、缺必需快照均报 `INPUT_BLOCKED` 或下述更具体状态，不读取真实数据补齐。

| metadata 必需字段 | 单位 / 语义与缺失处理 |
|---|---|
| `code_shas, implementation_bases, contract_hash` | 完整 SHA、合同字节锁；漂移停止 |
| `pred_recorder_id, candidate_recorder_id, sidecar_sha256` | 必须等于 §1；候选只作共同宇宙对齐 |
| `generated_at, window{start,end}, calendar, timezone` | 生成时点、显式窗口、已排序无重复的市场交易日期；不按自然日补日期 |
| `price_domain, valuation_version, benchmark_version` | none 价格域、估值版本、同 fill 的 P-BASE 基准版本；无默认指数 |
| `strategy{topk,n_drop,source,eligibility_version,eligibility_rules,native_stop}` | 10、3、`frozen_original_intents`、资格来源版本、完整非空冻结闸门配置、`N/A`；配置只登记不重新判资格，不得猜 ST/年龄/涨幅资格 |
| `fees{model,buy_rate,sell_rate,minimum,granularity,source}` | commission_only、费率为成交金额比例、最低费 CNY、per_order、证据来源；必须显式给值，无生产政策 import |
| `risk_budget` | 股票目标权重上限 [0,1]；无来源的真实数值仍阻塞 |
| `order_policy, quantity_policy` | §5/§6 固定枚举，无任意阈值网格 |
| `inputs` | scores / initial_state / plans / pref 每项给 `uri,raw_sha256,content_sha256,coverage,version`；规范内容 hash 必须匹配内嵌段 |

`load_snapshot` 只校验指定快照自身原字节及规范内容，并校验内嵌段内容 hash；来源 URI 是声明，不自动解引用。manifest 明确 `snapshot.raw_verified=true`、`input_raw_hashes_verified=false`。源文件 raw hashes、共同宇宙与 PIT 来源须由后续宿主只读核验；这些声明本身不能证明真实输入齐全或可交易性。

## 4. scores 与 P-REF

每行必需 `date,instrument,score,score_available_at,source_version,anti_rank,anti_available_at,candidate_present,label`。score 保留原值；anti_rank 是现有 `MAXRET20_ANTI_RANK`，范围 [0,1]，高值表示近期未大涨。`candidate_present=true` 声明冻结共同宇宙；不得把 candidate score 加入字段。每日 T0 取按 score 排序前 10；中位数取 T0 十个 anti-rank 的通常中位数（第 5/6 个的平均）。严格 `< median` 才跳过，等号保留；T1 按 score 取 `>= median`，不足十个才从 `< median` 按 score 回填，逐项记录放宽。

`pref`：完整 `calendar`、具名 `windows{start,end}`、`expected`、`label`、`bootstrap`。label 固定 `Ref($close,-2)/Ref($close,-1)-1`；每日 Top10Spread 为等权 Top10 label 减完整共同宇宙等权 label，绝不替代成 Top−Bottom 或 PnL。全日 label 缺失保留为 `LABEL_MISSING`；部分行缺标签停止并要求来源对账，不能自动缩小宇宙。每个日期不足十只、漏日、空窗口拒绝。

数值复核范围由 `pref_check.numeric_scope` 明列：完整日历/可用日数、共同宇宙平均行数、T0/T1 Spread、Δ 及正负零比例、Jaccard/overlap/名单 turnover、相同名单占比、放宽数量/天数/比例、T0 低于中位数只数、T0/T1/宇宙 anti-rank 均值、kth ties、moving-block bootstrap、Spearman RankIC（ties 平均秩，退化日记 null/单列分母）、added/dropped anti 与 label、月度/季度分层、冻结 T0 对照差。名单 turnover=`1-overlap/10`，不能替代资金换手。无换入换出时 added/dropped 统计为 null，不伪填零。原 `lgb_frozen_d_top10` 是外部候选模型结果，本门不消费候选分数或重判它，`not_checked` 显式说明。

bootstrap 固定 block=5、reps=10000、seed=20260919；NumPy default_rng 非环状连续块，有放回均匀取起点 0…n−5，拼接截断至 n，2.5%/97.5% 线性 quantile，每窗重置随机数。至少五个有标签日期。绝对容差 `1e-8`、相对容差 0，在看新增收益前固定；不为通过再放宽。原 bootstrap 生成源码未定位，真实数值不匹配即停止，不能以本实现反写原值。

frozen 必须提供与 §1 MQ-PJSON 规范 hash 一致的完整 expected，以及原窗 `2025_valid:2025-01-03…2025-12-31`、`2026_oos:2026-01-01…2026-09-14`。每个日历日必须恰好落入一个窗口，不允许暗删日或重复窗口。真实通过仍需原始来源、统计生成口径与独立窗门禁；本刀真实 P-REF 为 `INPUT_BLOCKED`。synthetic 用手算 expected，永远只报 `SYNTHETIC_PASS`；不匹配报 `PREF_MISMATCH` 并阻止组合输出。

## 5. 原始 10/3 意图与各臂参考状态

当前没有可核验原始 10/3 意图包。`replay_10n3_two_year.py` 调用 backtest_daily；`export_positions_trades.py` 是已成交 PortAna 持仓；`export_next_day_pool.py` 默认 50/5 且可预测。三者均只作来源线索，不能调用、倒推失败订单或偷偷适配。本刀没有实现规则重建适配器。后续若原始快照不存在，须另刀核对冻结规则并交付仅生成意图的确定性适配。

`initial_state` 是两臂共同起点：`cash`（CNY，非负）、`positions`（instrument→`quantity,lot_id,instance_id`）、`quantity_unit="share"`、`native_stop="N/A"`。持仓正数量、lot 唯一、最多十只。参考现金和持仓属于独立的理想化信号路径，不是 M-REF/M-LAG 的实际账本。

每个显式 portfolio calendar 日期必须有两个独立 plan，即使当日无意图也要交空计划。plan 必需：

| 字段 | 定义 |
|---|---|
| `date,arm_id,source,pre_state_hash` | 日期、P-BASE/P-CHASE、frozen_original_intents、该臂上次参考递推后 state hash；不得拿 BASE 状态重置 CHASE |
| `decision_at,available_at,effective_at,expires_at` | decision≤available≤effective<expires；当日所有排序所用 score/anti 已在 decision 前可得；同日 close 事件不授权同根 open |
| `marks,mark_at` | instrument→none 参考价（CNY/share）；mark_at≤decision；旧仓不能缺价；意图转换价格须与该估值点完全一致 |
| `sells` | 原始卖出候选列表；完整数量字段 + `approved:bool,approval_reason`。未经批准继续持有，无名单删除；批准卖出最多 3，只允许完整 lot 退出 |
| `buys` | 原始获准新买 instrument 有序列表；已有仓时最多 3、空仓初始建仓最多 10；持仓总数≤10 |
| `buy_candidates` | 明确冻结的合法回填备选及逐只数量字段，另含 `eligible:bool,eligibility_reason`；每个原始买入必须已获准且有对应数量，缺失停止 |
| `corporate_actions` | v1 MQ 只接受空列表；非空报 SEMANTICS_BLOCKED，不能隐式缩放或漏事件 |

每个数量记录必填 `instrument,execution_symbol,instance_id,lot_id,target_weight,original_target_quantity,reference_price,reference_price_at,quantity_unit,quantity_conversion`。证券映射唯一，跨日不漂移。BUY 为新 lot，不买已有仓；原始数量是明确买卖数量，不是持仓终值。SELL 量/lot 必须等于参考持仓，target_weight=0。目标权重是 [0,1] 的资金比例，旧仓沿用漂移权重；现金为补项。

P-BASE 输出获准原始卖买及其原始权重/数量。P-CHASE 保持原卖出批准结果，只检查原买入；保留不低于 T0 中位数的原买入，严格低于者记录 `SKIP_BELOW_MEDIAN`，在冻结 eligible 候选中按 score 补足原始买入槽位，先 `BACKFILL_SCORE`，仍不足才 `RELAX_BELOW_MEDIAN`。资格失败永不放宽；未授权卖出的旧仓留存，不每日整体换成 T1。回填必须有该臂参考状态对应的数量快照，不能拿另一只股票的股数套用。

每臂用自己选出的 SELL→BUY 在共同参考价递推，扣一次显式 per_order 研究费，验证现金非负、股数合法、最多十只。它只是下一日原始计划的校验参考；fill 结果完全不输入此函数。下一日快照必须与该臂独立 state hash 相同，否则 PAIR_INVALID。manifest 保存完整 before/after state、原始 plan、两个 state hash、漂移/目标权重、目标换手、初始建仓标记、参考费用；失败日停止整包，不删除后继续。

合成手算例：初始 P…Y 各 100 股×10 元，现金 5000，NAV=15000；获准卖 P/Q，R 未获准；原买 A/B 各 100 股、权重各 1/15。A/B 的 anti=.1，C…J=.5，K…O=.8，当日 T0 中位数=.5；CHASE 回填 C/D。BASE 次日持 ABRSTUVWXY，CHASE 持 CDRSTUVWXY，均仍现金 5000（仅此合成例零费）。次日空计划保持旧仓，绝不改成 C…L。目标换手两臂均 2/15；这不是实际换手或收益。

## 6. 输出意图、数量与公司行动

`intents.csv` 的固定列顺序：

```text
arm_id,intent_id,instance_id,lot_id,instrument,execution_symbol,decision_at,available_at,side,target_weight,original_target_quantity,quantity_unit,quantity_conversion,reference_price,reference_price_at,reason,reference_state_hash,source_plan_hash,effective_at,expires_at,retry_policy,conflict_policy,expiry_policy,native_stop
```

`quantity_unit="share"`、`quantity_conversion="SNAPSHOT_FIXED"`。新买 100 股整手；审计已提供数量是否等于 `floor(target_weight*reference_NAV/reference_price/100)*100`，不改写它；卖出允许退出原有零股/小数 lot。比较现金/转换金额绝对容差 `1e-8` CNY，只消除浮点噪声，不允许融资。费用以 CNY 计、滑点未来通过成交价进入，不二次扣除。reference cost/peak/stop 均 N/A，不向 10/3 添加 r2/Livermore/WRD1。

公司行动转换未来 BT 单独记 `event_id,instrument,available_at,effective_at,from_unit,to_unit,original_quantity,factor,current_quantity,source_hash,price_domain`，所有配对共用同一事件；保留原始数量，未完成订单也须换算。Mode B shares÷k 的 factor=1/k，允许小数旧仓；这不表示现金分红入账或真实总回报守恒。映射/PIT/域不可证则 SEMANTICS_BLOCKED，绝不把转换伪装成选股差异。本刀 MQ 遇显式事件即阻塞，公司行动执行验收留给 BT；真实运行前必须证明无漏事件。

`constraints.csv` 列 `date,arm_id,instrument,status,reason,score,anti_rank,t0_median,reference_state_hash`，状态包含上述 skip/backfill/relax、`ELIGIBILITY_BLOCKED`、`KEEP_UNAPPROVED_SELL`、`KEEP_OLD_POSITION`、`INTENT_EMITTED`；旧仓不在共同 score 宇宙时 score/anti 用 null，持仓仍保留。

## 7. BT R1 生命周期（接口要求，尚未实现）

共同订单政策固定，不是现场可调网格：

- `retry_policy=NEXT_LEGAL_BAR_LIMIT_DOWN_NEXT_SESSION`
- `conflict_policy=CANCEL_OLDER_REMAINDER_SELL_FIRST`
- `expiry_policy=CANCEL_REMAINDER_EXPIRY_EXIT_DEFER_NO_BAR`

每条意图的显式 expires_at 提供有效期，不继承旧脚本 N/现金池。普通剩余订单在截止时点取消；若原始意图本身是到期退出，Q36 当日无 session bar 则挂起到下一交易日并保留原到期标记，不回退日线价。v1 MQ 不生成持有 N 天强卖或止损。已有实际仓位在退出失败后保留和估值。

| 状态 / 转移 | 行为 |
|---|---|
| CREATED→WAITING | 接受原意图，未到可用/生效时点；不丢失原始量 |
| WAITING→ACTIVE | 到合法交易机会；M-LAG 要求 minute open **严格晚于** available_at，且不早于 effective_at，跨午休/收盘到下个合法 session |
| ACTIVE→PARTIAL/FILLED | 有合法成交，原量=累计成交量+剩余量（共同单位转换后）；部分成交剩余继续等待 |
| WAITING/ACTIVE/PARTIAL→EXPIRED | 普通订单达到 expires_at，剩余取消，已成交持仓不消失 |
| WAITING/ACTIVE/PARTIAL→CANCELLED | 新的反向意图冲突先取消旧余量，同时间戳 SELL 优先、再按 intent_id；保留 SUPERSEDED 关联 |
| CREATED/ACTIVE→REJECTED | 无法合法执行的数量/现金/身份错误，记录全意图分母与原因 |

FILLED/REJECTED/EXPIRED/CANCELLED 是终态，重试记录不重新生成信号。阻挡原因枚举：`NOT_AVAILABLE,T_PLUS_ONE,LIMIT_UP,LIMIT_DOWN,SUSPENDED,NO_BAR,CASH_INSUFFICIENT,SELLABLE_INSUFFICIENT,LOT_ROUNDING,EXPIRED,SUPERSEDED,UNIT_MAPPING_BLOCKED,STALE_MARK`。T+1 可卖量独立按 lot；跌停卖出当日禁止任意重试，下一市场交易日按冻结参考重评（Q7）；停牌/无 bar 不填造价。

M-REF 保留理想化参考标签；收盘后信号不能被宣称可在当日 close 因果成交。M-LAG 同根 close 事件禁止倒填该根 open。合法 session 开闭时点、bar 标签含义必须由冻结市场日历与分钟 metadata 证明（不得照搬旧 14:57 假设）；session 缺证据 INPUT_BLOCKED。high/low 不作触发。期末 `MARK` 只估值，不制造 SELL/佣金；保留最后估值日期及陈旧标记。

BT `orders/fills` 至少含配对键、intent/order/lot ID、状态/原因、可用/合法执行/实际成交时间、价格/价域、原量/当前单位量/累计成交/未成交/剩余量、费用/收费累计、实际现金/持仓/可卖量、数量事件、最后估值时间。费用 per_order 最低费对部分成交累计计费、只增量收取，不能每个 fill 重复最低费。买入受实际含费现金限制，卖出受实际可卖量限制；裁剪量和未成交原因记账，不向 MQ 反向修改意图。

## 8. 产物、指标与状态

MQ 路径 `exports/analysis/joint-return-v1/<run_id>/manifest.json|intents.csv|constraints.csv|pref_check.json`；BT 未来路径 `backtest_output/joint-return-v1/<run_id>/orders.csv|fills.csv|daily_nav.csv|summary.json`。run_id 仅字母数字开头及字母数字 `_ . -`，最长 96；目标目录已存在即拒绝。校验失败不创建成功产物；CLI stdout 给状态/原因、退出码 2。manifest 最后写，缺 manifest 的不完整目录不可消费。测试仅 tmp_path；真实数字宿主保存，不入 Git。

manifest 保存 §3 全部 metadata、输入文件/段 hash、artifact raw/content hashes、全表/分臂 intent hashes、初始状态和参考状态历史、配对范围。输出中的 `MQ_DATA_FREE_PASS` 仅合成工程通过，`input_status=SYNTHETIC_ONLY`；即使 frozen 快照数值门通过，原源文件 raw/PIT/覆盖未经宿主核验仍输出 `status=input_status=INPUT_BLOCKED` 与 `real_input_blockers`，不能交 BT 开跑或标绿。`execution_status=NOT_RUN`，return_status=待实测，不能以其代替联合 IMPLEMENTATION_PASS。

| 指标 | 固定定义 / 分母 |
|---|---|
| 目标换手（MQ 已输出） | `0.5*Σ abs(w_target-w_pre_drift)` 包括现金，同估值点；initial_build 单列 |
| 实际换手（BT 待实现） | 每日 `0.5*(买入额+卖出额)/调仓前净资产`；另报双边额/费用/现金/未成交；分母≤0 停止 |
| 回撤 | 完整共同日历净 NAV 的 `max(1-NAV/running_max(NAV))`；ΔMDD=处理−对照，正为恶化；期末持仓须 mark |
| 净超额 | `R_net=NAV_end/NAV_start-1`；ΔR_net=处理−同 fill/同资金 P-BASE，另报每日净收益差及配对不确定性；差序列不是可投资 NAV |
| 费用归因 | 现金持仓一次扣费产生净 NAV；滑点在价内；费用加回仅会计归因，不等于无费重跑 |
| 尾部与覆盖 | 低 anti 权重/行业集中/size 尾部需预定定义；订单数和数量成交率都以全意图为分母，缺码/缺分钟/停牌/现金不足/部分/过期/陈旧估值均保留 |
| benchmark | 主基准同 fill 的 P-BASE；共同宇宙等权用于主动暴露而非成交收益；市场指数须 P6 另锁分红域与版本 |

BT 最小 summary 必需 arm/fill/window/month、上述换手/回撤/净超额与分母、NAV/benchmark 版本、覆盖/缺失/不可行和语义限定；MQ 不预填这些真实指标。缺定义/缺台账为不可判。

全链状态继承：`INPUT_BLOCKED` 缺源/时点/参数；`PAIR_INVALID` hash/状态/现金/前视漂移；`SEMANTICS_BLOCKED` 单位/公司行动/PIT/价域不可证；`IMPLEMENTATION_PASS` 必须两仓串联 data-free 通过才可用；`NO_RETURN_SUPPORT`、`HISTORICAL_DIAGNOSTIC_ONLY`、`RETURN_RESEARCH_SUPPORTED` 仅未来真实回执使用。δ1 commission-only 不等于完整税费，δ2 股份缩放不等于现金分红；BT E-R5/NP2 适用性待正确性轨道处理，不因本刀而解除。
