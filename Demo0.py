#股市行情数据获取和作图 -2
from  Ashare import *          #股票数据库    https://github.com/mpquant/Ashare
from  MyTT import *            #myTT麦语言工具函数指标库  https://github.com/mpquant/MyTT
import glob
import os
import pyarrow.parquet as pq
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

# filtered_df = df[df['Age'] > 28]
df = all_df[all_df['symbol'].isin(['001965.SZ'])]

#-------有数据了，下面开始正题 -------------
CLOSE=df.close.values;         OPEN=df.open.values           #基础数据定义，只要传入的是序列都可以  Close=df.close.values 
HIGH=df.high.values;           LOW=df.low.values             #例如  CLOSE=list(df.close) 都是一样

MA5=MA(CLOSE,5)                                #获取5日均线序列
MA10=MA(CLOSE,10)                              #获取10日均线序列
up,mid,lower=BOLL(CLOSE)                       #获取布林带指标数据

#-------------------------作图显示-----------------------------------------------------------------
import matplotlib.pyplot as plt ;  from matplotlib.ticker import MultipleLocator
plt.figure(figsize=(15,8))  
plt.plot(CLOSE,label='SHZS');    plt.plot(up,label='UP');           #画图显示 
plt.plot(mid,label='MID');       plt.plot(lower,label='LOW');
plt.plot(MA10,label='MA10',linewidth=0.5,alpha=0.7);
plt.legend();         plt.grid(linewidth=0.5,alpha=0.7);    plt.gcf().autofmt_xdate(rotation=45);
plt.gca().xaxis.set_major_locator(MultipleLocator(len(CLOSE)/30))    #日期最多显示30个
plt.title('SH-INDEX   &   BOLL SHOW',fontsize=20);   plt.show()
