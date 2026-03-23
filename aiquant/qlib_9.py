import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场

# 特征工程实践（执行成功）

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
    from qlib.data.filter import NameDFilter
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.contrib.data.handler import Alpha158

    # 使用内置的Alpha158特征集 (新版API参数名称有变化)
    handler = Alpha158(
        instruments='csi300',  # 沪深300成分股
        start_time='2010-01-01',  # 开始时间
        end_time='2020-12-31',  # 结束时间
        fit_start_time='2010-01-01',  # 拟合处理器的时间范围开始
        fit_end_time='2015-12-31',  # 拟合处理器的时间范围结束
        # 处理器配置 (新版推荐显式配置)
        infer_processors=[
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}}
        ],
        learn_processors=[
            {"class": "DropnaLabel"},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}}
        ]
    )

    # 执行数据处理流程 (新版推荐先调用fit_process_data)
    handler.fit_process_data()

    # 获取特征数据
    features = handler.fetch(col_set='feature')
    # 获取标签数据
    labels = handler.fetch(col_set='label')

    print('特征数据形状:', features.shape)
    print('标签数据形状:', labels.shape)

    # 额外信息：获取特征名称和示例数据
    feature_names = handler.get_cols("feature")
    print(f'特征数量: {len(feature_names)}')
    print('前10个特征名称:', feature_names[:10])

    # 查看数据示例
    print("\n特征数据示例:")
    print(features.head())
    print("\n标签数据示例:")
    print(labels.head())