import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter

# 示例数据准备（需替换为实际数据）
dates = pd.date_range(start="2025-01-01", periods=100, freq="D")
close_prices = np.random.uniform(10, 20, 100)  # 随机生成收盘价

# 模拟成本分布分位点（实际需通过成交量/价格分布计算）
cost_low = np.percentile(close_prices, 1)    # COST(0.01)
cost_high = np.percentile(close_prices, 99.99)  # COST(99.99)

# 计算L3: (C - L1) / (L2 - L1) * 100
l3 = (close_prices - cost_low) / (cost_high - cost_low) * 100

# 计算K, D, J（SMA实际为EMA，权重因子=1）
def ema(data, window):
    return data.ewm(span=window, adjust=False).mean()

k = ema(pd.Series(l3), 3)  # K线
d = ema(k, 3)              # D线
j = 3 * k - 2 * d          # J线

# 标记买入信号：J上穿K且J<80
buy_signal = (j > k) & (j.shift(1) <= k.shift(1)) & (j < 80)
buy_positions = j[buy_signal]  # 信号点的J值位置

# 绘制图形
fig, ax = plt.subplots(figsize=(14, 8))
ax.plot(dates, k, color='white', linewidth=2, label='K线')
ax.plot(dates, d, color='yellow', linewidth=2, label='D线')
ax.plot(dates, j, color='#FF00FF', linewidth=2, label='J线')  # 粉紫色

# 标记买入信号（箭头）
for date, pos in zip(dates[buy_signal], buy_positions):
    ax.annotate('↑', xy=(date, pos), xytext=(0, 15),
                textcoords='offset points',
                color='lime', fontsize=14, ha='center')

# 设置图形属性
ax.set_title('通达信指标可视化：K/D/J线与买入信号', fontsize=16)
ax.set_ylabel('指标值', fontsize=12)
ax.xaxis.set_major_formatter(DateFormatter("%Y-%m-%d"))
ax.legend(loc='upper left')
ax.grid(alpha=0.3)
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

"""

关键说明​
1.
​成本分布计算（COST函数）​​

•
实际需基于历史成交量与价格分布计算分位点（示例用np.percentile简化）。

•
建议通过tushare/akshare等库获取详细订单簿数据
。

2.
​SMA与EMA的区别​

•
通达信中 SMA(序列, N, M)的 M=1时等价于 ​EMA​（指数平滑）而非简单移动平均
。

•
Python中需用 .ewm(span=N).mean()实现。

3.
​信号标记逻辑​

•
DRAWICON的箭头通过 annotate实现，位置在信号点的J值处
。

•
条件 CROSS(J,K)等价于 (J_t > K_t) & (J_{t-1} <= K_{t-1})。

​输出效果​
•
​K线​：白色轨迹（短期动量）

•
​D线​：黄色轨迹（中期趋势）

•
​J线​：粉紫色（加速震荡器）

•
​买入信号​：J线上穿K线且J<80时显示绿色箭头↑

https://via.placeholder.com/800x400/2C2C2C/FFFFFF?text=K/D/J+Chart+with+Buy+Signals

（示意图：实际运行将显示动态曲线与箭头标记）

​扩展建议​
•
​数据源集成​：使用 tushare.get_hist_data()替换随机数据
。

•
​多图叠加​：可增加K线主图与成交量副图，使用 plt.subplots(2,1)实现
。

•
​参数优化​：调整EMA周期（如 span=5）或信号阈值（如 J<70）以适配不同品种。

"""