from xtquant import xtdata
import time


def get_st_stocks():
    """
    获取ST股票清单
    Returns:
        list: 包含ST股票代码和名称的列表，格式为[(code, name)]
    """

    # 获取沪深A股所有股票代码[2,5](@ref)
    all_stocks = xtdata.get_stock_list_in_sector("沪深A股")
    print(f"共获取到 {len(all_stocks)} 只沪深A股股票")

    st_stocks = []

    # 遍历每只股票，查询ST信息[1](@ref)
    for i, stock_code in enumerate(all_stocks):
        try:
            # 获取股票详细信息[1](@ref)
            stock_detail = xtdata.get_instrument_detail(stock_code)

            if stock_detail is not None:
                # 检查是否为ST股票（根据返回的字典中的ST标记字段）
                # 实际字段名可能需要根据返回数据结构调整[1](@ref)
                is_st = False

                # 方法1：检查字典中是否存在ST相关字段
                if 'st_flag' in stock_detail and stock_detail['st_flag']:
                    is_st = True
                elif 'is_st' in stock_detail and stock_detail['is_st']:
                    is_st = True
                elif 'ST' in str(stock_detail).upper():
                    # 通用方法：在返回信息中搜索ST关键词
                    is_st = True

                if is_st:
                    stock_name = stock_detail.get('name', '未知名称')
                    st_stocks.append((stock_code, stock_name))
                    print(f"发现ST股票: {stock_code} {stock_name}")

            # 添加延迟，避免请求过于频繁
            if i % 100 == 0:
                time.sleep(0.1)

        except Exception as e:
            print(f"处理股票 {stock_code} 时出错: {str(e)}")
            continue

    return st_stocks


def get_st_stocks_alternative_method():
    """
    替代方法：通过股票列表接口筛选ST股票
    适用于get_instrument_detail接口不可用的情况
    """
    try:
        # 使用get_instrument_list接口获取股票列表[2](@ref)
        instrument_list = xtdata.get_instrument_list(market='stock', type=['STOCK_A'])

        st_stocks = []
        for item in instrument_list:
            # 检查股票名称中是否包含ST标识[1](@ref)
            stock_name = item.get('name', '')
            stock_code = item.get('code', '')

            if 'ST' in stock_name or '*ST' in stock_name or 'PT' in stock_name:
                st_stocks.append((stock_code, stock_name))
                print(f"发现ST股票: {stock_code} {stock_name}")

        return st_stocks

    except Exception as e:
        print(f"使用替代方法时出错: {str(e)}")
        return []


def main():
    """主函数"""
    print("开始获取ST股票清单...")

    # 方法1：通过股票详情接口获取
    print("=== 方法1：通过股票详情查询 ===")
    st_stocks_method1 = get_st_stocks()

    # 方法2：通过股票列表接口获取（备用方法）
    print("\n=== 方法2：通过股票列表筛选 ===")
    st_stocks_method2 = get_st_stocks_alternative_method()

    # 合并结果（去重）
    all_st_stocks = list(set(st_stocks_method1 + st_stocks_method2))

    # 输出最终结果
    print(f"\n=== ST股票清单获取完成 ===")
    print(f"共找到 {len(all_st_stocks)} 只ST股票:")

    for i, (code, name) in enumerate(all_st_stocks, 1):
        print(f"{i:2d}. {code} - {name}")

    # 保存到文件
    with open("st_stocks_list.txt", "w", encoding="utf-8") as f:
        f.write("ST股票清单\n")
        f.write("生成时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        f.write("=" * 50 + "\n")
        for code, name in all_st_stocks:
            f.write(f"{code} {name}\n")

    print(f"\n结果已保存到 st_stocks_list.txt")


if __name__ == "__main__":
    main()