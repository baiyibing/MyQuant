# Joint return v1：R0 合同 / R1 MQ 快照接口

状态：本刀交付 R0 与 MQ R1 data-free；BT R1 下一刀。真实输入 `INPUT_BLOCKED`，分钟链 `NOT_RUN`，新收益、成交率、滑点与 Sharpe 均待实测。

SSOT：[联合实施计划](../2026-09-19-joint-return-implementation-plan.md) §3、R0/R1、F-R2–F-R12；来源与缺口见 [input-register](input-register.md)，门禁见 [acceptance](acceptance.md)。本次用户澄清优先于旧计划：原始 10/3 从未实盘、程序未上线，只有回测，不存在线上原始意图包。禁止要求 live `frozen_original_intents`；来源改为显式回测规则生成。研究默认 50/5（仓内实验积累最多），20/3、10/3 可切换；这是研究默认，不改线上 10/3 配置，也不表示线上已经运行。旧计划中硬锁研究 10/3、等待原始意图包的要求作废，其余生产隔离边界继承。

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

本次回测规则适配 MQ 白名单：

- `docs/reviews/joint-return-v1/contract.md`
- `docs/reviews/joint-return-v1/input-register.md`
- `docs/reviews/joint-return-v1/acceptance.md`
- `my_scripts/joint_return_contract.py`
- `my_scripts/joint_return_portfolio.py`
- `tests/test_joint_return_portfolio.py`
- `my_scripts/joint_return_freeze_snapshot.py`
- `my_scripts/joint_return_rule_intents.py`
- `my_scripts/joint_return_merge_scores.py`
- `tests/test_joint_return_freeze_snapshot.py`
- `tests/test_joint_return_rule_intents.py`
- `docs/reviews/joint-return-v1/host-frozen-snapshot-checklist.md`

BT 下一刀拟白名单：`backtest/research/joint_return_replay.py`、`scripts/research/run_joint_return_replay.py`、`tests/test_joint_return_replay.py`。本刀不写 BT 文件。sibling 工作区 HEAD `41f3d11a34c665cc8a21b3e1d351b9e06b0466b5` 仅作差异登记，事实按固定 BT 对象读取；不 checkout/pull。后续 R2–R6 另行派工，不在此白名单。

运行 manifest 必填 MQ/BT 两个实际 40 位 `code_shas` 和上述两个 `implementation_bases`；合成 fixture 使用基线 SHA 仅演示字段，不能冒充实际运行提交。实际提交由本地 Git commit 与 handoff 登记；本次禁止 push、PR、评论。后续宿主回执另行登记，文档不自引用自身提交 SHA。

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
| `strategy{topk,n_drop,source,rule_version,rule_parameters,eligibility_version,eligibility_rules,native_stop}` | 正整数 topk、0≤n_drop≤topk 整数；默认研究 50/5，覆盖 20/3、10/3；`backtest_rule_intents`、`topk-dropout-reference-v1`、下述规则参数、资格版本与非空闸门定义、`N/A`。bool/浮点数不当整数，不得猜 ST/年龄/涨幅资格 |
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

### 4.1 scores 显式合并

入口 `python -m my_scripts.joint_return_merge_scores --control PATH --universe PATH --anti PATH --labels PATH --output-dir NEW_DIR`。四个输入均为 JSON 行数组，键是 `(date,instrument)`，不自动改名/转换类型/补时间；每文件重复键、必需列缺失均 INPUT_BLOCKED。

| 输入 | 除 date/instrument 外的必需列 |
|---|---|
| control | `score,score_available_at,source_version,recorder_id`，recorder_id 必须是完整 control ID。 |
| universe | `candidate_present=true,recorder_id`，recorder_id 为完整 candidate ID；这是**预先核验的共同宇宙**，只含成员信息，不能有 score。 |
| anti | `anti_rank,anti_available_at,source_version,source_sha256`，source_sha256 是 §1 原 sidecar 的来源声明，不是转换后的 JSON 字节 hash。 |
| labels | `label,source_version`；整日无 label 用显式 null，不能省行/省列。 |

以 universe 为完整分母，逐键要求其他三表覆盖，禁止 inner join 丢缺失行；额外的 control/anti/label 键在 `merge-manifest.json.coverage.outside_common_keys` 完整记录。candidate scores 禁止进入任何表。输出 `scores.json` 维持 §4 必需列，保留 control recorder、anti/label 版本和原 sidecar hash 声明；按固定顺序输出，数值不重算。部分 label 缺失阻塞，全日 null 保留。输出 manifest 冻结四输入 URI/双 hash 和完整日历；上游 recorder/sidecar/PIT 真实性仍需核验，因此 status=SCORES_MERGED 也不把 input_status 从 INPUT_BLOCKED 改绿。

## 5. 回测规则意图与各臂参考状态

原始 10/3 **从未实盘、程序未上线，只有回测**。不存在可索取的 live frozen_original intents。本合同唯一接受 `source="backtest_rule_intents"`；旧 `frozen_original_intents` 与 `PortAna_positions` 均拒绝。生成器从 control scores、显式研究初态和逐日市场/资格输入生成计划，绝不由 PortAna 最终仓位、成交或线上订单倒推。

入口 `python -m my_scripts.joint_return_rule_intents --scores PATH --initial-state PATH --sessions PATH --metadata PATH --output-dir NEW_DIR [--topk 50 --n-drop 5]`。默认 50/5；20/3、10/3 必须同时给两个开关。metadata 若已登记 topk/n_drop，必须与 CLI 一致，否则 INPUT_BLOCKED，不静默改写。生成新的 `plans.json,metadata.json,rule-manifest.json`；输入文件不改，输出目录不覆盖。输出 metadata 的 plans 声明含本次规则输入的 URI/双 hash 与策略 hash，其余 section 声明保留；scores/initial_state 的预登记 URI/双 hash 必须匹配文件。

### 5.1 规则来源和明确边界

复用 Qlib `TopkDropoutStrategy` 的 top/bottom 研究选股核心。仓内调用证据：`my_scripts/custom_train_backtest.py`、`my_scripts/replay_2025_st_age_vs_15.py`（50/5）、`my_scripts/replay_10n3_two_year.py`（10/3）；规则源码核对 Qlib commit `79633dd9506ea689e5400dea0197717b5b3d74b7` 的 `qlib/contrib/strategy/signal_strategy.py`。运行时不 import Qlib/Exchange/PortAna，不调用回测或真实撮合。

`rule_parameters` 必须显式给且仅含：`method_buy="top",method_sell="bottom",only_tradable=false,hold_thresh`（非负整数）、`risk_degree`（[0,1]）。仅 topk/n_drop 有研究 CLI 默认；持有门槛、资金、费用、风险比例和资格配置不从旧脚本猜值。`eligibility_rules` 登记实际来源规则，market 中提供其可得时点和逐只判定；本适配不实现 ST/年龄/涨幅数据加载器，也不声称复现仓内所有 Filter 子类。

每日、每臂按以下顺序递推：

1. scores 按 `score desc,instrument asc` 排序。`today` 为未持有股票的前 `n_drop+topk-held_count`；旧仓与 today 合并排序，旧仓中落在合并榜尾 n_drop 的进入卖出候选。不是每天强卖 n_drop，也不是每天重新等权 TopK。n_drop=0 明确不卖出。
2. 卖出还需显式 `sell_eligible=true` 且该臂持有交易日数≥hold_thresh。拒绝的候选留仓并记录原因。为遵守本合同 topk 上限，可买槽位=`min(len(today),批准卖出数+topk-held_count)`；**不借用拒绝卖出的槽位**。这是参考意图适配的明确约束，与 Qlib 先按候选卖出数算 buy 列表的实现有区别，不声称逐笔成交等价。
3. 批准卖出按共同参考价、完整 lot 及显式研究费更新参考现金；每个买入槽位预算=`卖后现金*risk_degree/slots`。target_weight=预算/调仓前 NAV，数量=`floor((预算+1e-8)/参考价/100)*100`。不暗调费率、风险比例或缩单；实际选中的含费现金不足则 PAIR_INVALID。
4. P-BASE 只在 today 的前 slots 中保留显式获准且整手数量>0 的买入，不因资格拒绝另行提升后排。所有非持仓候选均提供显式资格；零整手/无槽位记录到 rule_trace 和 constraints 的 `RULE_BUY_BLOCKED`，不造零量订单。
5. P-CHASE 在该臂自己的规则基线上，只替换低于每日 **Top10 T0** anti 中位数的新买，合格候选按 score 补足，必要时记录放宽；资格绝不放宽。P-REF/anti 阈值的 Top10 是既有诊断口径，与研究持仓 topk 分开，50/5 不将它改成 Top50。
6. 每臂用自身 SELL→BUY 参考结果递推下一天，持有交易日数也各自递推；新买到下一交易日计 1，旧仓每个显式市场 session 加 1。实际 M-REF/M-LAG fills 不反馈选股。持仓不得超过所选 topk，买入可补前日空槽，不能硬限所有非空仓日最多 n_drop。

缺旧仓 score 直接 INPUT_BLOCKED，不沿用 Qlib NaN 排尾；稳定 instrument ties 明确锁定。以上差异都是版本 `topk-dropout-reference-v1` 的定义，不得把本参考账本说成历史原始成交记录。

### 5.2 初态与 sessions 必需列

`initial_state` 是显式研究起点：`cash`（CNY，非负）、`positions`（instrument→`quantity,lot_id,instance_id,holding_days`）、`quantity_unit="share"`、`native_stop="N/A"`。非空初始仓的 holding_days 必须显式提供，是第一决策时点已持有的交易日数；后续年龄在每臂 rule_trace 中记录。允许显式现金空仓起步，不要求真实/线上账户；不自动继承旧现金池。数量正、lot 唯一、持仓数≤topk。参考路径与 fill 账本分离。

`sessions.json` 顶层行数组；日期集合必须恰好等于 metadata.calendar，不能删失败日。每行必需：

| 字段 | 定义 |
|---|---|
| `date,decision_at,available_at,effective_at,expires_at,mark_at` | 日期与五个显式时点；mark≤decision≤available≤effective<expires。score/anti/资格须在 decision 可得；日期不自动 shift。同根收盘信号不授权同根 open；后续 M-LAG 使用可得时点后的合法 open。 |
| `price_domain,source_version,eligibility_version` | none、非空市场来源版本、与 strategy 一致的资格版本。 |
| `market` | 每只当前 score 股票及旧仓的显式价格/证券映射/资格行；不够即 INPUT_BLOCKED。 |
| `corporate_actions` | 显式空列表；非空 SEMANTICS_BLOCKED，不可删掉真实事件过门。 |

market 每行必须有 `instrument,execution_symbol,reference_price,buy_eligible,buy_reason,sell_eligible,sell_reason,eligibility_available_at`。价格为 mark_at 的 none CNY/share；资格布尔值和非空原因均不可省略，资格发布时间不得晚于 decision。映射跨日唯一且不能漂移，价格不能从未来成交拿来。资格在时点上的可证性仍需宿主验证。

### 5.3 生成计划与递推校验

portfolio calendar 每日有 P-BASE/P-CHASE 两条 plan，无交易也有空计划：

| 字段 | 定义 |
|---|---|
| `date,arm_id,source,pre_state_hash` | 日期、臂、backtest_rule_intents、本臂上次参考状态 hash；不能用 BASE 重置 CHASE。 |
| `decision_at,available_at,effective_at,expires_at,marks,mark_at` | 从上述显式 session 复制；marks 是参考价表。 |
| `sells` | 完整数量字段 + `approved,approval_reason`；候选数量≤n_drop，只退出完整 lot。 |
| `buys` | 规则获准新买 instrument 有序列表，填充批准卖出后及原有空槽，最终持仓≤topk。 |
| `buy_candidates` | 每只非持仓且数量>0 的候选，完整数量字段 + `eligible,eligibility_reason`；CHASE 回填量由自身参考预算独立生成。 |
| `corporate_actions` | 显式空列表。 |
| `rule_version,strategy_hash,rule_trace` | 生成器证据：规则版本、完整策略 hash、session/scores 内容 hash、持有年龄、排序候选、零量拒绝原因；freeze 与 portfolio 拒绝策略 hash 漂移，portfolio 还校验排序后 scores hash。 |

数量字段为 `instrument,execution_symbol,instance_id,lot_id,target_weight,original_target_quantity,reference_price,reference_price_at,quantity_unit,quantity_conversion`。新 lot 身份由规则版本/臂/日期/证券/前态 hash 确定；SELL 量/lot 与持仓完全相同、weight=0。BUY 不加到旧仓；original_target_quantity 是**规则冻结的原始订单量**，不是存在过的线上原始订单。

portfolio 验证来源、参数、数量转换、独立前态、现金、topk 上限和风险预算，manifest 保留完整 before/after、plan、hash、漂移/目标权重、目标换手及研究参考费。基础 plan 结构仍可用于手算合成 pins；真实来源须留存生成器回执和上游输入，不能把填入 source 字串本身当成来源证明。生成器不运行 P-REF；freeze 后 portfolio 仍执行原 expected hash/窗口/数值门禁。

## 6. 输出意图、数量与公司行动

`intents.csv` 的固定列顺序：

```text
arm_id,intent_id,instance_id,lot_id,instrument,execution_symbol,decision_at,available_at,side,target_weight,original_target_quantity,quantity_unit,quantity_conversion,reference_price,reference_price_at,reason,reference_state_hash,source_plan_hash,effective_at,expires_at,retry_policy,conflict_policy,expiry_policy,native_stop
```

`quantity_unit="share"`、`quantity_conversion="SNAPSHOT_FIXED"`。新买 100 股整手；审计已提供数量是否等于 `floor(target_weight*reference_NAV/reference_price/100)*100`，不改写它；卖出允许退出原有零股/小数 lot。比较现金/转换金额绝对容差 `1e-8` CNY，只消除浮点噪声，不允许融资。费用以 CNY 计、滑点未来通过成交价进入，不二次扣除。reference cost/peak/stop 均 N/A，不向任一研究参数组添加 r2/Livermore/WRD1。

公司行动转换未来 BT 单独记 `event_id,instrument,available_at,effective_at,from_unit,to_unit,original_quantity,factor,current_quantity,source_hash,price_domain`，所有配对共用同一事件；保留原始数量，未完成订单也须换算。Mode B shares÷k 的 factor=1/k，允许小数旧仓；这不表示现金分红入账或真实总回报守恒。映射/PIT/域不可证则 SEMANTICS_BLOCKED，绝不把转换伪装成选股差异。本刀 MQ 遇显式事件即阻塞，公司行动执行验收留给 BT；真实运行前必须证明无漏事件。

`constraints.csv` 列 `date,arm_id,instrument,status,reason,score,anti_rank,t0_median,reference_state_hash`，状态包含上述 skip/backfill/relax、`ELIGIBILITY_BLOCKED`、`KEEP_UNAPPROVED_SELL`、`KEEP_OLD_POSITION`、`INTENT_EMITTED`；已冻结基础计划可用 null 表达无 score 旧仓；本规则生成器要求旧仓 score 齐备，否则 INPUT_BLOCKED。

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
