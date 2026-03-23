import pandas as pd

# 显示所有行
pd.set_option('display.max_rows', None)
# 显示所有列
pd.set_option('display.max_columns', None)
# 设置列宽，确保长文本完整显示
pd.set_option('display.max_colwidth', None)
# 设置显示宽度，防止自动换行
pd.set_option('display.width', None)

# 指定文件路径，请将'your_file.txt'替换为实际文件路径
# file_path = 'shiyingli.txt'
# df = pd.read_csv(file_path, delim_whitespace=True, header=None)

file_path = 'st.csv'
df = pd.read_csv(file_path, header=None)
# 使用pandas读取空格分隔的txt文件
# 关键参数说明：
# - delim_whitespace=True：指定使用空格（包括连续空格或制表符）作为分隔符[15,20](@ref)
# - header=None：表示文件不包含列标题行，第一行即为数据[1,4](@ref)
# 若文件有列名标题行，可省略header参数或设置header=0


# 为三列数据指定列名（可选，便于后续操作）
# 如果文件已有列名标题行，则无需此步
df.columns = ['code', 'syl', 'st']

# 打印DataFrame的前几行以确认读取结果
print("数据预览（前5行）：")
print(df.head())

# 显示DataFrame的基本信息（行数、列数等）
print("\n数据形状（行数, 列数）：")
print(df.shape)

filtered_df = df[df['st'] > 0]

# 打印DataFrame的前几行以确认读取结果
print("数据预览（前5行）：")
print(filtered_df)

# 显示DataFrame的基本信息（行数、列数等）
print("\n数据形状（行数, 列数）：")
print(filtered_df.shape)

name_list = filtered_df['code'].to_list()
print(name_list)  # 输出: ['Alice', 'Bob', 'Charlie']

