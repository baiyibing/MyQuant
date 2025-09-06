#股市行情数据获取和作图 -2
from  Ashare import *          #股票数据库    https://github.com/mpquant/Ashare
from  MyTT import *            #myTT麦语言工具函数指标库  https://github.com/mpquant/MyTT
import glob
import os
import pyarrow.parquet as pq
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.dates import DateFormatter
import mplfinance as mpf
from matplotlib.ticker import MultipleLocator
from timeit import default_timer as timer


def resample_weekly(daily_df):
    # 方法2：先填充缺失的交易日（使用前向填充），然后再重采样
    # 生成一个完整的日期索引以确保连续性
    all_dates = pd.date_range(start=daily_df.index.min(), end=daily_df.index.max(), freq='D')
    daily_df = daily_df.reindex(all_dates)
    # 对OHLC等价格数据，通常使用前向填充（ffill）来填充非交易日的值
    with pd.option_context("future.no_silent_downcasting", True):
        daily_df = daily_df.ffill().infer_objects(copy=False)
    # 对于成交量，非交易日可以填充0
    if 'volume' in daily_df.columns:
        # daily_df['volume'].fillna(0, inplace=True)
        daily_df.fillna({'volume': 0}, inplace=True)
    # 然后再进行正常的周重采样
    return daily_df.resample('W').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'symbol': 'first',
        'amount': 'sum',
        'volume': 'sum'
    }).dropna()

def MAIRU(df):
    CLOSE = df.close.values
    OPEN = df.open.values  # 基础数据定义，只要传入的是序列都可以  Close=df.close.values
    HIGH = df.high.values
    LOW = df.low.values  # 例如  CLOSE=list(df.close) 都是一样

    MA5 = MA(CLOSE, 5)  # 获取5日均线序列
    MA10 = MA(CLOSE, 10)  # 获取10日均线序列
    MA20 = MA(CLOSE, 20)  # 获取20日均线序列
    up, mid, lower = BOLL(CLOSE)  # 获取布林带指标数据

    epsilon = 1e-8  # 计算价格标准化位置（添加epsilon防止除零）

    L1 = COST(CLOSE, 0.01 / 100)  # 最低1%成本位
    L2 = COST(CLOSE, 99.99 / 100)  # 最高99.99%成本位
    L3 = (CLOSE - L1) / (L2 - L1 + epsilon) * 100;  # 价格标准化位置
    K = SMA(L3, 3, 1)  # COLORWHITE;                  L3的3日指数加权平均
    D = SMA(K, 3, 1)  # COLORYELLOW;                  K的3日指数加权平均
    J = 3 * K - 2 * D  # COLORFF00FF;                             动量指标
    MAIRU = CROSS(J, K) & (J < 80)  & (CLOSE >= MA20) # J线上穿K线且J值低于80,而且站上了20日均线

    # df['MAIRU'] = MAIRU
    # SettingWithCopyWarning:
    # A value is trying to be set on a copy of a slice from a DataFrame.
    # Try using .loc[row_indexer,col_indexer] = value instead
    df.loc[:, 'MAIRU'] = MAIRU

    buy_signals = df[df['MAIRU']]

    return buy_signals

# -----------------------------------------------------作图显示-----------------------------------------------------------
def DRAWICON(df):
    CLOSE = df.close.values
    OPEN = df.open.values  # 基础数据定义，只要传入的是序列都可以  Close=df.close.values
    HIGH = df.high.values
    LOW = df.low.values  # 例如  CLOSE=list(df.close) 都是一样

    MA5 = MA(CLOSE, 5)  # 获取5日均线序列
    MA10 = MA(CLOSE, 10)  # 获取10日均线序列
    up, mid, lower = BOLL(CLOSE)  # 获取布林带指标数据

    epsilon = 1e-8  # 计算价格标准化位置（添加epsilon防止除零）

    L1 = COST(CLOSE, 0.01 / 100)  # 最低1%成本位
    L2 = COST(CLOSE, 99.99 / 100)  # 最高99.99%成本位
    L3 = (CLOSE - L1) / (L2 - L1 + epsilon) * 100;  # 价格标准化位置
    K = SMA(L3, 3, 1)  # COLORWHITE;                  L3的3日指数加权平均
    D = SMA(K, 3, 1)  # COLORYELLOW;                  K的3日指数加权平均
    J = 3 * K - 2 * D  # COLORFF00FF;                             动量指标
    MAIRU = CROSS(J, K) & (J < 80)  # J线上穿K线且J值低于80

    # plt.rcParams 是 Matplotlib 中的一个字典对象，用于管理全局配置设置。通过操作这个字典，你可以自定义和调整 Matplotlib 绘制图形时的各种参数和属性。
    # 确保参数名称的准确性，可以通过 plt.rcParams.keys() 查看所有可用的配置参数。

    # 设置全局字体（解决中文乱码）
    plt.rcParams['font.sans-serif'] = ['SimHei']  # Windows 常用黑体
    # plt.rcParams['font.sans-serif'] = ['Microsoft YaHei']     # 微软雅黑
    # plt.rcParams['font.sans-serif'] = ['PingFang SC']         # macOS 苹方字体

    # 解决负号显示为方块的问题
    plt.rcParams['axes.unicode_minus'] = False

    # 创建双图布局,设置画布
    # plt.figure 是一个用于创建图形窗口的函数，其中 figsize 参数用于指定图形的宽度和高度，单位为英寸。
    # 例如，plt.figure(figsize=(10, 6)) 表示创建一个宽度为 10 英寸、高度为 6 英寸的图形窗口。
    plt.figure(figsize=(14, 10))

    # plt.suptitle函数用于在图形顶部添加一个居中的超标题。
    plt.suptitle('通达信指标Python实现 - K/D/J信号系统', fontsize=16)

    # 1. 价格走势+信号标记
    # subplot用于创建子图的函数。它允许你在一个图形窗口中创建多个子图，从而方便地进行多图绘制。
    # nrows子图的行数
    # ncols子图的列数
    # index子图的位置索引，从1开始
    ax1 = plt.subplot(3, 1, 1)

    # mpf.plot(df, type='candle', ax=ax1, style='binance', show_nontrading=False)
    # 在指定的子图对象 ax1 上绘制 DataFrame 中 'close'列（收盘价）的折线图，并自定义线条样式和图例标签
    # df.plot(x='col1', y='col2')在 Pandas 中是合法的，但若误用于 Matplotlib 对象会报错
    df['close'].plot(ax=ax1, label='收盘价', color='#1f77b4', linewidth=2)
    # ax1.plot(df.index, df['close'], 'g--', label='收盘价', alpha=0.7)
    # plt.plot()要求 x和 y数据必须作为位置参数传递，而非关键字参数
    ax1.plot(df.index, MA5, label='MA5', linewidth=0.5, alpha=0.7)
    ax1.plot(df.index, MA10, label='MA10', linewidth=0.5, alpha=0.7)

    # 标记买入信号
    buy_signals = df[df['MAIRU']]  # df[df['column'] > value]通过逻辑条件生成一个布尔值序列（True/False），再用该序列筛选DataFrame的行
    # scatter在子图对象 ax1上绘制散点图，用于标记特定数据点（如买入信号）
    # 散点的 x 轴坐标，表示买入信号的时间戳（如日期）
    # 散点的 y 轴坐标，表示买入信号触发时的收盘价
    # 散点尺寸 s 为 100（单位：点²），确保标记在图表中清晰可见
    # 散点形状 marker 为 红色上三角（▲），是金融图表中表示“买入”的通用符号
    # 设置图例标签label为“买入信号”，需配合 ax1.legend()显示图例
    ax1.scatter(x=buy_signals.index, y=buy_signals['close'], marker='^', s=100, color='red', label='买入信号')
    ax1.set_ylabel('价格', fontsize=12)  # 用于设置图表 y 轴标签的方法

    # grid方法用于配置网格线的显示和样式。它可以控制网格线的可见性、应用的刻度以及显示的轴。
    # linestyle '-'：实线（默认）':'：点线 '-.'：点划线 'None'：无线条
    # alpha控制网格线透明度，取值范围 [0, 1]。0.7表示70%不透明（30%透明），使网格线半透明以避免遮挡数据
    ax1.grid(visible=True, linestyle='--', alpha=0.7)
    ax1.legend(loc='upper left')  # 图例位置

    # 2. K/D/J指标
    ax2 = plt.subplot(3, 1, 2)
    ax2.plot(df.index, K, label='K线', color='white', linewidth=1.5)
    ax2.plot(df.index, D, label='D线', color='yellow', linewidth=1.5)
    ax2.plot(df.index, J, label='J线', color='#FF00FF', linewidth=1.5)

    # df.index为 x 轴数据，通常是时间序列（如日期索引）。若 df是 DataFrame，其索引需为 DatetimeIndex类型以确保时间刻度正确显示
    # K线D线J线 作为 y 轴数据，代表 K 线指标的数值序列（如随机振荡指标 K 值）。需与 df.index长度一致，形成坐标点 (时间, K值)

    # 添加参考线
    # 此代码的作用是在子图 ax2的 y 轴值为 80 的位置绘制一条水平参考线，常用于标记关键阈值（如超买超卖线、目标值、平均值等），辅助观察数据与特定值的关系。
    ax2.axhline(y=80, color='gray', linestyle='--', alpha=0.7)
    ax2.axhline(y=20, color='gray', linestyle='--', alpha=0.7)
    ax2.fill_between(df.index, 80, 100, color='red',
                     alpha=0.1)  # Y 轴范围 80 至 100 之间填充一个红色半透明区域，常用于标记关键阈值区间（如超买区、风险区或目标范围）
    ax2.fill_between(df.index, 0, 20, color='green', alpha=0.1)  # Y 轴范围 0 至 20 之间填充一个绿色半透明区域，常用于标记关键阈值区间（如超买区、风险区或目标范围）
    ax2.set_ylabel('K/D/J值', fontsize=12)
    # Matplotlib 默认会根据数据范围自动调整 Y 轴（auto-scaling）。set_ylim此函数 覆盖默认行为，确保 Y 轴始终显示指定范围（0–100），避免因数据波动导致图表比例失真
    ax2.set_ylim(0, 100)  # 强制将 ax2的纵坐标范围固定为 0 到 100，无论数据实际范围如何变化
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.legend(loc='upper left')

    # 3. 信号区域图
    ax3 = plt.subplot(3, 1, 3)
    # 绘制J线
    ax3.plot(df.index, J, color='#FF00FF', linewidth=1.5)
    # 标记买入区域
    # 在子图 ax3上绘制一条垂直参考线，常用于标记特定事件的时间点（如财报发布、政策变动等）
    # x 垂直线的 x 轴位置，通常为时间戳或数值。
    for date in buy_signals.index:
        ax3.axvline(x=date, color='#ff000066', linewidth=2)

    ax3.set_ylabel(ylabel='J线', fontsize=12)
    ax3.set_xlabel(xlabel='日期', fontsize=12)
    ax3.grid(visible=True, linestyle='--', alpha=0.5)

    # 动态计算并重排子图（subplots）的边距、间距和位置，确保所有元素（坐标轴标签、刻度标签、标题、图例）完整显示且互不重叠
    # 适用于单图或多子图场景，即使图表包含复杂标签或标题.使子图区域尽可能填充整个画布（Figure），减少空白区域，提升图表紧凑性与美观度
    plt.tight_layout()
    plt.subplots_adjust(top=0.94)
    plt.show()


start = timer()

# -----------------------------------------------------计算-------------------------------------------------------------

# 证券代码兼容多种格式 通达信，同花顺，聚宽
# sh000001 (000001.XSHG)    sz399006 (399006.XSHE)   sh600519 ( 600519.XSHG ) 

# df=get_price('000001.XSHG',frequency='1d',count=120)      #默认获取今天往前120天的日线行情
# print('上证指数日线行情\n',df.tail(5))

# 指定 Hive 表根目录（包含分区子目录）
table_path = "a_kline"  # hdfs:///path/to/hive_table或本地路径 /data/hive_table

# 创建 Dataset 并读取数据
dataset = pq.ParquetDataset(
    table_path,
    use_legacy_dataset=False,  # 必须使用新版实现（自动解析分区）
    filesystem=None            # 自动识别 HDFS/S3，或显式指定 fs 对象
)
table = dataset.read()          # 读取为 Arrow Table

print(u'读取为 Arrow Table', timer() - start)

all_df = table.to_pandas()          # 转为 Pandas DataFrame（可选）

print(u'转为 Pandas DataFrame', timer() - start)

all_df['date']=pd.to_datetime(all_df['date'])
# all_df.set_index(['date'], inplace=True)
# all_df.index.name=''

print(u' Pandas 转 to_datetime', timer() - start)

now = datetime.today()
normalized_today = now.replace(hour=0, minute=0, second=0, microsecond=0) # 当前日期（去除时间部分）
start_date = normalized_today - timedelta(days=1000)  # 120 天前的日期[1,6](@ref)
# start_date = start_date.strftime("%Y-%m-%d")

# filtered_df = df[df['Age'] > 28]

# filtered_df = df[(df['date'] >= start_date) & (df['date'] <= today)]
all_df = all_df[(all_df['date'] >= start_date)]
# TypeError: '>=' not supported between instances of 'str' and 'datetime.datetime'

print(u' df 按时间过滤 ', timer() - start)

# 在 Pandas 中将某列（如 date）设置为索引后，该列名会从列名列表（columns）中移除，转而作为索引（index）存在。这是 Pandas 的默认设计逻辑
all_df.set_index(['date'], inplace=True)
all_df.index.name=''

print(u' df 设置index ', timer() - start)

unique_column = all_df['symbol'].drop_duplicates()
unique_values = unique_column.values

loop_start = timer()

print(u' df 取得排重后的股票代码，准备进入循环 ', loop_start - start)

for item in unique_values:
    a_end = timer()

    # if item in ['920167.BJ']:
    df = all_df[all_df['symbol'].isin([item])].copy()

    daily_buy_signals = MAIRU(df)

    if daily_buy_signals.empty or daily_buy_signals.size == 0:
        pass
    else:
        daily_show_symbol = False
        weekly_show_symbol = False

        for index, row in daily_buy_signals.iterrows():
            if abs(normalized_today - index) < timedelta(days=100):
                print(f"信号日K | "
                      f"日期: {index.strftime('%Y-%m-%d')} | "
                      f"代码: {row['symbol']} | "
                      f"开: {row['open']:.2f} | "
                      f"高: {row['high']:.2f} | "
                      f"低: {row['low']:.2f} | "
                      f"收: {row['close']:.2f} | "
                      f"量: {row['volume']:,.0f}股 | "
                      f"额: {row['amount']:,.0f}元")
                daily_show_symbol = True

        if daily_show_symbol:
            weekly_df = resample_weekly(df)

            weekly_buy_signals = MAIRU(weekly_df)
            for index, row in weekly_buy_signals.iterrows():
                if abs(normalized_today - index) < timedelta(days=100):
                    print(f"信号周K | "
                          f"日期: {index.strftime('%Y-%m-%d')} | "
                          f"代码: {row['symbol']} | "
                          f"开: {row['open']:.2f} | "
                          f"高: {row['high']:.2f} | "
                          f"低: {row['low']:.2f} | "
                          f"收: {row['close']:.2f} | "
                          f"量: {row['volume']:,.0f}股 | "
                          f"额: {row['amount']:,.0f}元")
                    weekly_show_symbol = True

        if daily_show_symbol and weekly_show_symbol:
            print(f"---------------代码: {item} ----------------")

    loop_start = a_end

print(u' 程序执行完毕 ', timer() - start)


#
"""

请将以下通达信公式的计算结果使用matplotlib绘制出图形
L1:=COST(0.01);                             计算股票成本分布的最低1%分位点（支撑位）      
L2:=COST(99.99);                            计算股票成本分布的最高99.99%分位点（压力位）
L3:=(C-L1)/(L2-L1)*100;                     动态价格位置指标：(当前收盘价 - 最低成本) / (最高成本 - 最低成本) * 100，反映当前价在成本区间中的相对位置
                                            基于L3的平滑计算：
K:SMA(L3,3,1),COLORWHITE;                   实际为EMA（指数移动平均）​，权重因子=1（非简单平均）
D:SMA(K,3,1),COLORYELLOW;                   对K值再次EMA平滑
J:3*K-2*D,COLORFF00FF;                      震荡加速线，增强灵敏度
MAIRU:=CROSS(J,K) AND J<80;                 当J上穿K且J < 80时标记买入信号（DRAWICON绘制箭头
DRAWICON(CROSS(J,K) AND J<80,J,1);



L1:=COST(0.01);                              
L2:=COST(99.99);                            
L3:=(C-L1)/(L2-L1)*100;                     
                                           
K:SMA(L3,3,1),COLORWHITE;                   
D:SMA(K,3,1),COLORYELLOW;                  
J:3*K-2*D,COLORFF00FF;                      
MAIRU:=CROSS(J,K) AND J<80;                 
DRAWICON(CROSS(J,K) AND J<80,J,1);
"""