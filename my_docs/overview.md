# `my_scripts/` 综述文档

本文档对 `my_scripts/` 下的全部脚本（当前为 5 个 Python 文件）做端到端综述：从 QLib 初始化、因子/标签构建、模型训练、预测信号生成，到组合构建、回测执行与绩效/持仓分析。

主要入口脚本：
- `my_scripts/custom_train_backtest.py`

核心自定义组件：
- 因子算子：`my_scripts/custom_ops.py`
- 数据处理器/特征处理：`my_scripts/custom_handler.py`
- 交易策略：`my_scripts/custom_strategy.py`
- 回测分析工具：`my_scripts/custom_utils.py`

## 1) 端到端数据流（整体流程）

```mermaid
flowchart TD
  A[qlib.init(...) 初始化] --> B[D.instruments(...) 构建股票池 + 过滤]
  B --> C[Alpha158CostKDJ DataHandler(fetch feature/label)]
  C --> D[DatasetH(segments=train/valid/test)]
  D --> E[LGBModel.fit(dataset)]
  E --> F[SignalRecord.generate -> pred.pkl]
  F --> G[SigAnaRecord.generate -> sig_analysis/*]
  F --> H[PortAnaRecord.generate -> portfolio_analysis/*]
  H --> I[custom_utils: 风险/持仓打印 + 报告生成]
  H --> J[Qlib report_graph/risk_analysis_graph 可视化]
```

## 2) 逐文件深度综述

### 2.1 `my_scripts/custom_train_backtest.py`（训练 + 回测主入口）

这个脚本是“实验工作流”的总控端，负责把 QLib 的各组件串起来并落地分析产物。

#### (1) 运行入口与日志/多进程兼容

- 使用 `if __name__ == '__main__':` 包裹主逻辑，并调用 `multiprocessing.freeze_support()`（Windows 下常见的多进程/打包兼容）。
- `loguru` 通过 `logger.add(...)` 配置输出过滤（例如：按 `module == "custom_strategy"` 将策略日志写到 `Filter.log`）。

#### (2) `qlib.init(...)`：数据、Redis 缓存、算子注册与实验管理

关键配置包括：
- `provider_uri = "~/.qlib/qlib_data/my_data"`：Qlib 数据存储路径
- `region=REG_CN`：中国市场
- `kernels=16`：并行内核数（QLib内部）
- `redis_host/redis_port/redis_password/redis_task_db`：Redis 缓存与任务协同（连接失败会降级不使用缓存）
- `custom_ops=[SMA]`：注册自定义算子 `SMA`（来自 `my_scripts/custom_ops.py`）
- `exp_manager`：MLflow 实验管理器（`class: MLflowExpManager`，`uri: mlruns`，`default_exp_name: MyExperiment`）

#### (3) 时间切片、股票池与过滤

脚本设置了四段时间：
- 总体 `start_time/end_time`
- 训练 `fit_start_time/fit_end_time`
- 验证 `valid_start_time/valid_end_time`
- 测试 `test_start_time/test_end_time`

股票池构建：
- 先准备一个较长的 `exclude_stocks` 列表。
- `exclude_filter = NameDFilter(...)` 使用正则排除这些股票代码。
- `filtered_instruments = D.instruments(..., filter_pipe=[exclude_filter])`。

补充说明（当前代码现状）：
- 脚本中还定义了 `dynamic_filter = ExpressionDFilter(...)`（用于基于表达式动态过滤），但后续并没有把它加入 `filter_pipe`，因此它目前不会生效。

#### (4) 数据处理器配置：`Alpha158CostKDJ`

`data_handler_config` 是一个决定“特征输出内容”的关键字典，主要字段：
- `start_time/end_time`：整体数据范围
- `fit_start_time/fit_end_time`：训练数据边界
- `infer_processors`（推理阶段处理链）
  - `ProcessInf`
  - `RobustZScoreNorm(fields_group="feature")`
  - `Fillna(method="ffill")`
- 开关字段：
  - `include_alpha158=True`：是否保留原始 Alpha158 因子
  - `include_cost_kdj=True`：是否加入 COST-KDJ 相关因子（`COST_K/COST_D/COST_J`）
  - `include_signal=False`：是否输出 `MAIRU_SIGNAL`（用于回测信号）
  - `include_lz=True`：是否加入一组滚动/波动类自定义因子（如 `VOLDDX_*`、`BIGDDX_*`、`LIMIT_STATUS`）

在本脚本中：
- `handler = Alpha158CostKDJ(**data_handler_config)` 用于后续 `fetch` 和 dataset handler 的构造。

#### (5) 任务配置字典 `task`：模型 + 数据集

`task` 包含两个子字典：

1. `task["model"]`
   - `class`: `LGBModel`
   - `module_path`: `qlib.contrib.model.gbdt`
   - `kwargs`: LightGBM 超参数（例如 `loss="mse"`, `learning_rate`, `num_leaves`, `max_depth`, `num_threads` 等）

2. `task["dataset"]`
   - `class`: `DatasetH`
   - `module_path`: `qlib.data.dataset`
   - `kwargs`：
     - `handler`：使用 `custom_handler.Alpha158CostKDJ`，并把 `data_handler_config` 作为 `kwargs` 传入
     - `segments`：train/valid/test 对应时间切片

#### (6) 特征检查、模型/数据集实例化

脚本还会：
- `data = handler.fetch(col_set="feature")`
- 打印 `data.columns`
- 根据 `signal_cols` 与 `data.columns` 做可用列筛选并输出示例（例如 `COST_K/COST_D/COST_J/MAIRU_SIGNAL/ZHANGTING`）。

重要现状提示：
- 因为本脚本设置 `include_signal=False`，所以 `Alpha158CostKDJ.get_feature_config()` 默认不会产出 `MAIRU_SIGNAL`；因此 `available_cols` 中通常不会包含该列（除非你把 `include_signal` 改成 `True`）。

随后：
- `model = init_instance_by_config(task["model"])`
- `dataset = init_instance_by_config(task["dataset"])`

#### (7) 回测策略配置：`TopkDropoutStrategyWithFilter`

`port_analysis_config` 由三部分组成：

1. `executor`
   - `class`: `SimulatorExecutor`
   - `time_per_step="day"`
   - `generate_portfolio_metrics=True`

2. `strategy`
   - `class`: `TopkDropoutStrategyWithFilter`
   - `module_path`: `custom_strategy`
   - `kwargs`：
     - `model`: 上面训练好的 `model`
     - `dataset`: 同一 dataset
     - `topk=10`：每天选择预测分数最高的目标持仓数量
     - `n_drop=3`：计划卖出的数量（与 TopkDropout 的组合逻辑共同决定最终换仓集合）
     - `hold_thresh=1`：最小持有天数

3. `backtest`
   - `start_time/end_time`：用测试集时间段
   - `account=100000000`：初始资金
   - `benchmark="SH601727"`
   - `exchange_kwargs`：
     - `freq="day"`
     - `limit_threshold=0.095`：涨跌停限制
     - `deal_price="close"`：成交价使用收盘价
     - `open_cost/close_cost/min_cost`：手续费/成本模型

#### (8) 工作流：训练、预测、信号评估、回测分析

训练与实验跟踪：
- `with R.start(experiment_name=exp_name):`
  - `R.log_params(**flatten_dict(task))`
  - `model.fit(dataset)`
  - `R.save_objects(trained_model=model)`
  - `rid = R.get_recorder().id` 获取实验记录器 ID

特征重要性（用于特征筛选/可视化）：
- 优先尝试 `model.feature_importance()`
- 否则尝试 `model.get_feature_importance()`
- 再否则使用 fallback（目前是 `feat_imp=None`，需要你确认 QLib 版本下具体接口）
- 之后将 `feat_imp_series` 转为排序结果，并构造 plotly 横向条形图展示 Top-K。

预测信号生成与信号分析：
- `SignalRecord(model, dataset, recorder).generate()` 产生 `pred.pkl`
- `SigAnaRecord(recorder).generate()` 产生信号分析产物（脚本注释里提示过 `sig_analysis/ic.pkl` 路径可能不存在，实际产物名可能与 QLib 版本有关）

回测分析：
- `PortAnaRecord(recorder, port_analysis_config, "day").generate()`
- 随后脚本从 recorder 中加载：
  - `portfolio_analysis/report_normal_1day.pkl`
  - `portfolio_analysis/positions_normal_1day.pkl`
  - `portfolio_analysis/port_analysis_1day.pkl`

风险/持仓分析与可视化：
- 使用 `risk_analysis` 对 `return` / `bench` / `return-bench` 做风险绩效拆解
- 使用 `my_scripts/custom_utils.py` 的：
  - `pprint_risk_analysis`
  - `pprint_position_report`
  - `analyze_position_by_date`
  - `generate_position_report`
- 使用 QLib 的图表函数：
  - `analysis_position.report_graph(...)`
  - `analysis_position.risk_analysis_graph(...)`

预测 IC 图：
- `dataset.prepare(segments='test', col_set=['feature','label'])` 获取测试集 label 与 feature
- `pred_label = concat([label_df, pred_df])` 并调用 `analysis_position.score_ic_graph(pred_label, ...)`。

#### (9) 输出产物（你可能关心的文件）

脚本里明确落盘/展示的产物包括：
- `预测结果.csv`
- `预测结果和真实标签.csv`
- 持仓分析报告：`position_analysis.txt`（由 `generate_position_report` 默认输出）
- plotly 图会 `feature_importance_fig.show()`，并且 QLib 的图表在 `fig.show()` 处直接弹出/渲染（取决于你的运行环境）。

### 2.2 `my_scripts/custom_handler.py`（数据处理器/因子/信号）

该文件定义了若干对 QLib `DataHandlerLP`/`Alpha158` 体系的扩展类，核心包括：
- 自定义因子算子接入（导入 `SMA`）
- 扩展 Alpha158：`Alpha158CostKDJ`
- 一个用于回测信号后处理的 Handler：`CostKDJSignalHandler`

#### (1) 自定义算子注册/导入

文件开头会把当前目录加入 `sys.path`，并执行：
- `from custom_ops import SMA`
- 同时打印 `✅ SMA 类已导入: {SMA}`

这样做的目的是：让 QLib 的算子表达式里能使用你自定义的 `SMA` 实现。

#### (2) `AlphaSimpleCustom(Alpha158)`（特征示例扩展）

该类给出了一个“如何从配置动态构建表达式”的示例：
- `get_feature_config()` 构造 `conf = {"ma": {"windows":[...]} , "macd":{...}}`
- `parse_config_to_fields()` 将 windows 列表映射到：
  - `Mean($close, d)/$close`（均线/收盘价比）
  - `MACD_EXP`（EMA 差分/归一化）

虽然当前主流程没用到它，但它说明了你扩展因子的方式。

#### (3) `Alpha158vwap` / `AlphaSimpleOpen`（标签示例扩展）

这两个类只改 `get_label_config()`，用于展示标签如何替换为 vwap 或 open 相关收益：
- `Alpha158vwap`：`Ref($vwap,-2)/Ref($vwap,-1) - 1`
- `AlphaSimpleOpen`：`Ref($open,-6)/Ref($open,-1) - 1`

#### (4) `Alpha158CostKDJ(Alpha158)`（主用数据处理器：COST-KDJ + 可选滚动因子）

这是主训练脚本中实际使用的处理器（见 `custom_train_backtest.py` 中 `handler = Alpha158CostKDJ(...)`）。

##### 关键构造参数（开关/窗口）
- `cost_window=250`：用于构造 `Quantile($low/$high, N, ...)` 的滚动窗口长度
- `include_alpha158`：是否把新因子追加到原 Alpha158 因子
- `include_cost_kdj`：是否产出 COST-KDJ 核心因子
- `include_signal`：是否产出额外的回测信号 `MAIRU_SIGNAL`
- `include_lz`：是否产出滚动技术指标/成交相关因子

##### `get_feature_config()`：表达式如何拼装

1) COST-KDJ 主因子（当 `include_cost_kdj=True`）

- 近似 COST(0.01) / COST(99.99)
  - `L1_expr = Quantile($low, N, 0.0001)`
  - `L2_expr = Quantile($high, N, 0.9999)`
- 相对位置映射
  - `L3_expr = ($close - L1_expr) / (L2_expr - L1_expr + 1e-6) * 100`
- K/D/J
  - `K_expr = SMA(L3_expr, 3, 1)`
  - `D_expr = SMA(K_expr, 3, 1)`
  - `J_expr = 3*K_expr - 2*D_expr`

2) MAIRU 信号（当 `include_signal=True` 且 `include_cost_kdj=True`）

- 背景均线条件（脚本注释里提到“周线近似”，但实际表达式是日均线）
  - `K20_expr = ($close > Mean($close, 20)) & ($close > Mean($close, 100))`
- 交叉条件与阈值
  - `MAIRU_expr = If( (J_expr > K_expr) & (Ref(J_expr,1) <= Ref(K_expr,1)) & (J_expr < 80) & K20_expr, 2, 0)`
- 最终输出列名：
  - `COST_K/COST_D/COST_J` 与 `MAIRU_SIGNAL`

##### 注意：当前训练脚本把 `include_signal=False`
- 因而 `MAIRU_SIGNAL` 不会进入 feature columns。

3) 额外滚动因子（当 `include_lz=True`）

实现包含多组表达式（依赖 Alpha158 提供的原始字段，如 `$volddx`、`$bigddx`、`$adfadfbasiccurhold`、`$zhangting` 等）：
- `VOLDDX_TX{10,20,30}` / `BIGDDX_TX{10,20,30}`
  - 形如 `($volddx-Mean($volddx,d))/Std($volddx,d)`
- `VOLDDX_STD{10,20,30}` / `BIGDDX_STD{10,20,30}`
  - 形如 `Std($volddx,d)/Abs($volddx)`
- `VOLDDX_R{1,3,5}` / `BIGDDX_R{1,3,5}`
  - 对流通盘拉动作用的累计/归一化
- `LIMIT_STATUS = $zhangting`

最后根据 `include_alpha158` 决定：
- `fields.extend(new_fields)`：保留原 Alpha158 + 新因子
- 或者 `fields=new_fields`：只用新因子

##### 返回值
- `return fields, names`

#### (5) `CostKDJSignalHandler(DataHandlerLP)`（信号后处理示例）

该类与 `Alpha158CostKDJ` 的主要差异在于：
- 它更像是“先算 K/D/J（作为特征），再在 `get_extended_data` 里派生 MAIRU 信号列”的方式。

关键点：
- `get_feature_config()`：
  - 可选 `include_alpha158` 把 Alpha158 原因子带入
  - 无条件加入 `COST_K/COST_D/COST_J`（表达式同 COST-KDJ 部分）
- `get_extended_data(df)`：
  - 计算 `cross = (J > K) & (J.shift(1) <= K.shift(1))`（J 上穿 K）
  - 再计算 `MAIRU = (cross & (J < 80)).astype(int)`
  - `df["MAIRU"] = MAIRU`

说明：
- 主训练脚本当前使用的是 `Alpha158CostKDJ`，而不是这个 `CostKDJSignalHandler`。

### 2.3 `my_scripts/custom_strategy.py`（回测组合构建：TopK Dropout + 涨幅过滤）

该文件对 QLib 自带的 `TopkDropoutStrategy` 做了扩展：在选入候选股票时增加“涨幅阈值过滤”，以降低极端走势带来的不稳定性。

#### (1) 核心策略类：`TopkDropoutStrategyWithFilter`

构造参数（在 `__init__` 中硬编码）：
- `max_return_threshold = 0.15`（15% 最大涨幅阈值）
- `lookback_days = 5`（回溯窗口用来算历史涨幅）
- `logger = get_module_logger(...)`：记录策略内部行为

#### (2) 涨幅过滤函数

1) 旧版 `_filter_stocks_by_return_threshold_old(...)`
- 在回溯窗口区间内用 `D.features` 拉取 `$close`，再通过 `groupby('instrument')` 得到每只股票的 first/last 收盘价
- 计算 `(last-first)/first` 并筛选 `<= max_return_threshold`

2) 当前启用的新版 `_filter_stocks_by_return_threshold(...)`
- 性能优化：只查两天收盘价（起点一天 + 终点一天）
- 使用 `get_date_by_shift(trade_start_time, -1)` 与 `get_date_by_shift(trade_start_time, -(lookback_days+1))` 得到交易日
- 然后：
  - `start_price = D.features(... start_time=prev_dates_last, end_time=prev_dates_last)`
  - `end_price = D.features(... start_time=prev_dates_first, end_time=prev_dates_first)`
  - 计算 `returns = (end_series - start_series) / start_series`
  - 对每个股票进行阈值过滤，达到 `initial_required_count` 就提前 break

函数签名里有 `initial_required_count`：
- 它代表“候选中目标需要补足的数量上限”，用于减少不必要的数据处理开销。

#### (3) 交易决策入口：`generate_trade_decision(self, execute_result=None)`

这是策略逻辑的核心入口。回测在每个 `trade_step` 会调用它一次。

关键流程：
1. 取得当前交易步与时间区间
   - `trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)`
2. 为信号计算获取历史窗口（严格因果）
   - `pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)`
3. 获取预测分数
   - `pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)`
   - 若 `pred_score` 是 DataFrame（多列信号），只取第一列：`pred_score.iloc[:,0]`
4. 当前持仓 `last`
   - `current_stock_list = current_temp.get_stock_list()`
   - `last = pred_score.reindex(current_stock_list).sort_values(ascending=False).index`

##### 买入候选生成（`method_buy=="top"`）
- 候选集合：
  - `candidate_stocks = pred_score[~pred_score.index.isin(last)].sort_values(ascending=False).index`
- 需要补足数量：
  - `initial_required_count = self.n_drop + self.topk - len(last)`
- 策略做两阶段选择：
  1. 先取前 1000 个候选（`initial_today = get_first_n(candidate_stocks, 1000)`）
  2. 应用涨幅过滤 `_filter_stocks_by_return_threshold(...)`
  3. 若过滤后不足，再从候选的 `[1000:2000]` 区间抽取并再次过滤补足

##### 卖出集合生成（`method_sell=="bottom"`）
- `sell = last[last.isin(get_last_n(comb, self.n_drop))]`

##### 订单创建与执行

卖出阶段：
- 遍历 `current_stock_list`，检查每只股票是否可交易 `trade_exchange.is_stock_tradable(...)`
- 若该股票在 `sell` 中且满足持有天数阈值（`current_temp.get_stock_count(... ) >= hold_thresh`）：
  - 创建 `Order(... direction=Order.SELL)`
  - 可执行则加入 `sell_order_list`
  - `trade_exchange.deal_order(...)` 后更新 `cash`

买入阶段：
- `value = cash * self.risk_degree / len(buy)`
- 对每只 `buy`：
  - 检查可交易
  - `buy_price = trade_exchange.get_deal_price(...)`
  - `buy_amount = value / buy_price`
  - `factor = trade_exchange.get_factor(...)`
  - `buy_amount = round_amount_by_trade_unit(...)`
  - 创建 `Order(direction=Order.BUY)` 加入 `buy_order_list`

最终返回：
- `TradeDecisionWO(sell_order_list + buy_order_list, self)`

#### (4) 当前代码与参数依赖注意点

- `method_buy/method_sell/only_tradable/forbid_all_trade_at_limit` 没有在 `custom_train_backtest.py` 中显式传入，可能依赖 `TopkDropoutStrategy` 的默认值。
- 如果你希望策略利用 `MAIRU_SIGNAL` 或其他信号列，需要在策略侧做相应使用；当前策略只用 `pred_score`（模型预测分数）来做 topk，并用涨幅过滤做二次筛选。

### 2.4 `my_scripts/custom_ops.py`（QLib 自定义算子：递推 SMA）

该文件实现了一个名为 `SMA` 的自定义算子类，用于 QLib 表达式系统。

#### `class SMA(Rolling)`

文档字符串解释了 Tongdaxin 风格的平滑移动平均形式：
- `SMA(X, N, M) = (M * X + (N - M) * SMA[1]) / N`

关键实现点：
- `__init__(feature, N, M=1)`：
  - 校验 `N > 0`、`0 < M <= N`
  - 调用 `super().__init__(feature, N, "sma")`
- `_load_internal(...)`：
  - 加载底层序列 `series = self.feature.load(...)`
  - 取 `values.astype(np.float64)` 后做递推计算
  - 找到第一个非 NaN 的位置 `first_valid`
  - 之后：
    - 若当前值为 NaN -> `sma[i] = np.nan`
    - 否则 `sma[i] = alpha * values[i] + beta * sma[i-1]`
  - 返回 `pd.Series(sma, index=series.index)`
- `get_longest_back_rolling()`：
  - SMA 递推依赖历史“全部先前数据”，因此返回值用一个启发式（近似 EMA 的窗口估算）来控制回溯长度。

#### 如何被主流程使用

- `custom_train_backtest.py` 在 `qlib.init(custom_ops=[SMA])` 中注册了该算子
- `custom_handler.py` 的 COST-KDJ 表达式里使用了 `SMA(L3_expr, 3, 1)`。

### 2.5 `my_scripts/custom_utils.py`（回测结果分析/持仓报告生成）

提供多种“面向结果 DataFrame/positions dict/Position 实例”的辅助函数。

#### (1) `analyze_and_visualize_positions(report, positions, figsize=(14, 10))`

特点：
- 为 QLib 0.9.7 的 positions 结构设计：假设 `positions[date_str]` 是一个 dict，里面每个 instrument 对应 `amount/price/value`。
- 把输入 `report` 的索引标准化为 `DatetimeIndex`，并与 positions 的日期集合做交集。

逐日计算内容包括：
- 持仓股票数量 `num_stocks`
- 股票市值、现金市值、账户总值与对账误差（`reconciliation_diff / reconciliation_error_pct`）
- 集中度：top5/top10 价值占比
- 换手率：基于“持仓集合的对称差”计算
- 持仓天数统计 `holding_days`

输出：
- 返回包含 `analysis_df / avg_holding_days / total_unique_stocks / figure`
- 同时会 `plt.show()` 直接展示图。

#### (2) `generate_position_report(positions_dict, output_file='position_analysis.txt')`

作用：
- 把 positions 的每个交易日持仓信息写入文本报告。

兼容类型：
- 若 `position_data` 是 `pd.DataFrame`：写 DataFrame 统计信息
- 若 `position_data` 是 `qlib.backtest.position.Position`：调用其方法计算总市值、现金、逐股票金额/权重/持仓天数，并把明细写成 tab 分隔的表格片段

副作用：
- 会写文件 `output_file`，默认值 `position_analysis.txt`

#### (3) `analyze_position_by_date(positions_dict, target_date=None)`

- 默认取 positions_dict 的第一个日期键
- 打印指定日期持仓的明细/类型，并返回对应日期的数据

#### (4) `pprint_position_report(positions_dict)`

- 打印 positions 的数据结构信息：
  - dict 类型、keys、大小
  - 取样本日期并打印样本数据类型、DataFrame 形状与列名（或 pprint 字典内容）

#### (5) `pprint_risk_analysis(analysis_result)`

- 对 `risk_analysis` 返回字典逐项打印
- float 用 `:.4f` 格式化

#### (6) 文件末尾的说明注释

文件末尾包含一段 `""" ... """` 注释，说明曾对 QLib 内部 `position.py` 的 `update_order` 做过日志改动（示例 logger 记录 BUY/SELL 与成交成本等）。

## 3) 关键配置速查（训练与回测最重要的开关）

你在 `custom_train_backtest.py` 里最常需要动的配置主要集中在以下几块：

1. `qlib.init(...)`
- `provider_uri`：必须指向你的 QLib 数据目录
- `redis_*`：如果你需要缓存/锁机制
- `custom_ops=[SMA]`：确保表达式里能用自定义 `SMA`
- `exp_manager`：MLflow 记录实验

2. 时间切片
- `fit_*`：训练/验证
- `test_*`：回测

3. `data_handler_config`（特征开关）
- `include_alpha158=True/False`
- `include_cost_kdj=True/False`
- `include_signal=True/False`（决定是否产出 `MAIRU_SIGNAL`）
- `include_lz=True/False`（决定是否产出 VOLDDX/BIGDDX/LIMIT_STATUS 等）

4. `port_analysis_config`（策略与回测）
- 策略：
  - `topk`
  - `n_drop`
  - `hold_thresh`
- 回测：
  - `limit_threshold`
  - `deal_price`（close/open/vwap 等）
  - `open_cost/close_cost/min_cost`

## 4) 当前代码现状与潜在注意点（建议重点核对）

1. `dynamic_filter` 定义了但没有生效
- `dynamic_filter = ExpressionDFilter(...)` 被创建，但 `D.instruments(... filter_pipe=[exclude_filter])` 没有包含它。

2. `include_signal=False` 可能导致 `MAIRU_SIGNAL` 不存在
- `custom_train_backtest.py` 中 `data_handler_config` 设置了 `include_signal=False`；
- `custom_handler.py` 中 `MAIRU_SIGNAL` 仅在 `include_cost_kdj=True` 且 `include_signal=True` 时生成。
- 若你后续策略逻辑打算使用 `MAIRU_SIGNAL`，需要同步把开关打开并在策略侧消费它。

3. 特征重要性索引映射假设
- 脚本把 `feat_imp_series.index` 解析成 `Column_x`，然后用 `all_features[number]` 映射列名。
- 这依赖你当前 QLib/模型版本下 feature importance 的返回格式。

4. 信号分析产物文件名可能随版本变化
- 脚本里有注释：`recorder.load_object("sig_analysis/ic.pkl")` 可能找不到。
- 建议你在实际运行后查看 recorder artifacts 的目录结构，确认正确的对象路径。

## 5) 与已有文档的关系

`my_docs/` 目录里已有一些背景类说明文件，例如：
- `[my_docs/order.md](my_docs/order.md)`：订单对象与交易所模拟机制的说明
- `[my_docs/position.md](my_docs/position.md)`：Position/头寸更新机制背景

本文主要聚焦 `my_scripts/` 的“项目级实现与串联方式”。

