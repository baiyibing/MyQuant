import pandas as pd
import re
from loguru import logger
from datetime import datetime
import numpy as np


def parse_log_to_dataframe(log_file_path):
    # 定义正则表达式模式（跳过前导信息，捕获JSON部分）
    pattern = r"^(.+?)\|.+?\|.+? - ({.*})$"
    data_records = []

    # 逐行读取日志文件
    with open(log_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = re.match(pattern, line.strip())
            if match:
                try:
                    # 提取JSON字符串并解析
                    json_str = match.group(2)
                    # 处理特殊类型转换
                    data = eval(json_str.replace("Timestamp", "datetime.fromisoformat")
                                .replace("np.float64", "float"))

                    # 转换时间戳格式
                    data['start_time'] = datetime.fromisoformat(
                        data['start_time'].replace("'", "")
                    )

                    data_records.append(data)
                except Exception as e:
                    logger.error(f"解析失败: {line.strip()} - 错误: {str(e)}")

    # 创建DataFrame
    df = pd.DataFrame(data_records)

    # 数据类型优化
    df['trade_val'] = df['trade_val'].astype(float)
    df['deal_amount'] = df['deal_amount'].astype(int)

    return df


# 使用示例
if __name__ == "__main__":
    log_path = "orders.log"  # 替换为实际日志路径
    df = parse_log_to_dataframe(log_path)

    # 显示数据预览
    print(df.head())

    # 保存到CSV（可选）
    df.to_csv("trading_data.csv", index=False)