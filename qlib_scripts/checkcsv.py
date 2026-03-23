import os
import csv
from loguru import logger

def check_csv_for_string(directory, target_string):
    """
    遍历目录中的所有CSV文件，检查是否包含特定字符串。

    参数:
        directory (str): 要遍历的根目录路径
        target_string (str): 要搜索的字符串（例如 "ValueError: could not convert string to float: '1.#INF'"）

    返回:
        list: 包含匹配信息的字典列表，格式为 [{"file": 文件路径, "line_number": 行号, "line_content": 行内容}]
    """
    matches = []  # 存储匹配结果

    # 遍历目录及子目录
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".csv"):
                file_path = os.path.join(root, file)
                try:
                    # 逐行读取CSV文件
                    with open(file_path, 'r', newline='', encoding='utf-8') as csvfile:
                        csv_reader = csv.reader(csvfile)
                        for line_num, row in enumerate(csv_reader, 1):
                            # 将行内容合并为字符串进行检查
                            line_str = ','.join(row)
                            if target_string in line_str:
                                matches.append({
                                    "file": file_path,
                                    "line_number": line_num,
                                    "line_content": line_str
                                })
                except PermissionError:
                    print(f"权限拒绝，无法读取文件: {file_path}")
                except Exception as e:
                    print(f"读取文件 {file_path} 时出错: {str(e)}")

    return matches


# 使用示例
if __name__ == "__main__":
    target_dir = input("请输入要遍历的目录路径: ").strip()  # 例如: "E:\qlibdata"
    search_string = "1.#INF"
    logger.remove(0)
    logger.add("check.log")
    results = check_csv_for_string(target_dir, search_string)
    # logger.info(f"可用信号列: {available_cols}")
    if results:
        logger.info(f"找到 {len(results)} 处匹配:")
        for match in results:
            logger.info(f"文件: {match['file']}, 行号: {match['line_number']}")
            logger.info(f"内容: {match['line_content'][:100]}...")  # 预览前100字符
    else:
        print("未找到匹配的字符串。")