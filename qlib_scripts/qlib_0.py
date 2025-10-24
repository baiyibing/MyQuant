import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场

# 加载特征数据

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    qlib.init(
        # 数据存储路径
        provider_uri='~/.qlib/qlib_data/cn_data',
        # 中国市场
        region=REG_CN,
        # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
        # 配置实验管理器，用于跟踪和管理实验结果
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {
                "uri": "mlruns",
                "default_exp_name": "MyExperiment",
            }
        },
        # 设置日志级别，控制输出信息的详细程度：常用的日志级别有 DEBUG、INFO、WARNING、ERROR，级别从低到高，级别越低输出信息越详细。
        logging_level=logging.INFO
        # redis={
        #     "host": "localhost",  # 若Redis在远程服务器，请填写服务器IP
        #     "port": 6379,
        #     "password": "123456",  # 请替换为你的实际密码
        #     "db": 1
        # }
    )

    from qlib.data import D

    # 定义股票列表和特征
    instruments = ['SH605116']
    fields = [
        '$close',  # 收盘价
        '$volume',  # 成交量
        'Ref($close, 1)',  # 前一日收盘价
        'Mean($close, 5)',  # 5日平均收盘价
        '$high - $low'  # 当日振幅
    ]

    # 加载特征数据
    features = D.features(
        instruments=instruments,
        fields=fields,
        start_time='2025-01-01',
        end_time='2025-01-03',
        freq='day'
    )

    print(f"特征数据形状: {features.shape}")
    print(features.head())

    # # 以 AKShare 为例的示例代码
    # import akshare as ak
    #
    # # 获取后复权数据 - 需注意接口字段可能随版本更新而变化
    # stock_zh_a_hist_df = ak.stock_zh_a_hist(symbol="SH600548", period="daily", start_date="20250102", end_date="20250103",
    #                                         adjust="hfq")
    # print(stock_zh_a_hist_df)



