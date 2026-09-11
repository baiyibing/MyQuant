# Qlib 回测走查结果（Code Walkthrough + 架构评估）

时间：2026-03-25  
版本上下文：Qlib 0.9.7（与你的查询一致）  
范围：`my_scripts/` 中与回测、特征/标签构建、过滤、交易执行相关的关键脚本与扩展实现。

---

## 0. 回测流程端到端走查（你当前脚本实际接入的链路）

入口脚本：`my_scripts/custom_train_backtest.py`

1. `qlib.init(...)`：初始化数据提供者、缓存、Redis（若可用）、自定义算子 `SMA`（来自 `my_scripts/custom_ops.py`）。
2. `handler = Alpha158CostKDJ(**data_handler_config)`：构建数据处理器（自定义因子/信号扩展），并尝试配置 `infer_processors`（标准化/填充）。
3. `dataset = DatasetH(handler=handler, segments={train,valid,test})`：按日期切分训练/验证/测试段。
4. `model.fit(dataset)`：用 `LGBModel` 训练；内部会分别从 `train/valid` 取 `col_set=["feature","label"]` 且使用 `DataHandlerLP.DK_L`。
5. `SignalRecord.generate()`：生成 `pred.pkl`（预测分数）与 `label.pkl`（真实标签）。
6. `PortAnaRecord.generate()`：执行回测，输出 `portfolio_analysis/report_normal_1day.pkl` 与持仓等产物。
7. 你脚本中还进行了额外：读取 `pred.pkl`、手动 `dataset.prepare("test", col_set=["feature","label"])`、以及额外的 IC 可视化。

结论：流程本身是“能跑的”，但当前实现与“你在脚本里标注的意图”（过滤/处理器/基准口径等）存在多处脱节，导致回测逻辑未满足黄金准则所要求的严谨一致性。

---

## 1. 严重度最高的发现（Critical / High）

### 1.1 Critical：`infer_processors/learn_processors` 可能未按预期生效（处理链路传递断点）

涉及文件：
- `my_scripts/custom_handler.py`
- `qlib/data/dataset/handler.py`

问题点：
- 你的 `Alpha158CostKDJ.__init__` 接收了 `infer_processors/learn_processors`，但在调用父类 `Alpha158`（最终是 `DataHandlerLP`）时没有把这些参数继续传入父类构造函数，而是仅 `super().__init__(*args, **kwargs)`。
- Qlib 的 `DataHandlerLP` 会在父类构造函数中把 `infer_processors/learn_processors` 初始化成处理链路并生效；如果父类没有收到对应参数，你在外部配置的处理器可能不会被实际使用。

证据（关键实现）：
- `my_scripts/custom_handler.py` 中父类调用未传递 processors（只把它们存成了实例字段，但父类不会读这些字段）：  
```99:112:my_scripts/custom_handler.py
    def __init__(self, *args, cost_window=250, learn_processors=None, infer_processors=None, include_alpha158=False, include_cost_kdj=False, include_signal=False, include_lz=False, **kwargs):
        ...
        super().__init__(*args, **kwargs)
```
- Qlib `DataHandlerLP` 在构造阶段读取并实例化 processors 链路（因此必须通过父类构造参数传入）：  
```481:508:qlib/data/dataset/handler.py
        for pname in "infer_processors", "learn_processors", "shared_processors":
            for proc in locals()[pname]:
                getattr(self, pname).append(
                    init_instance_by_config(
                        proc,
                        None if (isinstance(proc, dict) and "module_path" in proc) else processor_module,
                        accept_types=processor_module.Processor,
                    )
                )
```

风险影响：
- 特征标准化、异常值处理、填充策略等可能与“你以为的配置”不一致。
- 进而影响模型训练、验证、测试预测分布，以及后续策略选择与回测表现的可解释性与可复现性。

建议改进方向（不直接修改代码）：
- 确保 `Alpha158CostKDJ.__init__` 在 `super().__init__` 时将 `infer_processors` 与 `learn_processors` 作为关键参数传给父类（或通过 `kwargs` 传入父类期望字段），使 Qlib 的处理链路严格可控。

---

### 1.2 Critical：你写的涨停/排除过滤器在训练/回测中未接入（意图未落地）

涉及文件：
- `my_scripts/custom_train_backtest.py`

证据：
- `filter_pipe` 相关配置在 `data_handler_config` 中被注释掉：  
```219:242:my_scripts/custom_train_backtest.py
        # "filter_pipe":[exclude_filter,limit_up_filter]
```
- 对照验证函数 `verify_limit_up_filter(...)` 的调用也被注释掉：  
```342:349:my_scripts/custom_train_backtest.py
    # verify_limit_up_filter(
```

结论：
- `UnifiedLimitUpFilter`、`exclude_filter`、`dynamic_filter` 当前并没有真正参与 train/valid/test 数据生成与回测组合构建。
- 与“你想在 DataHandler 中自动作用于 Train/Valid/Test”这一设想不一致。

建议改进方向：
- 恢复 `filter_pipe` 接入，并至少对 train/valid/test 三段做抽样断言或打印剔除前后 `LIMIT_STATUS` 或样本数变化，验证过滤器确实生效。

---

### 1.3 High：基准 `benchmark` 与注释目标不一致（影响相对指标解释）

涉及文件：
- `my_scripts/custom_train_backtest.py`

证据：
- 变量值：`benchmark = "SH601727"`；但注释写的是“沪深300”。  
```200:201:my_scripts/custom_train_backtest.py
    benchmark = "SH601727"  # 设置业绩比较基准为沪深300指数代码
```

Qlib 口径下常见 benchmark 默认是 `SH000300`（CSI300）。你的基准很可能不是你以为的沪深300，导致 excess return / 信息比率 / 最大回撤的相对结论偏差。

建议改进方向：
- 明确你想用的指数/基准并修正为 Qlib 数据中对应的标准标的（通常 CSI300：`SH000300`）。

---

## 2. 因果一致性（黄金准则）复核：总体“没有明显未来函数”，但对齐验证需要显式 shift

### 2.1 pred 与交易时点对齐机制：TopkDropoutStrategy 使用 `shift=1` 取信号

涉及文件：
- `qlib/contrib/strategy/signal_strategy.py`

证据（策略回测时取 pred 的时间窗）：  
```138:144:qlib/contrib/strategy/signal_strategy.py
        trade_start_time, trade_end_time = self.trade_calendar.get_step_time(trade_step)
        pred_start_time, pred_end_time = self.trade_calendar.get_step_time(trade_step, shift=1)
        pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)
```

这意味着：在交易日 T 进行决策时，用的是截至 T-1（或对应 shift 的前一段）的 pred，从机制上降低了未来函数风险。

### 2.2 Alpha158 label 的 horizon：Ref($close,-2)/Ref($close,-1)

涉及文件：
- `qlib/contrib/data/handler.py`

证据：  
```151:153:qlib/contrib/data/handler.py
    def get_label_config(self):
        return ["Ref($close, -2)/Ref($close, -1) - 1"], ["LABEL0"]
```

因此 pred/label 的“预测目标时间”与“回测交易日的 return 计算时间”之间存在天然偏移。  
你在脚本末尾做手动 `pred_label` concat 与 IC 图时，当前通常是安全的（因为两者都来自同一套 `dataset.prepare("test", ...)` 的 label/pred 索引体系），但任何进一步与 `report_normal_1day` 逐日一一对齐的检查，都必须显式考虑 shift/时间窗选择。

建议改进方向：
- 增加一次“pred.pkl datetime 范围 vs report index 范围”的对齐自检，并确认首日/尾日对应关系是否正确。

---

## 3. 交易执行与成本口径：存在“交易假设-过滤假设”不一致的结构性风险

涉及文件：
- `my_scripts/custom_train_backtest.py`
- `qlib/backtest/exchange.py`
- `qlib/contrib/strategy/signal_strategy.py`

发现要点：

1. 你设置了 `exchange_kwargs`：
   - `deal_price="close"`（使用收盘价作为成交价）
   - `limit_threshold=0.095`（用 `$change` 判定涨跌停/限价）
   - `open_cost/close_cost/min_cost`（手续费口径）

2. 你当前没有接入涨停过滤（第 1.2 点已确认），因此“想剔除涨停样本”的假设与“交易所层面的限价禁止/可交易逻辑”不是同一个口径。

3. 策略层面，`TopkDropoutStrategy` 默认 `forbid_all_trade_at_limit=True`：  
当涨跌停触发时，策略会直接禁止交易（并非你自定义过滤器“剔除样本”）。

证据（策略默认 forbid）：  
```88:123:qlib/contrib/strategy/signal_strategy.py
        forbid_all_trade_at_limit=True,
...
        if forbid_all_trade_at_limit:
            strategy will not do any trade when price reaches limit up/down
```

风险影响：
- 即使你未来恢复 `filter_pipe`，过滤器与策略 forbid / exchange 的 limit_threshold 仍可能形成“双重、且口径不同”的限制，从而导致实际组合成分与真实交易规则偏离你预期。

建议改进方向：
- 先明确你的“黄金准则下的交易规则”到底想表达哪一种：
  - A) 只避免买入涨停（允许卖出/保留部分持仓处理）
  - B) 交易所撮合层面完全禁止在限价时买卖
  - C) 统一用 `$zhangting` 作为过滤与限价依据（需要你在 handler/数据与 exchange 口径一致）
- 然后把过滤器/策略/交易所层限制口径统一起来。

---

## 4. 架构级改进建议（按优先级给出下一步）

1. **优先级 1：修复处理器链路可控性**
   - 让 `Alpha158CostKDJ` 的 `infer_processors/learn_processors` 真正传入并由 Qlib `DataHandlerLP` 初始化处理链路。

2. **优先级 2：恢复并验证 `filter_pipe` 生效**
   - 接回 `data_handler_config["filter_pipe"] = [exclude_filter, limit_up_filter]`。
   - 恢复 `verify_limit_up_filter(...)` 或至少做 train/valid/test 抽样断言。

3. **优先级 3：修正 benchmark**
   - 把代码中的 benchmark 与注释目标（沪深300/CSI300）对齐，避免相对指标误导。

4. **优先级 4：统一涨停处理口径**
   - 决策你要的是“过滤样本”还是“交易所禁交易”，并同步调整策略/交易所 limit_threshold 与过滤字段（`$zhangting` vs `$change`）。

5. **优先级 5：加入 pred 与回测逐日对齐自检**
   - 输出 `pred.pkl` 的第一/最后交易日与 `report_normal_1day` index 对应关系。

---

## 5. 可选的验证清单（建议你下一轮回跑时做）

- 打印 `dataset.prepare("train","valid","test", col_set=["feature","label"])` 中 label 缺失比例（NaN/0）变化；
- 在打开过滤器后，对三段分别打印样本数与（若存在）`LIMIT_STATUS` 分布；
- 将 `benchmark` 与实际指数一致后，重新评估 IR / max_drawdown 的稳定性；
- 做一次 pred->回测 return 的首尾对齐检查，确保 shift 口径无误。

