# 任务书：TopkDropout 轮换进主回测 + ST/年龄/止损叠层

- 日期：2026-09-16
- 状态：**✅ 已人裁 GO（v1.0）**。编码只按切片进行；成交核默认路径禁止改行为。
- 风险档：中（策略书新增；成交核 / 6/8 默认卖点不动）
- 人裁：2026-09-16 宿主会话，P-1～P-6 按草案建议全部 GO（见 §4）。未跑多路独立评审；不另开 review 目录。
- 工作流：本仓 `docs/pipeline-collab-2026-09-13.md`；主回测权威副本 + 交接页：
  `MyQuant-backtrader/docs/backtest/plan-topk-dropout-overlay-2026-09-16.md`
  `MyQuant-backtrader/docs/backtest/handoff-topk-dropout-overlay-codex-impl-2026-09-16.md`
- 业务源：2026-09-16 对话——Cat 名单先跑通；本仓只打分出 TopK；主回测用 qlib 同款淘汰算法（对着**实仓**现算），再叠 ST / 年龄 / 10% 成本止损。
- 上游锚：qlib `TopkDropoutStrategy`（`qlib/contrib/strategy/signal_strategy.py`，`method_buy=top` / `method_sell=bottom` / `hold_thresh=1`）；本仓训练默认即此（`custom_train_backtest.py`，未开 `--buy-state-filter`）。
- 已有产物（不过闸）：`exports/cat_50_raw_20260105_20260914/`（Cat `51dde0bc`，`--topk 50 --asof pred_minus_one`，169 日）。全截面分：`my_scripts/预测结果_20260915T131732Z_51dde0bc_50n5.csv`。
- 线上默认：**10/3 LGB 不动**。不覆盖 `8a061ea4` pred / 原分析包。

---

## 0. 一句话

本仓继续只交**日分 + TopK 名单**。主回测策略书里实现 qlib 的 TopkDropout（对**本引擎持仓**现算买/卖），再叠 ST/年龄（新开拦截、沿序补）和 10% 开仓价止损（额外卖）。不 import qlib，不吃 `live_pool/*sell.csv`，不把 n_drop 写进成交核，不和 PortAna NAV 对一个数。

```text
MyQuant                         MyQuant-backtrader
全日截面分 + 日 TopK CSV   →    策略书：TopkDropout(实仓, 当日分)
                                + ST/年龄 新开闸（沿序补满 topk）
                                + 止损额外卖（空位再按序补）
                                成交核：T+1 / 跌停 defer / 整手（已有）
```

---

## 1. 定位（钉死）

| 问 | 答 |
|---|---|
| 本仓交什么 | 打分；`export_daily_pool.py` 日 TopK（裸六位，`pred_minus_one`）；**另交全日分**（见 MQ-A）。不出计划卖出。 |
| 主回测底座 | 与 qlib 相同的淘汰**规则**，输入 = 当日截面分 + **本引擎当前持仓**。 |
| 附加规则 | ST PIT、上市年龄 ≥60：只挡**新开**；止损：开仓价 `pos.cost`，盘中最低碰到 10% 则卖（分钟为准），跌停 defer，T+1 当天新买不卖。 |
| 止损与轮换 | 止损卖掉、次日仍在序且过闸 → **允许再买**。不要和「跌出榜才卖」合成一条。 |
| 6/8 默认 | **不改**。本任务是新开一本薄书 / 新 strategy 名，不是把 v6 的 6% 改成 10%。 |

资金配给计划 **R-5**（「禁止把 dropout 复刻进引擎」）改为：**禁止进成交核、禁止 import qlib**；**允许在策略书里实现**。这是策略，不是复刻 PortAna。

---

## 2. 淘汰算法（实现者必须按这个，禁止「CSV 里没有就清」）

符号：`topk=50`，`n_drop=5`，`hold_thresh=1`。当日 `pred_score` = **买入日对应的上一预测日**全市场分（与 qlib `shift=1` / 本仓 `pred_minus_one` 同口径）。

1. `last` = 当前持仓代码，按 `pred_score` 从高到低。缺分的持仓：实现时标 `score_missing`，**不得 silently 当 0**；预锁建议：缺分视为极低分并计数，不得因此多卖超过 `n_drop`。
2. `today` = 未持仓票里分最高的 `n_drop + topk - len(last)` 只。满仓时 = 5 只新票。
3. `comb` = `last ∪ today`，按分排序。
4. `sell` = `last` 中落在 `comb` **最差 `n_drop` 只**里的那些（`method_sell=bottom`）。防止「卖掉分更高的、买进分更低的」。
5. `buy` = `today[:len(sell) + topk - len(last)]`。
6. 持有 bar 数 `< hold_thresh` 的不进卖单（T+1）。涨跌停可卖性交给引擎，策略不要再写一套。

满仓且已是真·前 50：`today` 为第 51–55 名，`comb` 最差 5 只都是新票 → `sell ∩ last = ∅` → 当天不换。

**禁止**：把「今日 TopK 文件里没有的持仓全部卖掉」。那比 50/5 狠，对不上 qlib。

**禁止**：用 `exports/live_pool/20260916_sell.csv` 或任何静态 sell 作为多日回测输入。那份是 LGB 纸面仓的一日近似，叠止损后第二天就歪。

`export_next_day_pool.plan_rebalance`（榜外最弱 n_drop）只是满仓时的近似，**单测对的是上面 1–6，不是 plan_rebalance**。

### 2.1 为什么 TopK 名单不够、必须有全日分

官方算法要给**当前持仓**打分，包括已掉出 Top50 的票。只有 50 个裸码无法排序 `last` / `comb`。因此 MQ-A 必须提供买入日对齐的全日分（或至少「当日 TopK ∪ 当前可能持仓」的分）。烟测可用已有 `预测结果_*51dde0bc*.csv`。

---

## 3. 切片

实现者只做任务书列出的片。跨仓：MQ 片在 MyQuant 开 `feat/topk-dropout-overlay`（或 `docs/` 若只动文档/导出）；BT 片在 MyQuant-backtrader 开 `feat/topk-dropout-overlay`。不要一个 PR 改两个仓。

| 片 | 仓 | 内容 | 验收 |
|---|---|---|---|
| **MQ-A** | MyQuant | `export_daily_pool.py`（或旁路）写出**全日分 sidecar**：`exports/<run>/scores/YYYYMMDD.csv`，文件名 = 买入日 T，内容 = 用于 T 的那一截面分（`pred_minus_one`：pred[T−1]）。列：裸六位码、score。LF 无 BOM。池目录仍是每日 TopK 裸码，契约不变。默认**不过** ST/年龄。 | 单测：已知 2 日 pred → 1 个买入日 scores 文件，行数 = 该 pred 日票数；与 TopK 文件同一 `asof`。不覆盖 `cat_50_raw_*`。 |
| **BT-A** | backtrader | 新策略书（建议名 `topk_dropout` / `version_topk`，**不要叫 version11 去复刻 Qlib**）：实现 §2。读 `--pool-dir` 仅作 TopK 便利；**排序与淘汰以 scores sidecar 或 `--pred-csv` 为准**。不改 `csv_simulate_loop` 成交核。 | data-free 单测：§2.2 三组合成账必须字节级对齐期望 buy/sell。`pytest tests/` 绿。 |
| **BT-B** | backtrader | 新开闸：ST PIT + 年龄 ≥60。只过滤 `buy` 候选；不够 `len(buy)` 则沿 `pred_score` 未持仓序往下补（仍排除已持仓、已 ST、未满龄）。**不**因变 ST 而在本片强制卖（那是持仓闸，另立项）。 | 单测：Top 新票是 ST → 买下一只非 ST；持仓变 ST 本片仍留仓（除非进了 §2 的 sell）。 |
| **BT-C** | backtrader | 叠 10% **开仓价**止损：盘中最低 ≤ `cost * (1-0.10)` 按触发价卖；开盘已在触发价下 → `stop_loss:gap_open` 按开盘卖。跌停 defer、T+1 当天新买不卖（用引擎现锁，不另写）。空位次日走 §2 + BT-B 再补。 | 单测：合成 K 线触价 / 缺口 / 跌停延期 / T+1 当天不卖。与 v6 的 6%+trail **分文件**，禁止改 v6 默认阈值冒充本片。 |
| **H-1** | 宿主 | 用 `exports/cat_50_raw_20260105_20260914` + MQ-A 分（或现成 pred CSV）跑同一窗：臂0=仅 BT-A；臂1=A+B；臂2=A+B+C。 | 只比名单重叠、`reason`、可卖、涨跌停。**禁止**与 qlib PortAna 超额/NAV 合成一个数。数字不入库 git。 |

### 3.1 BT-A 合成账（必须写进单测）

账 1 — 满仓真前 50：持仓 = 分最高 50；`today` = 51–55 → sell∩last 为空，buy 为空。

账 2 — 满仓含 5 只狗：持仓 = 前 45 + 分最低的 5 只；`today` = 被挤出的前 50 里那 5 只 → sell = 5 只狗，buy = 那 5 只。

账 3 — 未满仓（持 40）：`today` 长度 = 5+50-40 = 15；sell 仍最多 5（comb 最差 5 且属于 last）；buy 长度 = len(sell)+10。

---

## 4. 人裁点（GO 前逐条勾）

| ID | 问题 | 草案建议 | 人裁 |
|---|---|---|---|
| **P-1** | n_drop 放哪 | 策略书，不进成交核 | **GO** |
| **P-2** | 本仓是否出 sell CSV | **否**。只出分 + TopK | **GO** |
| **P-3** | ST/年龄放哪 | 主回测新开闸（BT-B），本仓导出不过闸 | **GO** |
| **P-4** | 止损语义 | 开仓价 10%、盘中最低、gap_open、跌停 defer、T+1 当天不卖。不是 v6 改 6→10，也不是从最高价回撤（那是 v8） | **GO** |
| **P-5** | 止损后次日仍在序 | 允许再买 | **GO** |
| **P-6** | 第一份烟测名单 | 用已有 Cat raw Top50，不过闸；LGB `8a061ea4` 平行名单本任务不强制 | **GO** |

---

## 5. 现锁（R-\*）

| # | 规则 |
|---|---|
| **R-1** | 不改线上 10/3；不覆盖 `8a061ea4` pred / 原分析包。 |
| **R-2** | 不加强本仓 qlib PortAna / 不改默认 TopkDropout 训练路径。 |
| **R-3** | 主回测不 import qlib；不把 n_drop 写进成交核。 |
| **R-4** | 不改 v6/v8 默认卖点；10% 止损是新书。 |
| **R-5′** | 策略书允许 TopkDropout；引擎禁止。 |
| **R-6** | 多日回测禁止消费 `live_pool/*sell.csv`。 |
| **R-7** | 对账只比名单 / reason / 可卖 / 涨跌停；禁止 PortAna NAV 判胜负。 |
| **R-8** | 不开 `--buy-state-filter`（MA/盈筹）。 |
| **R-9** | 池 CSV 契约不变：文件名=买入日，首列裸六位，LF 无 BOM。 |
| **R-10** | 遇任务书未覆盖的语义分叉：**停下来问人**，不自裁。 |

---

## 6. 判读预锁（宿主跑之前写死）

1. **采纳条件**：BT-A 三组合成账全过；臂0 在「无附加闸、无成交摩擦」的 fixture 上与 §2 一致；臂2 的止损 `reason` 能单独点名（`stop_loss:touch` / `gap_open` / `defer_sell_limit_down`），且未误改 v6 golden。
2. **合法终点**：Cat 名单 + 止损并不比「仅轮换」好看；ST 闸让成交变少；单窗数字。这些都算交付，如实写。
3. **禁止说法**：「已经对齐 qlib 50/5 净值」「该改线上 topk」「把 v6 止损改成 10% 就是本需求」「本仓计划卖出驱动了主回测」。
4. **预期管理**：实盘成交（跌停、T+1、资金配给）会让换手低于 qlib 纸面 50/5；叠止损后持仓更短、空位次日才补。先看 reason 计数，再谈净值。

---

## 7. 明确不做

- 本仓实现止损、ST 持仓强制卖、n_drop 细表、加大 n_drop 救回撤
- 把 `export_next_day_pool` 当 `--pool-dir` 输入
- 在成交核复刻 TopkDropout
- 用 `--stop-pct 0.10` 改 v6 冒充「给 50/5 加规则」
- 第三窗重训、换线上学习器
- 为烟测重训 Cat（已有 `51dde0bc`）

---

## 8. 验证命令（草案）

MyQuant（MQ-A 后）：

```text
D:/anaconda3/envs/vanna312/python.exe -m pytest -q my_tests/test_export_daily_pool.py
```

MyQuant-backtrader（BT-A/B/C 后）：

```text
D:/anaconda3/envs/vanna312/python.exe -m pytest -q tests/
```

宿主（H-1，合批，另目录）：`--strategy <新书> --pool-dir exports/cat_50_raw_20260105_20260914` + scores；起止与 Cat pred 窗对齐（买入日 2026-01-06～2026-09-14）。分钟结论以分钟版为准。

---

## 9. 代码落点（实现者填 HEAD 行号进 handoff）

| 仓 | 预期落点 |
|---|---|
| MyQuant | `my_scripts/export_daily_pool.py`；`my_tests/test_export_daily_pool.py` |
| backtrader | 新策略书模块（与 `csv_strategy_books` 并列）；**只读** `csv_simulate_loop.py` 买环接 strategy 的 buy/sell 列表；成交核现锁见 `engine-ashare-correctness.md` |
| 算法原文 | `D:\PycharmProjects\qlib-dev\qlib\contrib\strategy\signal_strategy.py` `TopkDropoutStrategy.generate_trade_decision`（约 138–231 行） |

---

## 10. 修订程序

人裁改 P-\* 后 bump 本文版本（v1.1…），在本页顶改状态。切片外的需求开新 plan，不塞进本 PR。GO 副本与 Codex 交接页已落到 MyQuant-backtrader `docs/backtest/`。
