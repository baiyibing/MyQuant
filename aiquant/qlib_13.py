import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场
from qlib.data.cache import DiskExpressionCache  # 导入磁盘缓存类
# 磁盘缓存（执行成功）
"""
为了提高数据处理效率，QLib 实现了完善的数据缓存机制。缓存机制可以避免重复计算，显著提高数据加载和处理的速度。
"""

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    qlib.init(
        # 数据存储路径
        provider_uri='E:/PycharmProjects/MyQuant/.qlib/qlib_data/cn_data',
        # 中国市场
        region=REG_CN,
        # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
        # expression_cache=DiskExpressionCache,  # 使用磁盘表达式缓存 加上此句报错
        # dataset_cache=DiskDatasetCache,      # 如需数据集缓存也可配置
        # mem_cache_size=10,                  # 内存缓存大小 (GB)
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

    # 定义你要查询的股票池和表达式
    instruments = ["csi300"]  # 例如沪深300成分股
    fields = ["Mean($close, 5) - Mean($close, 10)"]  # 你的特征表达式
    start_time = "2010-01-01"
    end_time = "2020-12-31"
    freq = "day"  # 数据频率

    # 获取数据 - Qlib 会自动处理缓存（如果缓存不存在则计算并保存，存在则读取）
    feature_df = D.features(
        instruments=instruments,
        fields=fields,
        start_time=start_time,
        end_time=end_time,
        freq=freq,
        disk_cache=1  # 使用磁盘缓存 (1: 如果不存在则生成; 2: 强制重新生成并缓存) [1](@ref)
    )

    print(feature_df.head())
