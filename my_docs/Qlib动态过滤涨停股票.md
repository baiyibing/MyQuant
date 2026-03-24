可以实现，但需要注意一个重要细节：**涨停判断涉及“当日收盘价 vs 昨日收盘价”，若在特征工程阶段直接过滤，可能引入未来信息。**

Qlib 提供了强大的 `ExpressionDFilter` 过滤器，允许在数据加载时动态筛选股票。下面我会给出具体的实现方法和配置示例，并重点说明如何规避数据泄露风险。

---

### 1. 核心方案：自定义过滤器

Qlib 的 `ExpressionDFilter` 可以根据表达式动态过滤，我们可以利用它来判断涨停。

**核心逻辑**：涨停条件通常是 `close >= pre_close * 1.095`（A股主板）。
但在 Qlib 中，为了不引入未来数据，通常使用 `Ref` 函数取前一日的 `close` 来构造比较表达式。

#### 具体实现代码

你可以创建一个自定义过滤器类，或者直接在配置文件中定义表达式。

```python
from qlib.data.filter import ExpressionDFilter

class LimitUpFilter(ExpressionDFilter):
    """
    动态涨停过滤器（防止未来信息泄露版本）
    """
    def __init__(self, limit_pct=0.095, fstart_time=None, fend_time=None, keep=False):
        # rule_expression 构建规则：当日收盘价 >= 昨日收盘价 * (1+涨停幅度)
        # 注意：使用 $close 和 Ref($close, 1) 配合
        rule = f"$close >= Ref($close, 1) * {1 + limit_pct}"
        super().__init__(
            rule_expression=rule,
            fstart_time=fstart_time,
            fend_time=fend_time,
            keep=keep  # False 表示过滤掉涨停的股票（即剔除）
        )
    
    def _getFilterSeries(self, instruments, fstart, fend):
        # 这里可以添加额外的逻辑，比如排除上市首日等
        return super()._getFilterSeries(instruments, fstart, fend)

# 使用示例
filter_limit_up = LimitUpFilter(limit_pct=0.095, keep=False)
```

**参数说明**：
- `rule_expression`：过滤表达式，返回布尔值。`True` 表示满足条件（此处满足涨停条件），会被过滤。
- `keep`：`False` 表示将满足 `rule_expression` 的股票剔除；`True` 则相反。
- `fstart_time` / `fend_time`：可以限定过滤生效的时间范围，比如只过滤特定年份。

---

### 2. 如何分别应用于 Train / Valid / Test

Qlib 的数据集分割（训练、验证、测试）是在 `DataHandler` 或 `Estimator` 配置中通过时间区间切分的。**我们不需要三个单独的过滤器，只需要一个过滤器，但它会随着时间窗口的滑动而动态执行。**

在 Qlib 的配置文件中，你将过滤器挂在 `data` 部分，Qlib 在加载每一个时间切片的数据时，都会动态执行一次过滤逻辑，自动过滤掉该时间段内的涨停股票。

#### 配置示例（YAML格式）

```yaml
data:
  class: DatasetH
  module_path: qlib.data.dataset
  kwargs:
    handler:
      class: DataHandler
      module_path: qlib.data.dataset.handler
      kwargs:
        # 关键点：在这里配置过滤器
        filter:
          # 使用自定义过滤器类
          class: LimitUpFilter
          module_path: your_module.limit_up_filter  # 替换为你的文件路径
          kwargs:
            limit_pct: 0.095
            keep: False   # 剔除涨停
        # 其他参数
        instruments: "csi300"
        start_time: "2010-01-01"
        end_time: "2020-12-31"
        # ... 特征配置等
    segments:
      train: ["2010-01-01", "2017-12-31"]
      valid: ["2018-01-01", "2018-12-31"]
      test: ["2019-01-01", "2020-12-31"]
```

当 Qlib 加载训练集时间区间时，过滤器会计算该区间内每天是否涨停；验证集和测试集也会分别独立计算，从而实现“动态过滤”。

---

### 3. 关键注意点：避免未来信息泄露

在实现涨停过滤时，有一个非常容易踩的坑：

> **`$close` 和 `Ref($close, 1)` 在同一行数据中，`Ref($close, 1)` 代表的是前一个交易日的值。**
> 如果你直接在过滤器里写 `$close / $open > 1.095`，这本身没问题。
> **但是**，如果你的特征集里包含了当天的 `$close`（标签通常也是由 `$close` 计算得出），那么在训练时，模型会学到 `$close` 的值，这就造成了**未来信息泄露**。

**解决方案**：
确保过滤器的执行独立于特征计算，或者**不要在用于预测的特征中包含收盘价相关的未来函数**。通常的做法是：**先过滤，再生成特征**。Qlib 的 `DataHandler` 处理顺序保证了这一点，但在自定义特征时需格外小心。

### 4. 更严谨的替代方案（高级）

如果你担心表达式过滤的性能或准确性，另一种方案是**在数据预处理阶段（入库前）打标签**。

1. 在原始数据入库前，增加一列 `is_limit_up`（布尔值）。
2. 然后在 Qlib 过滤器中使用 `$is_limit_up == 0` 作为过滤规则。

这样做的好处是：
- 逻辑清晰，避免了在表达式中进行复杂的除法运算。
- 可以处理特殊情形（如科创板 20% 涨停、北交所 30% 涨停），只需在入库时判断即可。

### 总结

1. **可以实现**：利用 Qlib 的 `ExpressionDFilter` 或自定义 `SeriesDFilter`。
2. **配置位置**：在 `DataHandler` 的 `filter` 参数中配置，它会自动作用于训练、验证、测试的全流程。
3. **避坑指南**：注意涨停判断中 `Ref` 的使用，并确保标签数据不包含未来信息。