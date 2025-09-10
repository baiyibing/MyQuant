# https://www.wuzao.com/qlib/tutorial/introduction
import multiprocessing
import qlib
import logging
from qlib.data import D
from qlib.data.filter import NameDFilter
from qlib.constant import REG_CN    # 中国市场

# python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn
# 下载会报错，元宝建议从https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz下载解压到~/.qlib/qlib_data/cn_data

# qlib.init(provider_uri='~/.qlib/qlib_data/cn_data', region=REG_CN)    ~ 表示当前用户的“home”目录

# qlib.init(provider_uri='./.qlib/qlib_data/cn_data', region=REG_CN)

# 初始化完成后，可以通过以下方式验证是否成功：如果能够成功输出交易日历和股票列表，说明初始化成功。

# ... 导入其他需要的模块

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

    # 1. 数据处理器配置 (使用QLib的标准Handler)
    data_handler_config = {
        "start_time": "2010-01-01",
        "end_time": "2020-12-31",
        "fit_start_time": "2010-01-01",
        "fit_end_time": "2015-12-31",
        "instruments": "csi300",  # 沪深300成分股
    }

    handler = Alpha158(**data_handler_config)

    # 2. 准备数据
    df = handler.fetch()
    features = df["feature"]  # 特征数据
    labels = df["label"]  # 标签数据

    # 3. 模型配置与训练
    model_config = {
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse",
            "colsample_bytree": 0.8879,
            "learning_rate": 0.0421,
            "subsample": 0.8789,
            "lambda_l1": 205.6999,
            "lambda_l2": 580.9768,
            "max_depth": 8,
            "num_leaves": 210,
            "num_threads": 20,
        }
    }

    model = init_instance_by_config(model_config)
    model.fit(features, labels)

    # 4. 特征重要性分析
    feature_importance = model.feature_importance()
    importance_series = pd.Series(feature_importance, index=features.columns)
    importance_series = importance_series.sort_values(ascending=False)

    # 5. 选择重要性最高的50个特征
    selected_features = importance_series.head(50).index.tolist()
    features_selected = features[selected_features]

    print(f"Selected {len(selected_features)} features:")
    print(selected_features)