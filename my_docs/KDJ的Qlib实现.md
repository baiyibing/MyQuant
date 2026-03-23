**这个通达信公式的大部分逻辑可以用Qlib实现，核心挑战在于筹码分布函数 `COST` 的处理。**

```python
    L1:=COST(0.01);
    L2:=COST(99.99);
    L3:=(C-L1)/(L2-L1)*100;
    K:SMA(L3,3,1),COLORWHITE;
    D:SMA(K,3,1),COLORYELLOW;
    J:3*K-2*D,COLORFF00FF;
    MAIRU:=CROSS(J,K) AND J<80;
```

这个公式实际上由两部分组成：
1. **筹码分布部分**：`COST(0.01)` 和 `COST(99.99)` 计算极端位置的获利盘价格
2. **KDJ指标部分**：对标准化后的价格 `L3` 进行SMA平滑，生成K/D/J值及买入信号

让我详细拆解一下Qlib对这两部分的支持情况：

---

### 一、筹码分布函数 COST 的处理（核心难点）

**结论：Qlib 原生表达式引擎没有内置 `COST` 函数，但社区已有成熟实现。**

`COST(0.01)` 表示获利盘比例为1%时的价格（即筹码分布的左端），`COST(99.99)` 则是获利盘99.99%的价格（右端）。这类筹码分布指标需要：
- 每日完整的成交价格分布数据
- 换手率加权计算（通常用半衰期加权）

根据聚宽社区的复现项目，已有开发者将筹码分布算法整合到Qlib框架中：

```python
# 参考实现：scr/distribution_of_chips.py
# 支持两种筹码分布算法：
# 1. 三角分布 (triangular distribution)
# 2. 平均分布 (uniform distribution)
```

**实现方案**：
```python
# 需要引入扩展的筹码分布算子
from scr.cyq_ops import CYQ_COST

# 在Qlib表达式中可以这样使用（需先注册算子）
cost_1 = CYQ_COST(0.01)   # COST(0.01) 的等价实现
cost_99 = CYQ_COST(99.99) # COST(99.99)
```

### 二、KDJ部分的Qlib实现（完全支持）

公式中的K/D/J计算使用的是 `SMA`（简单移动平均）函数，**这是Qlib原生支持的**。

#### 基础表达式实现

```python
from qlib.data.dataset.loader import QlibDataLoader

# 通达信公式的Qlib表达式版本
# 前提：需要先定义 cost_1 和 cost_99 为自定义算子或字段

l3_expr = '( $close - cost_1 ) / ( cost_99 - cost_1 ) * 100'
k_expr = 'SMA( l3, 3, 1 )'      # 对应 K:SMA(L3,3,1)
d_expr = 'SMA( k, 3, 1 )'       # 对应 D:SMA(K,3,1)
j_expr = '3 * k - 2 * d'        # 对应 J:3*K-2*D

# 买入信号：CROSS(J,K) AND J<80
# Qlib中的CROSS可以用条件表达式模拟
buy_expr = '(Ref(j, -1) <= Ref(k, -1)) & (j > k) & (j < 80)'

# 完整的数据加载配置
data_loader_config = {
    "feature": (
        [
            l3_expr,
            k_expr,
            d_expr,
            j_expr,
            buy_expr,
        ],
        ['L3', 'K', 'D', 'J', 'BUY_SIGNAL']
    ),
    "label": (['Ref($close, -1)/$close - 1'], ['LABEL'])
}
```

### 三、完整实现方案

#### 方案一：使用社区筹码分布实现（推荐）

```python
# 1. 先注册筹码分布算子（参考 Hugo2046 的实现）
from qlib.data.ops import register_ops
from scr.distribution_of_chips import CYQ_COST

register_ops({'CYQ_COST': CYQ_COST})

# 2. 构建完整公式
cost_001 = 'CYQ_COST(0.01)'
_cost_999 = 'CYQ_COST(99.99)'
l3 = f'($close - {cost_001}) / ({_cost_999} - {cost_001}) * 100'

# 3. 使用嵌套表达式实现SMA递推
# 注意：Qlib的SMA是滚动平均，与通达信的递归SMA有细微差异
k = f'SMA({l3}, 3, 1)'
d = f'SMA({k}, 3, 1)'
j = f'3*{k} - 2*{d}'

# 4. 买入信号（金叉 + J<80）
buy_signal = f'(Ref({j}, -1) <= Ref({d}, -1)) & ({j} > {d}) & ({j} < 80)'

# 5. 加载数据
loader = QlibDataLoader(config={
    "feature": ([l3, k, d, j, buy_signal], ['L3', 'K', 'D', 'J', 'BUY']),
    "label": (['Ref($close, -1)/$close - 1'], ['LABEL'])
})
df = loader.load(instruments='csi300', start_time='2020-01-01', end_time='2023-12-31')
```

#### 方案二：简化近似（如果无法获得筹码分布数据）

```python
# 用高低价范围替代筹码分布
# 将 L3 近似为 (C - LLV(L, N)) / (HHV(H, N) - LLV(L, N)) * 100
# 这本质上是威廉指标（%R）的变体

# 使用60日高低价范围作为近似
l3_approx = '($close - MIN($low, 60)) / (MAX($high, 60) - MIN($low, 60)) * 100'
k = f'SMA({l3_approx}, 3, 1)'
d = f'SMA({k}, 3, 1)'
j = f'3*{k} - 2*{d}'

# 然后按同样逻辑计算买入信号
```

### 四、重要提醒

1. **SMA的差异**：通达信的 `SMA(X,N,M)` 是递归平滑移动平均，而Qlib的 `SMA` 是标准的简单移动平均。对于参数 `(3,1)`，两者差异不大，但如果严格复现，可能需要自定义 `SMA` 算子。

2. **CROSS函数**：Qlib没有直接的 `CROSS` 函数，但可以用条件表达式模拟：`(Ref(j, -1) <= Ref(k, -1)) & (j > k)`。

3. **筹码分布数据依赖**：精确计算 `COST` 需要逐笔成交数据或高频分布数据。如果只有日线OHLCV，筹码分布只能近似估算。

4. **已有开源实现**：建议直接参考 GitHub 上的 `QuantsPlaybook` 项目，其中 `scr/distribution_of_chips.py` 提供了完整的筹码分布算法，可以直接集成到Qlib中使用。

### 五、总结

| 公式组件 | Qlib支持情况 | 备注 |
|---------|-------------|------|
| `COST(0.01)` / `COST(99.99)` | ⚠️ 需扩展 | 有社区实现，非原生 |
| `SMA` 平滑 | ✅ 原生支持 | 表达式引擎内置 |
| `CROSS` 金叉 | ✅ 可模拟 | 用条件表达式实现 |
| 条件判断 `J<80` | ✅ 原生支持 | 比较运算符 |

**结论**：这个通达信公式**可以用Qlib等价实现**，但需要引入社区扩展的筹码分布算子。如果你只需要KDJ部分（用高低价范围替代筹码分布），则完全可以用Qlib原生表达式引擎实现。