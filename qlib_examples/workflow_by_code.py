#  Copyright (c) Microsoft Corporation.
#  Licensed under the MIT License.
"""
Qlib provides two kinds of interfaces.
(1) Users could define the Quant research workflow by a simple configuration.
(2) Qlib is designed in a modularized way and supports creating research workflow by code just like building blocks.

The interface of (1) is `qrun XXX.yaml`.  The interface of (2) is script like this, which nearly does the same thing as `qrun XXX.yaml`
"""
import qlib
from qlib.constant import REG_CN
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.workflow.record_temp import SignalRecord, PortAnaRecord, SigAnaRecord
from qlib.tests.data import GetData
from qlib.tests.config import CSI300_BENCH, CSI300_GBDT_TASK


if __name__ == "__main__":
    # use default data 初始化数据提供路径和区域（中国市场）
    provider_uri = "~/.qlib/qlib_data/cn_data"  # target_dir
    # WARNING - Data already exists # 数据已存在，跳过下载
    GetData().qlib_data(target_dir=provider_uri, region=REG_CN, exists_skip=True)
    # INFO - qlib successfully initialized # Qlib初始化成功
    qlib.init(provider_uri=provider_uri, region=REG_CN)

    # ModuleNotFoundError. CatBoost/XGBoost/PyTorch skipped # 缺少相关库
    # - **原因**：你的环境没有安装`catboost`, `xgboost`, `pytorch`
    # - **影响**：代码会跳过这些模型，**但示例中实际使用的是LightGBM**（后续训练输出可见`LGBModel`）
    # - **建议**：如果不需要这些模型可忽略，需要时按之前指导安装

    # 通过配置初始化模型和数据集
    model = init_instance_by_config(CSI300_GBDT_TASK["model"])
    # 通过配置初始化模型和数据集
    dataset = init_instance_by_config(CSI300_GBDT_TASK["dataset"])

    # 定义回测配置（执行器、策略、回测参数）
    port_analysis_config = {
        # 执行器
        "executor": {
            "class": "SimulatorExecutor",
            "module_path": "qlib.backtest.executor",
            "kwargs": {
                "time_per_step": "day",
                "generate_portfolio_metrics": True,
            },
        },
        # 策略
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy.signal_strategy",
            "kwargs": {
                "signal": (model, dataset),
                "topk": 50,
                "n_drop": 5,
            },
        },
        # 回测参数
        "backtest": {
            "start_time": "2017-01-01",
            "end_time": "2020-08-01",
            "account": 100000000,
            "benchmark": CSI300_BENCH,
            "exchange_kwargs": {
                "freq": "day",
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            },
        },
    }

    # NOTE: This line is optional
    # It demonstrates that the dataset can be used standalone.
    example_df = dataset.prepare("train")
    print(example_df.head())

    # start exp 开启实验记录上下文
    with R.start(experiment_name="workflow"):
        R.log_params(**flatten_dict(CSI300_GBDT_TASK))
        model.fit(dataset)
        R.save_objects(**{"params.pkl": model})

        # prediction 生成模型预测信号记录
        recorder = R.get_recorder()
        sr = SignalRecord(model, dataset, recorder)
        sr.generate()

        # Signal Analysis   信号分析，评估预测信号质量
        sar = SigAnaRecord(recorder)
        sar.generate()

        # 回测报告 组合分析，执行回测并生成绩效报告
        # backtest. If users want to use backtest based on their own prediction,
        # please refer to https://qlib.readthedocs.io/en/latest/component/recorder.html#record-template.
        par = PortAnaRecord(recorder, port_analysis_config, "day")
        par.generate()
