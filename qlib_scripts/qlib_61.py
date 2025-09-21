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


# 数据诊断脚本
def diagnose_data_issues(dataset, handler):
    """全面诊断数据问题"""
    print("=== 数据诊断报告 ===")

    # 1. 检查数据集结构
    print("\n1. 数据集结构检查:")
    for segment in ["train", "valid", "test"]:
        try:
            data = dataset.prepare(segment)
            print(f"{segment}段 - 形状: {data.shape}, 列名: {data.columns.tolist()}")
        except Exception as e:
            print(f"{segment}段 - 错误: {e}")

    # 2. 检查处理器配置
    print("\n2. 处理器配置检查:")
    print(f"处理器类型: {type(handler).__name__}")
    if hasattr(handler, 'infer_processors'):
        print(f"推理处理器: {[type(p).__name__ for p in handler.infer_processors]}")
    if hasattr(handler, 'learn_processors'):
        print(f"学习处理器: {[type(p).__name__ for p in handler.learn_processors]}")

    # 3. 尝试直接获取标签数据
    print("\n3. 直接标签获取尝试:")
    try:
        # 尝试不同的数据键
        for data_key in [DataHandlerLP.DK_R, DataHandlerLP.DK_I, DataHandlerLP.DK_L]:
            try:
                label_data = dataset.prepare("test", col_set="label", data_key=data_key)
                print(f"数据键 {data_key} - 成功获取标签，形状: {label_data.shape}")
                break
            except:
                continue
        else:
            print("所有数据键都无法获取标签")
    except Exception as e:
        print(f"标签获取失败: {e}")

    # 4. 检查特征数据
    print("\n4. 特征数据检查:")
    try:
        feature_data = handler.fetch(col_set="feature")
        print(f"特征数据形状: {feature_data.shape}")
        print(f"特征列示例: {feature_data.columns.tolist()[:5]}")
    except Exception as e:
        print(f"特征获取失败: {e}")




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
    # from qlib.constant import REG_CN
    from qlib.utils import init_instance_by_config, exists_qlib_data, flatten_dict
    from qlib.workflow import R
    from qlib.data.dataset import DatasetH, DataHandlerLP
    from qlib.contrib.data.handler import Alpha158
    from qlib.tests.data import GetData

    # # 初始化Qlib数据环境
    # provider_uri = "./qlib_data/cn_data"
    #
    # # 检查并下载数据（如果不存在）[2,8](@ref)
    # if not exists_qlib_data(provider_uri):
    #     print("下载Qlib数据...")
    #     GetData().qlib_data(target_dir=provider_uri, region=REG_CN, delete_old=True)
    # else:
    #     print("数据已存在，跳过下载")
    #
    # # 初始化Qlib[2,4](@ref)
    # qlib.init(provider_uri=provider_uri, region=REG_CN)
    # print("Qlib初始化成功")


    from qlib.contrib.data.handler import Alpha158

    # 使用内置的Alpha158特征集 (新版API参数名称有变化)
    handler = Alpha158(
        instruments='csi300',  # 沪深300成分股
        start_time='2018-01-01',  # 开始时间
        end_time='2023-12-31',  # 结束时间
        fit_start_time='2018-01-01',  # 拟合处理器的时间范围开始
        fit_end_time='2020-12-31',  # 拟合处理器的时间范围结束
        # 处理器配置 (新版推荐显式配置)
        learn_processors=[
            {"class": "DropnaLabel", "kwargs": {}},
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "feature"}},
        ],
        infer_processors=[
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "feature"}},
        ],
    )


    # 定义完整任务配置（新版推荐方式）[7,8](@ref)
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
                "handler": handler,
                "segments": {
                    "train": ("2018-01-01", "2020-12-31"),
                    "valid": ("2021-01-01", "2021-12-31"),
                    "test": ("2022-01-01", "2023-01-01"),
                },
            },
        },
    }

    # 初始化模型和数据集[8,9](@ref)
    model = init_instance_by_config(task_config["model"])
    dataset = init_instance_by_config(task_config["dataset"])

    diagnose_data_issues(dataset, handler)

    rid = None

    # 开始实验记录（使用新版工作流API）[8](@ref)
    with R.start(experiment_name="model_training_demo"):
        # 记录所有任务参数（包括模型和数据集配置）
        R.log_params(**flatten_dict(task_config))

        # 训练模型
        model.fit(dataset)

        # 保存训练好的模型
        R.save_objects(trained_model=model)

        # 在测试集上进行预测
        pred = model.predict(dataset)

        # 将预测结果转换为DataFrame以便更好查看
        pred_df = pd.DataFrame(pred, index=dataset.prepare("test").index, columns=["score"])

        print(f"预测结果形状: {pred_df.shape}")
        print("预测结果示例:")
        print(pred_df.head())

        # 保存预测结果
        R.save_objects(predictions=pred_df)

        rid = R.get_recorder().id  # 获取当前实验记录器的ID，用于后续检索

        print("实验完成！记录器ID:", R.get_recorder().id)

    # 可选：特征重要性分析[6](@ref)
    try:
        feature_importance = model.get_feature_importance()
        print("\n特征重要性前10名:")
        print(feature_importance.sort_values(ascending=False).head(10))
    except AttributeError:
        print("\n当前模型不支持直接获取特征重要性")

    # 可选：加载已保存的模型进行后续分析
    print("\n=== 实验总结 ===")
    print(f"模型类型: {type(model).__name__}")
    print(f"训练时间段: 2018-01-01 至 2020-12-31")
    print(f"测试时间段: 2022-01-01 至 2023-01-01")
    print(f"使用的因子: Alpha158 (158个技术因子)")
    print(f"实验已保存，可通过记录器ID访问详细结果")

    from qlib.workflow.record_temp import SignalRecord, PortAnaRecord

    # 定义回测配置 (0.9.7版本新API)
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
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy.signal_strategy",
            "kwargs": {
                "signal": (model, dataset),  # 使用模型和数据集生成信号
                "topk": 50,  # 持有前50只股票
                "n_drop": 5,  # 每日剔除5只表现最差的
            },
        },
        "backtest": {
            "start_time": "2017-01-01",  # 回测开始时间（应根据实际数据调整）
            "end_time": "2020-08-01",  # 回测结束时间（应根据实际数据调整）
            "account": 100000000,  # 初始资金1亿元
            "benchmark": "SH000300",  # 基准指数沪深300
            "exchange_kwargs": {
                "freq": "day",
                "limit_threshold": 0.095,  # 涨跌停阈值
                "deal_price": "close",  # 以收盘价交易
                "open_cost": 0.0005,  # 开仓成本
                "close_cost": 0.0015,  # 平仓成本
                "min_cost": 5,  # 最低手续费
            },
        },
    }

    from qlib.contrib.evaluate import backtest_daily, risk_analysis

    ba_rid = None
    # 开始一个名为"backtest_analysis"的实验工作流，用于组织回测分析过程
    with R.start(experiment_name="backtest_analysis"):
        # 从之前的"train_model"实验中获取记录器，并加载其中保存的已训练模型
        recorder = R.get_recorder(recorder_id=rid, experiment_name="train_model")  # 根据rid获取训练记录器
        model = recorder.load_object("trained_model")  # 从记录器中加载名为"trained_model"的模型对象

        # 获取当前回测实验的记录器及其ID
        recorder = R.get_recorder()
        ba_rid = recorder.id
        print("策略回测开始！",ba_rid)

        # 创建SignalRecord实例用于生成交易信号，并生成信号[6](@ref)
        sr = SignalRecord(model, dataset, recorder)  # 传入模型、数据集和记录器
        sr.generate()  # 在测试集上生成模型的预测信号

        # 创建PortAnaRecord实例用于执行投资组合回测和分析，并生成回测结果[6](@ref)
        par = PortAnaRecord(recorder, port_analysis_config, "day")  # 传入记录器、回测配置和时间频率
        par.generate()  # 执行回测并生成分析报告

    # 运行诊断
    diagnose_data_issues(dataset, handler)

    # 性能评估指标计算 (Qlib 0.9.7版本)
    from qlib.contrib.evaluate import risk_analysis
    from qlib.contrib.evaluate import indicator_analysis
    from qlib.data.dataset import DatasetH

    # 性能评估指标计算
    from qlib.contrib.evaluate import risk_analysis
    from qlib.contrib.report import analysis_model

    # 获取测试集标签
    test_data = dataset.prepare("test", col_set="label", data_key=DataHandlerLP.DK_R)

    # 确保数据对齐
    aligned_label = test_data['label'].reindex(pred_df.index)

    # 基础评估
    basic_metrics = risk_analysis(pred_df, aligned_label)
    extended_metrics = indicator_analysis(pred_df, aligned_label)

    print("基础性能指标:")
    print(basic_metrics)

    print("\n扩展指标:")
    print(extended_metrics)

    # 计算年化指标
    annualized_return = basic_metrics.get('annualized_return', 'N/A')
    sharpe_ratio = basic_metrics.get('sharpe_ratio', 'N/A')
    max_drawdown = basic_metrics.get('max_drawdown', 'N/A')

    print(f"\n关键指标:")
    print(f"年化收益率: {annualized_return:.2%}")
    print(f"夏普比率: {sharpe_ratio:.2f}")
    print(f"最大回撤: {max_drawdown:.2%}")

    # 确保数据对齐 - 修正后的方法
    # 首先检查数据集结构
    print("数据集列名:", dataset.prepare("test").columns.tolist())
    print("数据集形状:", dataset.prepare("test").shape)

    # 获取测试集数据（使用正确的数据键）
    test_data = dataset.prepare("test", col_set=["feature", "label"], data_key=DataHandlerLP.DK_R)

    # 获取预测结果（确保pred_df是正确的DataFrame格式）
    if not isinstance(pred_df, pd.DataFrame):
        pred_df = pd.DataFrame(pred_df, columns=["score"], index=test_data.index)

    # 对齐标签数据
    if hasattr(test_data, 'label'):
        aligned_label = test_data['label']
    else:
        # 尝试其他可能的标签列名
        possible_label_cols = ['label', 'labels', 'target', 'LABEL0']
        for col in possible_label_cols:
            if col in test_data.columns:
                aligned_label = test_data[col]
                print(f"使用标签列: {col}")
                break
        else:
            # 如果找不到标签列，尝试其他方法
            print("警告: 未找到标准标签列，尝试从数据集获取标签...")
            try:
                # 尝试直接从handler获取标签
                aligned_label = handler.fetch(col_set="label")
                aligned_label = aligned_label.reindex(pred_df.index)
            except Exception as e:
                raise ValueError("无法获取标签数据，请检查数据处理器配置") from e

    # 确保标签和预测结果对齐
    aligned_label = aligned_label.reindex(pred_df.index)

    # 检查数据完整性
    print(f"预测结果形状: {pred_df.shape}")
    print(f"标签数据形状: {aligned_label.shape}")
    print(f"缺失值数量 - 预测: {pred_df.isnull().sum().sum()}, 标签: {aligned_label.isnull().sum().sum()}")

    # 移除缺失值
    valid_mask = ~(pred_df.isnull().any(axis=1) | aligned_label.isnull())
    pred_df_clean = pred_df[valid_mask]
    aligned_label_clean = aligned_label[valid_mask]

    print(f"清洗后数据形状: {pred_df_clean.shape}")

    # 基础评估
    if len(pred_df_clean) > 0:
        basic_metrics = risk_analysis(pred_df_clean, aligned_label_clean)
        extended_metrics = indicator_analysis(pred_df_clean, aligned_label_clean)

        print("基础性能指标:")
        print(basic_metrics)

        print("\n扩展指标:")
        print(extended_metrics)

        # 计算年化指标
        annualized_return = basic_metrics.get('annualized_return', 'N/A')
        sharpe_ratio = basic_metrics.get('sharpe_ratio', 'N/A')
        max_drawdown = basic_metrics.get('max_drawdown', 'N/A')

        print(f"\n关键指标:")
        print(f"年化收益率: {annualized_return:.2%}" if annualized_return != 'N/A' else "年化收益率: N/A")
        print(f"夏普比率: {sharpe_ratio:.2f}" if sharpe_ratio != 'N/A' else "夏普比率: N/A")
        print(f"最大回撤: {max_drawdown:.2%}" if max_drawdown != 'N/A' else "最大回撤: N/A")
    else:
        print("错误: 清洗后无有效数据进行评估")




