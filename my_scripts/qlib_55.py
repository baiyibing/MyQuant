import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场
from qlib.data.cache import DiskExpressionCache  # 导入磁盘缓存类
from qlib.utils import init_instance_by_config

# 完整特征工程实现示例（执行不成功）
"""
关键改写说明和最佳实践建议：
1.集成化的工作流管理：强烈推荐使用 Qlib 的 R(Recorder) 工作流系统来管理数据处理器等对象。这比直接使用 pickle更加强大和可靠，因为它：
自动处理对象的依赖关系和存储路径。与实验跟踪紧密结合，便于复现和管理不同版本的数据处理器。
提供统一的 API 来保存和加载各种对象（模型、处理器、数据集等）。

2.更完整的处理器配置：在配置中添加了 infer_processors和 learn_processors，这些是 DataHandlerLP的核心组成部分，用于数据预处理和标准化
。这使得缓存的价值更大，因为预处理可能比较耗时。

3.安全的对象序列化：直接使用 Python 的 pickle模块序列化复杂的对象（如 DataHandler）有时可能会遇到问题，特别是当对象包含无法被 pickle 的属性
（如某些计算图、数据库连接、线程锁等）或者 Qlib 内部数据结构发生变化时。通过工作流管理，Qlib 可能会使用更稳定和版本感知的序列化机制。

4.可复现性：通过 recorder.log_params()记录了处理器的配置信息，这对于后期追溯和复现实验至关重要。

5.缓存必要性评估：数据处理器 (DataHandler) 的主要职责是加载数据和应用处理器 (Processors)。
如果您的原始数据没有变化，并且处理器是确定的（例如 ZScoreNorm在 fit_start_time和 fit_end_time内拟合的参数不变），
那么缓存处理器可以节省每次初始化后拟合处理器的时间。如果数据经常更新或处理器配置改变，则需要重新创建和拟合处理器。
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

    # import qlib
    import pandas as pd
    from qlib.data import D
    from qlib.utils import init_instance_by_config, flatten_dict, exists_qlib_data
    from qlib.workflow import R
    from qlib.workflow.record_temp import SignalRecord
    from qlib.contrib.evaluate import risk_analysis
    from qlib.tests.data import GetData
    # from qlib.constant import REG_CN

    # # 初始化Qlib数据环境
    # provider_uri = "~/.qlib/qlib_data/cn_data"
    #
    # # 检查并下载数据（如果不存在）
    # if not exists_qlib_data(provider_uri):
    #     print("下载Qlib数据...")
    #     GetData().qlib_data(target_dir=provider_uri, region=REG_CN, delete_old=True)
    # else:
    #     print("数据已存在，跳过下载")
    #
    # # 初始化Qlib
    # qlib.init(provider_uri=provider_uri, region=REG_CN)
    # print("Qlib初始化成功")

    # 定义数据处理器配置
    data_handler_config = {
        "start_time": "2010-01-01",
        "end_time": "2020-12-31",
        "fit_start_time": "2010-01-01",
        "fit_end_time": "2015-12-31",
        "instruments": "csi300",  # 使用沪深300成分股
    }

    # 定义完整任务配置（新版推荐方式）
    task_config = {
        "model": {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8,
                "learning_rate": 0.05,
                "subsample": 0.8,
                "lambda_l1": 10,
                "lambda_l2": 10,
                "max_depth": 5,
                "num_leaves": 31,
                "num_threads": 10,
                "early_stopping_rounds": 50,  # 添加早停策略
            },
        },
        "dataset": {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": data_handler_config,
                },
                "segments": {
                    "train": ("2010-01-01", "2014-12-31"),
                    "valid": ("2015-01-01", "2015-12-31"),
                    "test": ("2016-01-01", "2020-12-31"),
                },
            },
        },
    }

    # 初始化模型和数据集
    model = init_instance_by_config(task_config["model"])
    dataset = init_instance_by_config(task_config["dataset"])

    # 开始实验（使用新版工作流API）
    with R.start(experiment_name="multi_factor_model"):
        # 记录实验参数
        R.log_params(**flatten_dict(task_config))

        # 训练模型
        model.fit(dataset)

        # 保存训练好的模型
        R.save_objects(trained_model=model)

        # 生成预测信号（新版API）
        recorder = R.get_recorder()
        sr = SignalRecord(model, dataset, recorder)
        sr.generate()

        # 获取预测结果
        pred_df = recorder.load_object("pred.pkl")
        print("预测结果示例:")
        print(pred_df.head(10))

        # 回测配置（新版API方式）
        port_analysis_config = {
            "executor": {
                "class": "SimulatorExecutor",
                "module_path": "qlib.backtest.executor",
                "kwargs": {
                    "time_per_step": "day",
                    "generate_portfolio_metrics": True,
                },
            },
            "strategy": {
                "class": "TopkDropoutStrategy",  # 使用TopK策略
                "module_path": "qlib.contrib.strategy.signal_strategy",
                "kwargs": {
                    "signal": pred_df,  # 使用预测结果作为信号
                    "topk": 50,  # 选择前50只股票
                    "n_drop": 5,  # 每日剔除5只表现最差的
                },
            },
            "backtest": {
                "start_time": "2016-01-01",
                "end_time": "2020-12-31",
                "account": 100000000,  # 初始资金1亿元
                "benchmark": "SH000300",  # 基准为沪深300
                "exchange_kwargs": {
                    "freq": "day",
                    "limit_threshold": 0.095,
                    "deal_price": "close",
                    "open_cost": 0.0005,  # 买入手续费
                    "close_cost": 0.0015,  # 卖出手续费
                    "min_cost": 5,  # 最低手续费
                },
            },
        }

        # 执行回测和分析（新版API）
        from qlib.workflow.record_temp import PortAnaRecord

        par = PortAnaRecord(recorder, port_analysis_config)
        par.generate()

        print("回测分析完成！")

    # 性能评估和结果分析
    print("\n=== 策略性能分析 ===")

    # 加载回测结果
    report_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
    positions_df = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")

    print("回测报告摘要:")
    # print(f"累计收益率: {report_df['cumulative_return'].iloc[-1]:.2%}")
    # print(f"年化收益率: {report_df['annualized_return'].iloc[-1]:.2%}")
    # print(f"夏普比率: {report_df['sharpe_ratio'].iloc[-1]:.2f}")
    # print(f"最大回撤: {report_df['max_drawdown'].iloc[-1]:.2%}")

    # 风险分析
    risk_metrics = risk_analysis(report_df['return'])
    print("\n风险分析指标:")
    # for key, value in risk_metrics.items():
    #     print(f"{key}: {value:.4f}")

    # 保存实验记录
    recorder.save_objects(
        task_config=task_config,
        risk_metrics=risk_metrics
    )

    print(f"\n实验记录已保存，记录器ID: {recorder.id}")


