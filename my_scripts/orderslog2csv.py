import re
import pandas as pd
import ast
from io import StringIO

# 显示所有行
pd.set_option('display.max_rows', None)
# 显示所有列
pd.set_option('display.max_columns', None)
# 设置列宽，确保长文本完整显示
pd.set_option('display.max_colwidth', None)
# 设置显示宽度，防止自动换行
pd.set_option('display.width', None)
# 设置全局浮点数格式（保留两位小数）
pd.set_option('display.float_format', '{:.6f}'.format)

# 示例日志内容（模拟文件）
log_content = """2025-11-11 15:11:50.535 | INFO     | qlib.backtest.position:update_order:398 - {'stock_id': 'SH600028', 'start_time': Timestamp('2025-01-03 00:00:00'), 'direction': 'B', 'deal_amount': np.float64(115500.0), 'trade_val': np.float64(1899108.6530685425), 'trade_price': np.float64(16.4424991607666), 'cost': np.float64(949.5543265342712)}"""

# 模拟文件读取
pattern = r' - (\{.*\})$'
dict_list = []
with open('orders.log', 'r') as f:
    for line in f:
        match = re.search(pattern, line.strip())
        if match:
            dict_str = match.group(1)
            # 预处理非标准类型
            dict_str = re.sub(r"Timestamp\('([^']+)'\)", r"'\1'", dict_str)  # Timestamp转字符串
            dict_str = re.sub(r"np\.float64\((\d+\.?\d*)\)", r"\1", dict_str)  # np.float64转浮点
            try:
                data = ast.literal_eval(dict_str)  # 安全转换字典
                dict_list.append(data)
            except SyntaxError:
                continue

df = pd.DataFrame(dict_list)
if not df.empty and 'start_time' in df.columns:
    df['start_time'] = pd.to_datetime(df['start_time'])
print(df)

# 1. 去除重复记录（基于所有列判断完全重复的行）
df_cleaned = df.drop_duplicates()
print("去重后数据形状:", df_cleaned.shape)

# 2. 将时间列转换为datetime类型并按时间排序
df_cleaned['start_time'] = pd.to_datetime(df_cleaned['start_time'])
df_sorted = df_cleaned.sort_values('start_time')
print("去除重复记录按时间排序后:")
print(df_sorted)

# 3. 计算盈利：定义盈利 = 卖出交易总额（direction='S'） - 买入交易总额（direction='B'）
# 为每个交易记录分配现金流：卖出为正，买入为负
df_sorted['cash_flow'] = df_sorted.apply(
    lambda row: row['trade_val'] if row['direction'] == 'S' else -row['trade_val'],
    axis=1
)

# 按stock_id分组，求和计算净盈利
profit_df = df_sorted.groupby('stock_id').agg(
    total_profit=('cash_flow', 'sum'),  # 盈利总和
    trade_count=('cash_flow', 'count')   # 可选：记录交易次数
).reset_index()

# print("\n每个stock_id的盈利情况:")
# print(profit_df)

# 按盈利降序排序，并重置索引
profit_df_sorted = profit_df.sort_values(by='total_profit', ascending=False).reset_index(drop=True)
print("\n按盈利排序后的结果:")
print(profit_df_sorted)