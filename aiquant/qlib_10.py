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

    from qlib.contrib.model.gbdt import LGBModel
    from qlib.contrib.data.handler import Alpha158
    from qlib.utils import init_instance_by_config
    import pandas as pd

    # 使用配置字典方式创建处理器（新版推荐）
    handler_config = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "instruments": "csi300",
            "start_time": "2010-01-01",
            "end_time": "2020-12-31",
            "fit_start_time": "2010-01-01",
            "fit_end_time": "2015-12-31",
            "infer_processors": [
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}}
            ],
            "learn_processors": [
                {"class": "DropnaLabel"},
                {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}}
            ]
        }
    }

    # 创建处理器实例
    handler = init_instance_by_config(handler_config)

    # 执行数据处理
    handler.fit_process_data()

    # 获取数据
    features = handler.fetch(col_set='feature')
    labels = handler.fetch(col_set='label')

    print('特征数据形状:', features.shape)
    print('标签数据形状:', labels.shape)