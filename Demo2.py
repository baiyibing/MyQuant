#股市行情数据获取和作图 -2
from  Ashare import *          #股票数据库    https://github.com/mpquant/Ashare
from  MyTT import *            #myTT麦语言工具函数指标库  https://github.com/mpquant/MyTT
import glob
import os
import pyarrow.parquet as pq
from datetime import datetime, timedelta

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
all_df = table.to_pandas()          # 转为 Pandas DataFrame（可选）

now = datetime.today()
normalized_today = now.replace(hour=0, minute=0, second=0, microsecond=0) # 当前日期（去除时间部分）
start_date = normalized_today - timedelta(days=120)  # 120 天前的日期[1,6](@ref)

start_date = start_date.strftime("%Y-%m-%d")

# filtered_df = df[df['Age'] > 28]
df = all_df[all_df['symbol'].isin(['001965.SZ'])]
# filtered_df = df[(df['date'] >= start_date) & (df['date'] <= today)]
df = df[(df['date'] >= start_date)]
# TypeError: '>=' not supported between instances of 'str' and 'datetime.datetime'


# 基础数据定义，只要传入的是序列都可以
CLOSE = df.close.values
OPEN = df.open.values
HIGH = df.high.values
LOW = df.low.values

MA5 = MA(CLOSE, 5)  # 获取 5 日均线序列
MA10 = MA(CLOSE, 10)  # 获取 10 日均线序列

print('BTC5 日均线', MA5[-1])  # 只取最后一个数
print('BTC10 日均线', RET(MA10))  # RET(MA10) == MA10[-1]
print('今天 5 日线是否上穿 10 日线', RET(CROSS(MA5, MA10)))
print('最近 5 天收盘价全都大于 10 日线吗？', EVERY(CLOSE > MA10, 5))
