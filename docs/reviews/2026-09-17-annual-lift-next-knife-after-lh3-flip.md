# 2026-09-17 · annual-lift 下一刀（T5-LH3 FLIP 之后）

**依据**：`2026-09-17-annual-lift-status-handoff.md`（尤其 §5、§7、§8、§11）、`2026-09-17-annual-lift-next-knife-codex.md`、`2026-09-17-t5-lh3-agent-runbook.md`

**性质**：只定一把刀、成功门和停手标签；本轮不写实现、不跑数、不重训、不改线上

**裁决**：选 **T6-SX0：非正预测退出**；本轮不选 T5 残部

**线上默认**：仍为 **10/3 LGB**，本页任何结果门都不授权改线上

## 0. 上一刀结果与新刀一句话

PR #75 的 T5-LH3 预检已在 `newtest_4090` 跑完，裁决为 **`LABEL_HORIZON_FLIP`**：

| 窗 / 切片 | 已发生的结果 | 判读 |
|---|---|---|
| 2025 valid | 三持有期候选 RankIC 更好，`ΔRankIC ≈ +0.012`；但候选 Top10 信号差比当前标签更差 | RankIC 与头部兑现已经分叉，S2 不过 |
| 2026 OOS | `ΔRankIC ≈ 0`，95% CI 穿 0；候选 Top10 信号差为负 | 没有 OOS 增量证据，且头部方向错误 |
| 2026 季度 | Q2、Q3 的 `ΔRankIC` 翻负 | 不是稳定的小正增量 |
| 已执行动作 | 标签周期路线停止；禁止再扫 h=2/4/5/10；禁止回 2026 扫闸；线上仍 10/3 | 失败即停已经兑现 |

PR #75 的 N1 修补已在 commit `dab1214` 落地：输出目录冲突检查前置到重计算之前。该修补只收紧运行安全，不改变上述研究 verdict。

**新刀一句话**：固定同一 `8a061ea4` 分、固定 `10/3` 且所有既有买入闸与价格型卖出规则全关；候选只增加一条独立卖出语义——持仓在当日可见的对齐预测分 `score <= 0` 时额外退出——与原 bottom=3 轮换做 2025/2026 配对比较。

## 1. 为什么 FLIP 后选 T6，而不选 T5 残部

### 1.1 T6 更直接回答当前问题

当前问题不是“还能不能找到一个单窗更高的格”，而是：**固定线上形态 10/3、现有闸全关以后，是否仍有单变量改动能在 2025 与 2026 同向抬升。**

T6-SX0 有三个直接优势：

1. **同 pred 即可配对。** 两臂都只读 `8a061ea428e04bb3a199a485ade49d0e` 及其同模型 2025 补分，不需要新模型、异 seed 或跨 recorder 拼数。
2. **不改 10/3 的入口定义。** `topk=10`、`n_drop=3`、`hold_thresh=1` 和所有买入候选排序都冻结；新刀只检验“模型已经明确给出非正预期时，是否应早于 bottom 配额退出”。
3. **直接接受现实成本检验。** 额外卖出可能增加换手，买 5bp / 卖 15bp / 最低 5 之后若仍能两窗同向胜出，才是与 10/3 兑现有关的证据；若被成本吃掉，也能一次关门。

这里的 `0` 不是从 OOS 挑出的参数。`8a061ea4` 是收益回归模型，零点就是“预测收益由正转为非正”的固定经济边界；本刀不试 `±ε`、分位数、rank 阈值或连续阈值。

### 1.2 本轮不选 T5 残部

| T5 残部 | 现有证据 | 为什么不是这一刀 |
|---|---|---|
| 泛化特征 | 已有 `turnover_resist_approx` 在短窗 `+0.138`、出窗 `-0.069` 的翻号；DropLimitUpLearn 也没有可直接晋升的头部名单证据 | 目前没有一列已经预注册、可不经筛选直接进入配对重训；此时开“特征”会先退化成候选挑选 |
| 行业 / 市值中性化 | M3-D 已做 raw/industry/size/both 两窗对照，长窗名单高重叠、命中未改善，短窗大改名单但命中原地踏步；默认保持关 | 没有新的跨窗“暴露导致头部损失”证据，重开就是换窗口复扫旧方法 |
| CYQ 特征化 | 现有正面线索主要来自宽名单与过滤语境；筹码映射又明确存在不可比边界。CYQ 进入模型前仍缺“已过过滤者内部、相近 pred 下的跨窗独立增量” | 它会产生新 pred，且当前证据不能直接回答 **10/3 全关**；先做它会混入特征定义、时点、缺失和重训四个变量 |
| 换 label / horizon | T5-LH3 已打 `LABEL_HORIZON_FLIP` | 路线已死；禁止再谈或改扫 h=2/4/5/10 |

因此，本裁决不是宣称所有新特征永久无效，而是认定：**在已有证据下，T6-SX0 比 T5 残部更能以同 pred、单变量、两窗配对直接回答本题。** T5 本轮不并行、不当备选臂；T6 失败后也不得自动回头开特征网格。

## 2. 具体刀法：T6-SX0 非正预测退出

### 2.1 对照与候选

| 项 | 对照臂 C | 候选臂 X |
|---|---|---|
| pred | `8a061ea4` | 与 C 完全相同 |
| 组合 | `topk=10`、`n_drop=3`、`hold_thresh=1`、`method_buy=top`、`method_sell=bottom` | 与 C 完全相同 |
| 买入闸 | buy-state / ST / 年龄 / 5日15% 全关 | 与 C 完全相同 |
| 价格型卖出 | 止损 / trail / 止盈全关 | 与 C 完全相同 |
| 新增语义 | 无 | 对可卖持仓，若当日对齐的有限 `score <= 0`，加入额外卖单，reason 固定为 `model_exit:nonpositive` |
| bottom 轮换 | 每日最多 bottom 3，原逻辑 | 原逻辑保留；SX0 额外卖出不占用、也不改写 bottom=3 配额 |

### 2.2 唯一允许的行为差异

买入日 `T` 仍只用基线本来可见的 `pred[T-1]` 截面分。候选臂按以下固定顺序生成一次当日计划：

1. 绑定开盘持仓和 `T` 日对齐分；禁止盘后标签、未来价格或当日未对齐分进入判断。
2. 先按原 10/3 bottom 算法得到基线 `buy_bottom` / `sell_bottom`。
3. 在开盘持仓中找出满足 `score` 有限、`score <= 0`、且已经满足原 `hold_thresh=1` / T+1 可卖约束的股票，记为 `sell_sx0`。
4. 候选卖单为 `sell_bottom ∪ sell_sx0`。同时命中时 reason 记 `model_exit:nonpositive`，并另列 `also_bottom=true`，以便把额外作用与原轮换分开记账。
5. 保持第 2 步已经生成的原 `buy_bottom` / `sell_bottom` 不变，再处理 SX0 多出来的空位；**禁止先做 SX0 再重跑 dropout**，因为那会改变 `comb` / 实际 `n_drop`。额外空位只能沿当日**全截面 scores sidecar**，从未持仓且非当日 `sell_sx0` 的代码中按 score 降序补到 10 只；买入宇宙不是 Top10 池文件。除禁止当日买回 `sell_sx0` 外不加任何买入过滤，尤其不得加 `score > 0` 或 `score <= 0` 不买的过滤；因此 X 仍可买入其他 `score <= 0` 的股票。只有 sidecar 合格名单耗尽，或现有成交核拒单，才允许留现金。
6. 涨跌停拒单、停牌、整手、资金和费用继续由现成交核处理；SX0 不另写一套成交规则。

缺分不是负分：持仓当日无有限 score 时，SX0 不触发，仍交给原 bottom 缺分确定序处理。`score == 0` 固定计入非正；不得加容差，也不得事后把阈值改为“略小于零”。

这是一条**模型判断失效的额外卖出**，不是把 `n_drop=3` 改大，也不是“跌出 Top10 就全清”。候选每日可以额外卖出多于 3 只；若这种语义带来的换手在现实成本后无益，本路线直接失败，不回头给额外卖出加数量上限。

## 3. 输入、两窗与六阶段参数卡

### 3.1 只用这套 pred、只看这两窗

| 窗 | pred 输入 | 成交窗口 | 身份 |
|---|---|---|---|
| 2025 | `my_scripts/预测结果_8a061ea4_2025valid.csv`；来自同一 `trained_model`，不重训 | `20250103`～`20251231` | valid / 早停已消费窗，只承担方向复核，不把高收益外推 |
| 2026 | recorder `8a061ea428e04bb3a199a485ade49d0e` 原 `pred.pkl` | `20260106`～`20260914`（169 池日） | OOS 测试窗；仍是已研究过的窗口，不伪装新盲窗 |

两窗各自在 C/X 之间做同窗配对；2025 与 2026 的绝对 NAV 不相加、不相乘。2024 不加作第三臂，本刀也不把 2026 切片冒充新窗口。

### 3.2 六阶段冻结卡

| 阶段 | 锁定值 |
|---|---|
| 训练 | LGB recorder `8a061ea428e04bb3a199a485ade49d0e`；train 2020–2024、valid 2025、test 2026；scaler 冻在 2020–2024；涨停出池开；DropLimitUpLearn 关；**本刀不训练** |
| 出分 | 2026 只读 recorder 原 `pred.pkl`；2025 只读同模型补分 CSV；`pred_minus_one` / shift=1；不覆盖、不回写、不另造异 seed pred |
| 组合 | 10/3、`hold_thresh=1`、top/bottom；C 为原语义，X 只叠 SX0；不扫宽度、`n_drop`、hold 或 score 阈值 |
| 买入闸 | buy-state / ST / 年龄 / 5日15% 全关；不得因 SX0 结果重开任何一项 |
| 成交回测 | 只在 MyQuant-backtrader 的独立策略书表达 SX0，禁止塞进成交核；qlib `$close` 后复权 bin、买5bp/卖15bp/最低5、拒单0.095、不追买、整手向下、本金1e8、`risk_degree=0.95`、SH000300；BT 不 import qlib |
| 线上 | 仍为 10/3 原策略；即使成功也只获得“候选”标签，不自动改线上卖点或 pred |

## 4. 明确冻结与禁区

本刀执行期间，以下项目全部冻结：

- **线上 10/3 不动**；不把研究候选当线上默认，不改生产卖点。
- **不覆盖 pred**：`8a061ea4` / `55c5bf77` 的 `pred.pkl`、已有 CSV、分析包和回测目录均只读；新产物必须另开目录。
- **标签周期路线已死**：不再换 label，不扫 horizon，明确禁止 h=2/4/5/10。
- **不回 2026 扫旧旋钮**：不扫闸、止损、trail、止盈、宽度、`n_drop`、hold、买入状态或 15% 阈值。
- **不重开已不建议路线**：不换树模型，不做月度滚动，不做 per-fold scaler，不重开 20/3，不把“关 15%”升默认，不做 9×11G handler 重建。
- **不夹带 T5 残部**：不同时加特征、中性化、CYQ、训练宇宙或 DropLimitUpLearn；否则无法归因给 SX0。
- **不改尺子**：不换湖价、前复权、成本、ST 表、年龄规则、代码规范、缺分排序、涨跌停或整手语义。
- **不跑 PortAna 来替代 T6 卖出语义**：本刀是策略书额外卖出，主比较必须在同一 BT 成交核内完成；不得把 PortAna C 与 BT X 相减。

## 5. 成功判据与失败标签

### 5.1 固定输出

每个窗口必须同时给 C/X 两臂的输入 hash、池日数、末值、区间收益、扣费年化超额、最大回撤、买卖笔数、换手、总费用，并单列：

- `model_exit:nonpositive` 次数、涉及交易日数、其中 `also_bottom` 次数；
- SX0 卖出后同日补位数、留现金日数、涨跌停/停牌拒单数；
- gross（零费用，仅作成本归因）与 locked cost（5/15bp/最低5，唯一判胜口径）的 C/X 差；
- 按自然季度的 `ΔNetReturn = NetReturn(X) - NetReturn(C)`，只作稳定性检查，不据此挑季度。

gross 固定为各臂 locked-cost 回放的**同一成交序列费用记零**后重算，不得另跑一次零费率撮合；否则成交序列变化会混入成本归因。

2026 的配对日收益差固定用 5 交易日 moving-block bootstrap、10,000 次、seed `20260917`，报告 `ΔNetReturn` 的 95% CI。不得看到结果后改 block 长度、次数或 seed。

### 5.2 成功：四门全过

| 门 | 预注册判据 |
|---|---|
| S0 · 语义隔离 | C/X 输入 hash 相同；X 相对 C 的策略差异只有 SX0；所有新增卖出均可由 `score <= 0` 复算，bottom 与 SX0 reason 可分账 |
| S1 · 两窗同号同排序 | 2025、2026 均满足 locked-cost `NetReturn(X) > NetReturn(C)`，即两窗 `ΔNetReturn > 0`；同基准下扣费年化超额排序也必须 X>C |
| S2 · OOS 证据 | 2026 配对 `ΔNetReturn` 的 5 日 block-bootstrap 95% CI 下界 `> 0` |
| S3 · 时间稳定 | 2026 季度 `majority_negative=false` 且 `single_quarter_driven=false`；不能靠一个季度抬起全窗 |

S3 的口径锁死如下，不得由执行者另作解释：

- 季度按成交日的自然季度 `Period('Q')` 切分；2026 必须保留不完整 Q3（`2026-07-01`～`2026-09-14`），不得丢弃，也不得补齐或外推到 9 月 30 日。
- 全窗和逐季度统一使用 locked-cost `ΔNetReturn = NetReturn(X) - NetReturn(C)`；gross 不参与 S3。
- `majority_negative = (季度数 > 0) and (ΔNetReturn < 0 的季度数 / 季度数 > 50%)`。
- `single_quarter_driven = (季度数 >= 2) and (全窗 ΔNetReturn > 0) and (ΔNetReturn > 0 的季度数 <= 1)`。

四门全过才打 **`SCORE_EXIT_CANDIDATE`**。它只表示“固定 10/3 全关时，SX0 在已观察的两窗给出同向增量”，不表示拿到新盲窗、可以上线或可以把 2025 收益当目标。

### 5.3 失败：按下列优先级打标签，任一失败即停

| 优先级 | 标签 | 条件 | 动作 |
|---:|---|---|---|
| 1 | `SCORE_EXIT_FLIP` | 2025/2026 的 locked-cost `ΔNetReturn` 反号，或 2026 `majority_negative=true` | 判为窗口或时段依赖；停止，不切强/弱窗或季度挑冠军 |
| 2 | `SCORE_EXIT_COST_ERASED` | 未命中优先级 1，gross 的 X-C 在两窗均为正，但 locked-cost 的 S1 任一窗不过 | 额外换手不值成本；停止，不改卖出数量、冷却期或费用假设 |
| 3 | `SCORE_EXIT_NO_EDGE` | 未命中优先级 1/2 且没有跨窗反号，但 S1/S2 任一不过、`single_quarter_driven=true`，或 `model_exit:nonpositive` 覆盖交易日数为 0 | 判为无可兑现增量；停止，不把零阈值改成 rank/分位/`±ε` 网格 |

上述优先级就是唯一裁决梯，确保失败标签互斥；“单季驱动”不得称为“翻转”。运行或实现错误不得手写研究 verdict，只能标为操作失败并修复同一固定语义。任一门失败即停，不得改阈值、卖出数量、季度切法或窗口，也不得滑参数网格；无论成功或失败，跑完即停，禁止转扫 trail、止盈、止损、horizon、宽度或 `n_drop`。

## 6. 后续复现命令草案（本轮禁止执行）

下面只是后续实现 / 宿主 agent 的接口草案。当前仓和当前 PR **不实现** `topk_score_exit`，也**不运行**以下命令；候选策略必须另开实现 PR，并保持 `topk_dropout` 对照书不变。

先从原 pred 向两个新目录导出 Top10 与全截面 scores sidecar；`<EXPERIMENT_ID>` 只允许替换为本机现有 `alpha158_cost_kdj_lgb` 的实际 MLflow 实验目录，不得指向其他 recorder：

```powershell
Set-Location D:\PycharmProjects\MyQuant
$py = "D:/anaconda3/envs/vanna312/python.exe"
$pred2025 = "D:\PycharmProjects\MyQuant\my_scripts\预测结果_8a061ea4_2025valid.csv"
$pred2026 = "D:\PycharmProjects\MyQuant\my_scripts\mlruns\<EXPERIMENT_ID>\8a061ea428e04bb3a199a485ade49d0e\artifacts\pred.pkl"

& $py -u my_scripts/export_daily_pool.py --pred $pred2025 --topk 10 --asof pred_minus_one --out-dir exports/t6_sx0_8a061ea4_2025_20260917
& $py -u my_scripts/export_daily_pool.py --pred $pred2026 --topk 10 --asof pred_minus_one --out-dir exports/t6_sx0_8a061ea4_2026_20260917
```

再在同一成交核中做四次配对回放。C/X 每臂和每窗都使用独立新目录；候选 CLI 名 `topk_score_exit` 是本任务预注册的未来接口，不得用现有止损 / trail 参数冒充：

```powershell
Set-Location D:\PycharmProjects\MyQuant-backtrader
$py = "D:/anaconda3/envs/vanna312/python.exe"
$qlibRoot = "C:\Users\wangc\.qlib\qlib_data\my_data"
$pool2025 = "D:\PycharmProjects\MyQuant\exports\t6_sx0_8a061ea4_2025_20260917"
$pool2026 = "D:\PycharmProjects\MyQuant\exports\t6_sx0_8a061ea4_2026_20260917"

& $py -u backtest/research/csv_daily_backtest.py --strategy topk_dropout --start 20250103 --end 20251231 --pool-dir $pool2025 --scores-dir "$pool2025\scores" --topk 10 --n-drop 3 --stop-pct 0 --cash-total 100000000 --daily-quota 100000000 --qlib-data-root $qlibRoot --qlib-cost --out-dir backtest_output/t6_sx0_control_2025_20260917
& $py -u backtest/research/csv_daily_backtest.py --strategy topk_score_exit --start 20250103 --end 20251231 --pool-dir $pool2025 --scores-dir "$pool2025\scores" --topk 10 --n-drop 3 --stop-pct 0 --cash-total 100000000 --daily-quota 100000000 --qlib-data-root $qlibRoot --qlib-cost --out-dir backtest_output/t6_sx0_candidate_2025_20260917

& $py -u backtest/research/csv_daily_backtest.py --strategy topk_dropout --start 20260106 --end 20260914 --pool-dir $pool2026 --scores-dir "$pool2026\scores" --topk 10 --n-drop 3 --stop-pct 0 --cash-total 100000000 --daily-quota 100000000 --qlib-data-root $qlibRoot --qlib-cost --out-dir backtest_output/t6_sx0_control_2026_20260917
& $py -u backtest/research/csv_daily_backtest.py --strategy topk_score_exit --start 20260106 --end 20260914 --pool-dir $pool2026 --scores-dir "$pool2026\scores" --topk 10 --n-drop 3 --stop-pct 0 --cash-total 100000000 --daily-quota 100000000 --qlib-data-root $qlibRoot --qlib-cost --out-dir backtest_output/t6_sx0_candidate_2026_20260917
```

输出目录若已存在，执行器必须拒绝覆盖并换一个新戳目录；禁止删除旧目录后复用。命令中没有 ST/年龄/15%/buy-state 参数，没有价格型卖出参数，也没有第二个 score 阈值。

## 7. 两本账的永久边界

| 账 | 本刀允许回答 | 永久不允许 |
|---|---|---|
| 线上导向 10/3 账 | 同 `8a061ea4`、固定 10/3 全关时，SX0 相对原 bottom 轮换能否在 2025/2026 同号同排序、且 2026 配对 CI 过门 | 不能因两窗成功直接改线上；不能把 2025 valid 高收益外推；不能借 SX0 改 topk、`n_drop` 或买入闸 |
| 50/5 研究账 | 继续用于现尺子对齐、机制归因和历史审计 | **不得**把 50/5 的 NAV、+23.1%/+29.3% 超额、15%/20% 止损峰值或 CYQ/过滤语境搬来修改线上 10/3；不得与本刀 C/X 做数值加减 |

最终立场：**这把刀只回答“固定 10/3 全关后，模型非正预测是否构成可迁移的额外卖出信息”。** 50/5 研究账无论净值多高，都不能改变本刀的基线、成功门或线上边界。
