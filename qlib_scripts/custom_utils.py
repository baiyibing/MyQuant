from pprint import pprint
import pandas as pd  # 导入pandas库进行数据处理

def generate_position_report(positions_dict, output_file='position_analysis.txt'):
    """生成完整的持仓分析报告"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("QLib持仓分析报告\n")
        f.write("=" * 50 + "\n\n")

        # 总体统计
        f.write("1. 总体统计信息\n")
        f.write(f"回测期间: {len(positions_dict)} 个交易日\n")
        f.write(f"日期范围: {min(positions_dict.keys())} 至 {max(positions_dict.keys())}\n\n")

        # 按日期详细分析
        f.write("2. 各交易日持仓概览\n")
        for date_str in sorted(positions_dict.keys()):
            position_data = positions_dict[date_str]
            f.write(f"\n日期: {date_str}\n")

            if isinstance(position_data, pd.DataFrame):
                f.write(f"  持仓标的数: {len(position_data)}\n")
                if 'market_value' in position_data.columns:
                    total_value = position_data['market_value'].sum()
                    f.write(f"  总市值: {total_value:.2f}\n")
                if 'amount' in position_data.columns:
                    total_amount = position_data['amount'].sum()
                    f.write(f"  总持仓量: {total_amount}\n")

            f.write("-" * 30 + "\n")

    print(f"分析报告已保存至: {output_file}")

def analyze_position_by_date(positions_dict, target_date=None):
    if target_date is None:
        target_date = list(positions_dict.keys())[0]

    if target_date in positions_dict:
        position_data = positions_dict[target_date]

        print(f"=== {target_date} 持仓分析 ===")

        if isinstance(position_data, pd.DataFrame):
            # 如果是DataFrame，进行详细分析
            print(f"持仓标的数量: {len(position_data)}")
            print(f"总市值: {position_data.get('market_value', pd.Series([0])).sum():.2f}")
            print(f"持仓明细:")
            print(position_data.to_string())
        else:
            # 如果是字典或其他结构
            print("持仓内容:")
            pprint(position_data)

    return positions_dict.get(target_date)

def pprint_position_report(positions_dict):
    if positions_dict:
        # 查看字典基本信息
        print("字典类型:", type(positions_dict))
        print("字典键:", list(positions_dict.keys()))
        print("字典大小:", len(positions_dict))
        # 基本美化输出
        pprint(positions_dict)

        # 获取第一个日期键和对应的仓位信息
        sample_date = list(positions_dict.keys())[0]
        sample_data = positions_dict[sample_date]

        print(f"样本日期: {sample_date}")
        print(f"该日期仓位数据类型: {type(sample_data)}")

        if isinstance(sample_data, pd.DataFrame):
            print("仓位数据结构: DataFrame")
            print("DataFrame形状:", sample_data.shape)
            print("列名:", sample_data.columns.tolist())
            print("\n前5行数据:")
            print(sample_data.head())
        else:
            print("仓位数据内容:")
            pprint(sample_data)

def pprint_position_report(positions_dict):
    if positions_dict:
        # 查看字典基本信息
        print("字典类型:", type(positions_dict))
        print("字典键:", list(positions_dict.keys()))
        print("字典大小:", len(positions_dict))
        # 基本美化输出
        pprint(positions_dict)

        # 获取第一个日期键和对应的仓位信息
        sample_date = list(positions_dict.keys())[0]
        sample_data = positions_dict[sample_date]

        print(f"样本日期: {sample_date}")
        print(f"该日期仓位数据类型: {type(sample_data)}")

        if isinstance(sample_data, pd.DataFrame):
            print("仓位数据结构: DataFrame")
            print("DataFrame形状:", sample_data.shape)
            print("列名:", sample_data.columns.tolist())
            print("\n前5行数据:")
            print(sample_data.head())
        else:
            print("仓位数据内容:")
            pprint(sample_data)