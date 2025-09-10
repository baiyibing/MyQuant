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

    # from qlib.data import D
    # from qlib.constant import REG_CN
    #
    # # 初始化Qlib数据环境
    # qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region=REG_CN)


    # 数据准备与预处理
    # 首先需要准备CSI300成分股的历史数据，包括价格、成交量、财务指标等。Qlib提供了标准化的数据接口：

    # 获取CSI300成分股数据
    csi300_instruments = D.instruments("csi300")
    price_data = D.features(csi300_instruments, ["$close", "$open", "$high", "$low", "$volume"])


    # 特征工程与Alpha因子
    # Qlib内置了丰富的Alpha因子库，如Alpha158和Alpha360，包含158个和360个技术因子：
    from qlib.contrib.data.handler import Alpha158
    from qlib.contrib.data.handler import Alpha360

    # 机器学习模型训练
    # 使用LightGBM模型对CSI300成分股进行收益预测：
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.contrib.data.handler import Alpha158
    from qlib.data.dataset import DatasetH
    from qlib.contrib.strategy import TopkDropoutStrategy
    from qlib.contrib.evaluate import backtest_daily, risk_analysis

    # 初始化 Qlib
    # qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")

    # 配置数据处理配置Alpha158因子处理器
    data_handler_config = {
        "start_time": "2008-01-01",
        "end_time": "2020-08-01",
        "fit_start_time": "2008-01-01",
        "fit_end_time": "2014-12-31",
        "instruments": "csi300",
    }
    handler = Alpha158(**data_handler_config)
    dataset = DatasetH(handler=handler, segments={
        "train": ("2008-01-01", "2014-12-31"),
        "valid": ("2015-01-01", "2016-12-31"),
        "test": ("2017-01-01", "2020-08-01"),
    })

    # 构建 LightGBM 模型
    model = LGBModel(loss="mse", learning_rate=0.05, num_leaves=64)
    model.fit(dataset)
    pred_score = model.predict(dataset)

    # 策略与回测
    strategy_obj = TopkDropoutStrategy(topk=50, n_drop=5, signal=pred_score)
    report, positions = backtest_daily(
        start_time="2017-01-01", end_time="2020-08-01", strategy=strategy_obj
    )
    analysis = risk_analysis(report["return"] - report["bench"])
    print(analysis)
