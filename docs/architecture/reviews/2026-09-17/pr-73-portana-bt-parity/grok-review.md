# PR #73 PortAna 买门槛对齐 BT — Grok 核评审

> 日期：2026-09-17
> 角色：MyQuant 仓 Grok 核（独立 grok CLI；只审不合入）
> 对象：[PR #73](https://github.com/baiyibing/MyQuant/pull/73) `feat/portana-bt-parity`（`origin/feat/portana-bt-parity` vs `origin/master`）
> 权威：[PR #73 body](https://github.com/baiyibing/MyQuant/pull/73) · [docs/reviews/2026-09-16-scores-leading-zero-nav-lift.md](../../../../reviews/2026-09-16-scores-leading-zero-nav-lift.md)
> 交叉：BT [PR #87](https://github.com/baiyibing/MyQuant-backtrader/pull/87) `feat/topk-arm0-qlib-align` @ `9cd5bb9`（本地 `/workspace/MyQuant-backtrader-topk-arm0`）
> HEAD：`cfd4e05be2bf2ab5584d26446aea88191bf622a1`
> merge-base：`e7b0569259884b8ed8104270522204a3813e1745`（= `origin/master`）
> GitHub：`MERGEABLE` / `CLEAN` / pytest **SUCCESS** [`35107134714`](https://github.com/baiyibing/MyQuant/actions/runs/35107134714) @ `cfd4e05`
> 工作树：`/workspace/MyQuant`（`feat/portana-bt-parity` @ `cfd4e05`，fetch 后与 origin 同步）

---

## 结论

**GO-WITH-NITS**（**可合**；nits 不阻断合入。本核不 merge）。

对照 PR body 与 2026-09-16 权威页：这是一次 scoped 的 PortAna 买门槛对齐。ST 静态名单清空、只认 `st_daily.parquet` `is_st`；15% 对 NaN 收盘按缺数放过；缺分排序用 `000608.SZ` 并列键；买入向下取整到 100 股；上市年龄溢出写成 `9999-12-31`。资格层（ST / 年龄 / 5 日 15%）默认关，默认 PortAna 仍走官方 `TopkDropoutStrategy`；CLI 默认仍是 **10/3 LGB**。官方 qlib TopkDropout 不在 diff。成本仍是买 5bp / 卖 15bp / 最低 5，与 BT #87 `--qlib-cost` 同构。本核复跑声明的单测 **61 passed**。169 日同 pred 净值对齐是宿主声明，本核未重跑。

---

## 对象

| 项 | 值 |
|----|----|
| PR | [#73 fix(strategy): align PortAna buy gates with BT](https://github.com/baiyibing/MyQuant/pull/73) |
| 比较 | `origin/master...HEAD`（23 files, +829 / −200；单 commit `cfd4e05`） |
| 默认路径 | 无 `--st-filter` / `--age-filter` / `--return-threshold-filter` / `--buy-state-filter` → 官方 TopkDropout；`--topk 10` `--n-drop 3` `--model lgb` |
| 对齐路径 | 任一资格开关 → `TopkDropoutStrategyWithBuyEligibility`（含排序 + 手数地板） |
| 官方 Topk | **零改**（diff 无 `qlib.contrib.strategy`） |
| 宿主声明 | `exports/analysis/55c5bf77_replay_age_lot` NAV **112,577,450.51** 与 BT zfill+age 趟对齐（权威 §9；本核未重跑） |

---

## 证据表

| 锁 / 对齐点 | 结果 | 证据 |
|-------------|------|------|
| **空静态 ST 黑名单** | **PASS** | `train_wiring.EXCLUDE_STOCKS_DEFAULT: list[str] = []`。`test_exclude_stocks_default_is_empty`。`--exclude-filter` 对空名单 `build_exclude_name_filter([]) is None`，不发出 `^(?!(|))`。 |
| **只读 parquet `is_st`** | **PASS** | `load_st_daily_index(..., use_coverage=False)` 默认不读 `st_coverage.json`，fallback 空集。`BuyEligibilityFilter` 有 `st_daily_file` 时丢掉 coverage / 静态偷偷并入。`test_st_daily_file_ignores_coverage_json`：旁路 json 禁不了 `SZ000608`。`load_st_codes_asof` 忽略 coverage/fallback 参数。 |
| **15% NaN closes** | **PASS** | `select_by_return_threshold`：`returns.fillna(-inf)`，与「票不在表里」同口径。`test_nan_close_passes_like_missing`。默认 `lookback_days=0` / `max_return_threshold=-1`，`_filter_stocks_by_return_threshold` 直接放行。要开须 `--return-threshold-filter`。 |
| **缺分排序 tie-break** | **PASS** | `sort_score_desc`：`fillna(-inf)`，分数降序、规范码升序、`mergesort`。并列键 `SZ000608`→`000608.SZ`（不是 `SZ` vs `SH` 字面量）。`generate_trade_decision` 的 `last` / `candidate` / `comb` / random 四处都走它。`test_sort_score_desc_missing_ties_by_code`：`SZ002943` 先于 `SH603950`。 |
| **100 股地板** | **PASS** | 买入改 `floor_amount_to_lot(value/price)`，不再 `round_amount_by_trade_unit`（`+0.1`）。`test_floor_amount_to_lot_does_not_round_up_like_qlib` 钉 324299.95→324200。`test_generate_trade_decision_counts_grow_across_steps`：`factor_calls` 保持 0。不改 qlib Exchange。 |
| **上市年龄溢出未可买** | **PASS** | `earliest_buy_date`：起始+age 越出日历或起始在日历之后 → `AGE_NOT_YET`（`9999-12-31`）；老股（日历之前）→ `None`（不限）。`shift_start_for_age` 越界写 `9999-12-31`，不再写回上市日。`test_age_overflow_blocks_like_920072` + `test_shift_start_for_age`。 |
| **默认关 universe exclude / limit-up / DropLimitUpLearn** | **PASS（声明内）** | CLI：`--exclude-filter` / `--limit-filter` / `--drop-limit-up-learn` 均 `store_true`，`parse_train_cli([])` 全 False。`build_production_filter_pipe(..., limit_up=False)`。`build_learn_processors()` 不含 `DropLimitUpLearn`；`--drop-limit-up-learn` 才插到 learn 帧首位。infer_processors 从未含它。handler cache digest 增加 `drop_limit_up_learn_on`。 |
| **官方 TopkDropout 不变** | **PASS** | diff 无 qlib 策略源。默认 `_use_elig_strategy` 假 → `class: TopkDropoutStrategy` / `module_path: qlib.contrib.strategy.signal_strategy`。资格层只活在 `custom_strategy` / `buy_eligibility`。 |
| **默认路径仍是 10/3 LGB** | **PASS** | `parse_train_cli([])`：`topk==10` `n_drop==3` `model=="lgb"` `exp_name=="alpha158_cost_kdj_lgb"`。ST/年龄/15%/买入状态默认关。PortAna 默认官方 Topk。`limit_threshold` 仍默认 0.095。成本未改：`open_cost=0.0005` `close_cost=0.0015` `min_cost=5`。 |
| **买门槛 opt-in，不静默接到线上 10/3** | **PASS** | 须显式 `--st-filter` / `--age-filter` / `--return-threshold-filter`（及既有 `--buy-state-filter`）才换自定义策略。任一开才带上排序+手数地板（对齐路径需要这把尺子）。默认 10/3 回测名单/手数算法仍是官方 Topk。 |

### 核重点 1 — 买门槛与声明一致；默认 10/3 不接新闸

权威页把分叉拆成：静态 ST fallback、15% NaN、缺分并列、`+0.1` 抬一手、年龄溢出写回上市日。本 PR 五处都改在 **自定义策略 / 资格层**，并且默认不启用。

`custom_train_backtest.py`：`_use_elig_strategy = st or age or buy_state or return_threshold`。全关则官方 Topk，kwargs 不含 `eligibility` / `close_cache` / 15% 阈值。`rebacktest_cost_tiers.build_strategy_config` 同构。

线上身份（10/3、LGB、实验名）CLI 默认未动，有单测钉死。PR test plan「Online default stays 10/3 LGB」未勾，但是代码默认就是 10/3 LGB；未勾的是流程项，不是实现缺口。

**声明内的默认路径变化**（不是买门槛，但是训练/导出宇宙）：`$zhangting` 出池和 `DropLimitUpLearn` 从「默认开」改成「默认关」。这是 PR body 明文，不是静默接 ST/年龄/15%。执行端 9.5% 拒单仍默认开。见 nits：导出/sweep/predict 把涨停出池硬编码关、没有回切开关。

### 核重点 2 — ST / 年龄 / 涨停 / 手数 fail-closed、可测

| 改动 | fail 方向 | 单测 |
|------|-----------|------|
| 年龄溢出 | **closed**：`9999-12-31`，窗内不可买 | `test_age_overflow_blocks_like_920072` |
| 老股起始在日历前 | 不限（与「满 60 日」语义一致） | `earliest_buy_date("2019-12-01") is None` |
| ST + parquet | 只认当日 `is_st`；coverage 不能偷偷禁买 | `test_st_daily_file_ignores_coverage_json` |
| ST 缺 parquet 列 / `--st-filter` 不给文件 | **open**（空集合 = 谁都不禁） | 见 nit；BT #87 缺文件/缺列是 raise |
| 手数非法 / ≤0 | **closed**：0 股 | `test_floor_amount_to_lot_*` `== 0.0` |
| 15% 缺价 / NaN | 放过（与 BT「缺数当 −inf ≤ 15%」一致，不是禁买） | `test_nan_close_passes_like_missing` |
| 涨停出池 | 默认关；执行端 9.5% 仍拒单 | CLI + `no_limit_threshold` 默认 False |

未知上市年龄：本仓 **fail-open**（`test_eligibility_unknown_age_passes`，不在 all.txt 则不设限）。BT #87 `make_eligible_buy` 对表里没有的码 **fail-closed**。这是交叉残留，不是这次溢出修复的回退；全市场 pred 的码都在 `all.txt` 时 169 日窗对得上。

`D.calendar(future=True)` 仍比 day.txt 长几天。溢出改成 `AGE_NOT_YET` 之后，2026-07-08 的 `920072` 两边都拦住。若未来窗越过 qlib 日历内、BT TSV 仍是 `99991231` 的那几天，会再分叉——不在本页 2026-01-06～09-14 声明窗内。

### 核重点 3 — 与 BT #87 交叉（成本 / 门槛叙事）

BT #87 body：`--qlib-data-root` 读 qlib `$close` 后复权；买时 ST / 年龄 / 5 日 15%；`--stop-pct 0`；`--qlib-cost` = 买 5bp / 卖 15bp / 最低 5；湖默认仍是双边 10bp。tip `9cd5bb9` 再补分数码 `zfill` + 年龄溢出 fail-closed。

| 叙事 | PortAna（本 PR） | BT #87 @ `9cd5bb9` |
|------|------------------|---------------------|
| 成本 | 未改；PortAna 一直是 5/15/min5（`custom_train_backtest` exchange + `COST_TIERS["qlib_default"]`） | `--qlib-cost` **对齐 PortAna**；默认湖 10bp 不动 |
| ST | parquet `is_st` only；空静态名单 | `load_st_daily_by_day` 同句「只认 is_st，不读 coverage」 |
| 15% NaN | fillna(−inf) 放过 | `with_return_threshold`：缺收盘 / NaN → pass |
| 排序 | `(-score, 000608.SZ)` | `sort_by_score_desc`：`(-score, code)`，码已是 `XXXXXX.SH\|SZ\|BJ` |
| 手数 | `int(shares/100)*100`，不足 1 手 → 0 | `_buy_size` 同式；**不足 1 手会补 100 股+补充资金**（见 nit） |
| 年龄溢出 | `9999-12-31` | `99991231` |
| 分数码 | 本仓不读 scores CSV | `zfill(6)` 修前导零（权威页那笔 475 万是 BT 读码 bug） |
| 官方 Topk | 不改 qlib | 纯函数书，不 import qlib 策略 |

成本叙事交叉一致：BT 用开关去贴 PortAna，PortAna 不改费率。门槛叙事交叉一致：两边都是买时闸、不强迫 ST 卖出、15% 缺数放过、溢出不可买。本 PR 不碰 `--stop-pct`（qlib Topk 无此书止损）。

### 核重点 4 — 测试覆盖关键对齐点

本核（vanna312）：

```
pytest my_tests/test_buy_eligibility.py
       my_tests/test_return_threshold_filter.py
       my_tests/test_st_status.py
       my_tests/test_train_filter_pipe.py
       my_tests/test_drop_limit_up_learn.py
       my_tests/test_handler_frame_cache.py
→ 61 passed / 2.96s
```

GitHub Actions pytest @ `cfd4e05` **SUCCESS**（PR test plan 还列了 `test_bar_call_spectrum`；该文件已改 `factor_calls==0`，CI 已带跑）。

| 对齐点 | 覆盖 |
|--------|------|
| 空黑名单 + 空 pipe | `test_exclude_stocks_default_is_empty` |
| CLI 默认关（含 10/3 LGB） | `test_guard_and_cache_cli_flags_default_off` |
| DropLimitUpLearn 默认不在 learn | `test_default_learn_processors_omit_drop_limit_up` |
| ST 不理 coverage | `test_st_daily_file_ignores_coverage_json` + `test_coverage_fallback_and_asof` |
| 15% NaN | `test_nan_close_passes_like_missing` |
| 并列键 002943/603950 | `test_sort_score_desc_missing_ties_by_code` |
| 手数 324299.95→324200 | `test_floor_amount_to_lot_does_not_round_up_like_qlib` |
| 年龄溢出 920072 | `test_age_overflow_blocks_like_920072` |
| 宇宙顺延与策略 min_trade_date 同尺 | `test_shift_start_matches_strategy_age_map` |
| cache digest 隔离 drop_limit_up | `test_digest_stable_and_isolated` |

缺口（不升格）：没有单测直接断言「全关 → 策略 class 是官方 TopkDropout」（只在脚本分支里）；169 日名单/手数/净值对齐是宿主声明，不在 CI。

---

## NITS（不阻断）

1. **`--st-filter` 不给 `--st-daily-file` 是空操作。** `st_codes=set(EXCLUDE_STOCKS_DEFAULT)` 现为空，`st_codes_of_date` 返回空集，等于没开。Help 写了。BT 缺配置的维是「不检查」；缺**文件**是 `FileNotFoundError`。PortAna 给了坏路径会在 `read_parquet` 炸；不给路径则静默放行。可测、不是默认路径。若要更 fail-closed：`--st-filter` 且无文件时直接 raise。

2. **parquet 缺 `is_st` / `trade_date` / `code` 列：本仓返回空 map，BT raise。** `st_status.load_st_daily_index` 只在列存在时填 `by_date`。空表 + `--st-filter` = 谁都不禁。真湖文件有这些列；交叉合同不如 BT 严。

3. **未知年龄 fail-open vs BT fail-closed。** `test_eligibility_unknown_age_passes` 明确允许。溢出修复没有动这条。全市场 `all.txt` 覆盖 pred 码时与 169 日声明不冲突。

4. **BT `_buy_size` 不足 1 手会用补充资金买 100 股；PortAna 地板到 0。** 权威 §8 钉的是 324299.95 抬一手，不是零钱补手。声明窗两边手数对齐，说明这条没触发。残差留在零钱/低价票。

5. **`export_next_day_pool` / `predict_extended` / `sweep_live_adapter` / `diag_weak_window_from_model` 把 `$zhangting` 出池和 DropLimitUpLearn 硬编码关，没有 `--limit-filter` 回切。** 训练入口有开关。若线上日池走 `export_next_day_pool`，合并后评分宇宙含涨停票（执行 9.5% 仍拒买）。这是声明的「默认关」，不是买门槛静默打开；日池名单会变。

6. **`replay_buy_stag_once.py` / `replay_buy_stag15_once.py` 硬编码 `E:\stock_data\...` 和 CAT recorder `4233a65a`，不是权威页的 LGB `55c5bf77`。** 宿主一次性脚本，不进 CI，也不复现声明净值。不挡合入。

7. **`BuyEligibilityFilter` 仍收 `st_coverage_file`，有 `st_daily_file` 时不用。** 死参。`st_daily_lookup` 路径仍可显式 `st_fallback`（测试注入），与「coverage 不再偷偷并入」不矛盾。

8. **handler cache 测试 payload 仍用 `limit_up_filter_on=True` 作基线。** 只测 digest 隔离，不是生产默认。易误读。

---

## 非阻断观察

- 资格开关任一打开，自定义策略**同时**换排序 + 手数地板。这是对齐路径需要的同一把尺子，不是漏接。默认官方 Topk 仍是 pandas 排序和 `+0.1` 取整——声明就是不改官方。
- `--buy-state-filter` 不再顺带 15%（以前 `TopkDropoutStrategyWithFilter` 写死 5 日 / 0.15）。15% 独立。行为变化仅发生在显式开了买入状态过滤的路径。
- `build_tradable_universe` 去掉 `--st-coverage-file`；`--tradable-universe` 仍默认关。
- 权威页写明「线上仍是 10/3 LGB。本页不是上线依据。」本 PR 也不构成上线依据。

---

## 依赖（HEAD，资格路径）

```
custom_train_backtest / rebacktest_cost_tiers
  ├─ 默认 → qlib.contrib.strategy.TopkDropoutStrategy   # 零改
  └─ 开关 → buy_eligibility.TopkDropoutStrategyWithBuyEligibility
              ├─ custom_strategy.{sort_score_desc, floor_amount_to_lot,
              │                   select_by_return_threshold}
              ├─ BuyEligibilityFilter
              │    ├─ st_status.load_st_daily_index(use_coverage=False)
              │    └─ earliest_buy_date / load_age_map(all.txt)
              └─ train_wiring.EXCLUDE_STOCKS_DEFAULT == []
```

---

## STOP

无。本核不 merge。
