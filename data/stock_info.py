import akshare as ak
import pandas as pd


def get_all_stock_list():
    """
    获取沪深京三市所有A股的股票代码与名称列表
    """
    try:
        # 使用 stock_info_a_code_name() 获取所有沪深京A股列表
        all_stock_df = ak.stock_info_a_code_name()
        print("沪深京三市所有A股股票列表获取成功！")
        print(f"总共获取到 {len(all_stock_df)} 只股票")
        return all_stock_df
    except Exception as e:
        print(f"获取沪深京股票列表时出错：{e}")
        return None


def get_bj_stock_list():
    """
    专门获取北京证券交易所（北交所）的股票代码与名称列表
    """
    try:
        # 使用 stock_info_bj_name_code() 获取北交所股票列表
        bj_stock_df = ak.stock_info_bj_name_code()
        print("北交所股票列表获取成功！")
        print(f"总共获取到 {len(bj_stock_df)} 只北交所股票")
        return bj_stock_df
    except Exception as e:
        print(f"获取北交所股票列表时出错：{e}")
        return None


def main():
    """
    主函数：获取并展示股票列表数据
    """
    print("开始获取股票列表数据...")

    # 获取所有沪深京A股列表
    # all_stocks = get_all_stock_list()
    # if all_stocks is not None:
    #     print("\n所有沪深京A股列表前10行预览：")
    #     print(all_stocks.head(10))
    #
    #     # 保存到CSV文件
    #     all_stocks.to_csv("all_a_shares.csv", index=False, encoding='utf-8-sig')
    #     print("\n所有沪深京A股列表已保存到 'all_a_shares.csv'")
    #
    # print("\n" + "=" * 50 + "\n")

    # 专门获取北交所股票列表
    bj_stocks = get_bj_stock_list()

    bj_stocks['证券代码'] = bj_stocks['证券代码'] + '.BJ'
    bj_stocks = bj_stocks[['证券代码', '证券简称']]
    # bj_stocks = bj_stocks.iloc[1:]
    if bj_stocks is not None:
        print("\n北交所股票列表前10行预览：")
        print(bj_stocks.head(10))

        # 保存到CSV文件
        bj_stocks.to_csv("bj_stocks.csv", header=False, index=False, encoding='utf-8-sig')
        print("\n北交所股票列表已保存到 'bj_stocks.csv'")

    print("\n程序执行完毕！")


if __name__ == "__main__":
    main()