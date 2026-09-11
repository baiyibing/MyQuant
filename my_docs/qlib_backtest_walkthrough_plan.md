## 目标

- 完成一次“代码级走查（Code Walkthrough）+ 架构级评估”，判断你当前回测是否满足回测黄金准则：因果一致、训练/验证/测试无数据泄漏、信号与下单时点对齐、过滤器/交易成本口径正确。
- 输出：问题清单（按严重度排序、给出对应代码位置）+ 建议的下一步改进清单。

## 计划与步骤

1. **回测流程总览（入口->回测产物）**
   - 以 `my_scripts/custom_train_backtest.py` 为主线，梳理：`qlib.init`、时间切分、Handler/Dataset、`model.fit`、`SignalRecord/SigAnaRecord`、`PortAnaRecord`、report/positions 的读取与额外分析。
   - 同时标注哪些模块是“定义了但未接入”的（例如 filter/对照 handler）。

2. **因果一致性与时间对齐检查（黄金准则核心）**
   - 核查：
     - Handler/Label 的时间偏移（Alpha158 默认 label horizon）与 `deal_price='close'`/Qlib 默认交易时序（你已选择“按 Qlib 默认了 T+1”）是否一致。
     - `pred.pkl` 的 `datetime` 索引与 `portfolio_analysis/report_normal_1day.pkl` 的交易日索引是否存在 0/1 天错位。
   - 建议加入“自检输出”以验证：首个交易日的 `pred.pkl` vs 回测 report 的差值。

3. **DataHandlerLP 处理器（learn_processors/infer_processors）是否真正生效**
   - 对照 Qlib 0.9.7 文档：`DataHandlerLP` 的 `process_type='append'` 下 `_infer` 和 `_learn` 的处理链路差异（PTYPE_A：`_learn` = infer_processors + learn_processors）。
   - 核查你的 `Alpha158CostKDJ`：其 `__init__` 是否正确把 `infer_processors/learn_processors` 传给父类 `Alpha158`/`DataHandlerLP`；否则可能导致标准化/丢弃 NaN 标签等步骤失效。

4. **过滤器与股票池口径是否一致（避免“意图与实现脱节”）**
   - 核查 `UnifiedLimitUpFilter`、`exclude_filter`、`dynamic_filter` 是否通过 `filter_pipe` 真正作用在 Handler 的 train/valid/test 三段。
   - 核查“对照 handler_no_limit_filter”是否被用于任何评估或统计。
   - 对照 Qlib 文档中 filter_pipe 的用法示例（`instruments: *market` + `filter_pipe: [*filter]`）。

5. **交易执行与成本口径（SimulatorExecutor + 策略行为）**
   - 核查 `exchange_kwargs`、`deal_price`、`limit_threshold/open_cost/close_cost/min_cost` 是否与策略下单逻辑匹配。
   - 核查你使用的是 Qlib 内置 `TopkDropoutStrategy`（而非 `TopkDropoutStrategyWithFilter`），因此自定义过滤逻辑是否未生效。

6. **基准（benchmark）与指标口径**
   - 检查 `benchmark` 变量是否与注释（沪深300）一致；如果基准股票/指数不匹配，会直接影响 excess return、IR、最大回撤等。

7. **输出整改方向（按严重度排序）**
   - 对每个发现给出：影响范围、复现/验证思路、建议改法（例如：把 filter_pipe 接回 Handler 配置、修复 processors 传递、调整 warm-up 历史窗口、修正 benchmark、增加 pred vs trade 对齐自检）。

## 涉及的关键文件

- `my_scripts/custom_train_backtest.py`
- `my_scripts/custom_handler.py`
- `my_scripts/custom_filter.py`
- `my_scripts/custom_ops.py`
- `my_scripts/custom_strategy.py`（用于核查自定义策略是否实际接入）
- `my_scripts/custom_utils.py`（用于核查是否影响回测逻辑或仅用于分析）

## 预期的核心发现类型

- 因果泄漏/时序错位（pred 与 trade 日不对齐）
- 过滤器未生效（filter_pipe 注释/对照 handler 未使用）
- 数据处理器未生效（processors 传递给父类失败）
- benchmark 指标口径错误
- 特征 warm-up 不足导致大量 NaN 或 ffill 伪稳定

