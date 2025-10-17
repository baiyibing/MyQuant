import multiprocessing
import logging

from timeit import default_timer as timer
from loguru import logger
import pandas as pd  # 导入pandas库进行数据处理
import qlib
from qlib.config import REG_CN
from qlib.contrib.model import LGBModel
from qlib.contrib.report.analysis_position import report_graph
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.data.dataset import DatasetH
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord
from qlib.contrib.report import analysis_model, analysis_position
from qlib.data import D  # 导入数据模块
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    start = timer()

    logger.remove(0)
    logger.add("ht.log")

    qlib.init(
        # 数据存储路径
        provider_uri = "~/.qlib/qlib_data/cn_data",  # target_dir
        # 中国市场
        region=REG_CN,
        # QLib 使用 Redis 进行缓存和锁机制,如果 Redis 连接失败，QLib 会自动降级为不使用缓存，这可能会影响性能但不会导致程序错误。
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
        redis_task_db=1,  # Redis 数据库编号
        custom_ops=[SMA],
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
        # logging_level=logging.DEBUG
        logging_level=logging.INFO
    )

    start_time = "2020-01-01"
    end_time = "2023-12-31"

    # 定义策略相关的市场和分析基准
    market = "csi300"
    benchmark = "SH000300"  # 设置业绩比较基准为沪深300指数代码

    exp_name = "alpha158_cost_kdj_lgb"

    # 定义数据处理器配置，指定数据获取的时间范围、训练集时间区间和投资标的
    data_handler_config = {
        "start_time": start_time,  # 整体数据开始时间
        "end_time": end_time,  # 整体数据结束时间
        "fit_start_time": start_time,  # 特征计算起始时间（通常与start_time一致）
        "fit_end_time": "2020-12-31",  # 特征计算结束时间（训练集截止时间）
        "cost_window": 250,  # 特征计算结束时间（训练集截止时间）
        "infer_processors": [
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}}],  # 特征计算结束时间（训练集截止时间）
        "learn_processors": [{"class": "DropnaLabel"}],  # 特征计算结束时间（训练集截止时间）
        "instruments": market,  # 投资标的，这里使用前面定义的market（csi300）
        "include_alpha158": False,  # 若仅需自定义因子，可设为 False 以加速
    }

    # 定义任务配置字典，包含模型和数据集的详细配置
    task = {
        "model": {  # 模型配置部分
            "class": "LGBModel",  # 使用LightGBM模型,除了 LightGBM，QLib 还支持 XGBoost、CatBoost、MLP 等多种模型
            "module_path": "qlib.contrib.model.gbdt",  # 模型所在的模块路径
            "kwargs": {  # 传递给模型构造函数的参数（LightGBM的超参数）,LGBModel 是对 LightGBM 的封装，它实现了 QLib 的模型接口，能够与其他组件无缝集成
                "loss": "mse",  # 损失函数为均方误差
                "colsample_bytree": 0.8879,  # 构建每棵树时列采样比例
                "learning_rate": 0.0421,  # 学习率
                "subsample": 0.8789,  # 样本采样比例
                "lambda_l1": 205.6999,  # L1正则化系数
                "lambda_l2": 580.9768,  # L2正则化系数
                "max_depth": 8,  # 树的最大深度
                "num_leaves": 210,  # 树的叶子数
                "num_threads": 20,  # 并行线程数
                # "features": ["COST_J"],
            },
        },
        "dataset": {  # 数据集配置部分
            "class": "DatasetH",  # 使用DatasetH数据集类,负责将数据划分为训练集、验证集和测试集，并提供数据加载接口
            "module_path": "qlib.data.dataset",  # 数据集所在的模块路径
            "kwargs": {  # 传递给数据集构造函数的参数
                "handler": {  # 数据处理器配置
                    "class": "Alpha158CostKDJ",  # 使用Alpha158特征集,一个预定义的数据处理器，它实现了 158 个常用的 Alpha 因子
                    "module_path": "custom_handler",  # 数据处理器所在模块路径
                    "kwargs": data_handler_config,  # 使用前面定义的data_handler_config
                },
                "segments": {  # 定义数据集的分段（训练集、验证集、测试集）
                    "train": (start_time, "2020-12-31"),  # 训练集时间范围
                    "valid": ("2021-01-01", "2021-12-31"),  # 验证集时间范围
                    "test": ("2022-01-01", end_time),  # 测试集时间范围
                },
            },
        },
    }

    model = init_instance_by_config(task["model"])  # 根据model配置创建模型实例
    print(u'根据model配置创建模型实例', timer() - start)
    dataset = init_instance_by_config(task["dataset"])  # 根据dataset配置创建数据集实例
    print(u'根据dataset配置创建数据集实例', timer() - start)

    # 定义投资组合分析（回测）的配置
    port_analysis_config = {
        "executor": {  # 回测执行器配置,负责模拟交易执行过程，计算交易成本和投资组合收益。
            "class": "SimulatorExecutor",  # 使用模拟执行器
            "module_path": "qlib.backtest.executor",  # 执行器所在模块路径
            "kwargs": {  # 执行器参数
                "time_per_step": "day",  # 回测的时间步长为一天
                "generate_portfolio_metrics": True,  # 生成投资组合指标
            },
        },
        "strategy": {  # 交易策略配置
            "class": "TopkDropoutStrategy",  # 使用TopK丢弃策略,一个简单但有效的策略，它每天选择模型预测分数最高的 50 只股票，并剔除其中 5 只持仓最久的股票
            "module_path": "qlib.contrib.strategy.signal_strategy",  # 策略所在模块路径
            "kwargs": {  # 策略参数
                "model": model,  # 使用的预测模型
                "dataset": dataset,  # 使用的数据集
                "topk": 50,  # 选择信号最强的50只股票
                "n_drop": 5,  # 每次调仓时丢弃排名最后5只股票
            },
        },
        "backtest": {  # 回测参数配置
            "start_time": "2022-01-01",  # 回测开始时间（与测试集一致）
            "end_time": end_time,  # 回测结束时间（与测试集一致）
            "account": 100000000,  # 初始资金金额（1亿元）
            "benchmark": benchmark,  # 业绩比较基准（沪深300指数）
            "exchange_kwargs": {  # 交易所模拟参数（交易规则）
                "freq": "day",  # 交易频率为日频
                "limit_threshold": 0.095,  # 涨跌幅限制阈值（9.5%）
                "deal_price": "close",  # 交易价格使用收盘价
                "open_cost": 0.0005,  # 开仓（买入）手续费率（万分之五）
                "close_cost": 0.0015,  # 平仓（卖出）手续费率（千分之1.5）
                "min_cost": 5,  # 最低手续费（5元）
            },
        },
    }

    """
    支持两种策略模式：
    模型驱动：用 COST_J 作为特征训练 LGB
    信号驱动：直接用 MAIRU == 1 选股
    """

    r_start = timer()
    rid = None
    with R.start(experiment_name=exp_name):
        R.log_params(**flatten_dict(task))  # 将任务配置参数扁平化后记录到实验中，便于追踪
        model.fit(dataset)  # 在训练集上训练模型，并在验证集上进行验证
        R.save_objects(trained_model=model)  # 将训练好的模型保存到当前实验记录中
        rid = R.get_recorder().id  # 获取当前实验记录器的ID，用于后续检索

    # 打印完成信息
    print("策略回测完成！", rid, timer() - r_start)

    b_start = timer()
    ba_rid = None
    # 开始一个名为"backtest_analysis"的实验工作流，用于组织回测分析过程
    with R.start(experiment_name="backtest_analysis"):
        # 从之前的"train_model"实验中获取记录器，并加载其中保存的已训练模型
        recorder = R.get_recorder(recorder_id=rid, experiment_name=exp_name)  # 根据rid获取训练记录器
        # 获取当前回测实验的记录器及其ID 如果接着上个with R.start() model.fit(dataset) 就直接使用recorder = R.get_recorder()
        # recorder = R.get_recorder()
        ba_rid = recorder.id
        print("策略回测开始！", ba_rid)

        model = recorder.load_object(exp_name)  # 从记录器中加载名为"trained_model"的模型对象

        # 创建SignalRecord实例用于生成交易信号，并生成信号[6](@ref)
        sr = SignalRecord(model, dataset, recorder)  # 传入模型、数据集和记录器
        sr.generate()  # 在测试集上生成模型的预测信号

        # 创建PortAnaRecord实例用于执行投资组合回测和分析，并生成回测结果[6](@ref)
        par = PortAnaRecord(recorder, port_analysis_config, "day")  # 传入记录器、回测配置和时间频率
        par.generate()  # 执行回测并生成分析报告

    # 打印完成信息
    print("策略回测完成！", ba_rid, timer() - b_start)

    # 获取记录器
    # recorder = R.get_recorder(recorder_id=ba_rid, experiment_name="backtest_analysis")
    recorder = R.get_recorder(recorder_id=rid, experiment_name=exp_name)
    pred_df = recorder.load_object("pred.pkl")  # 预测结果
    report_normal_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")  # 普通报告
    positions = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")  # 持仓记录
    analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")  # 分析报告

    figures = analysis_position.report_graph(report_normal_df, show_notebook=False)
    print(
        "展示回测净值可视化结果(不扣费、扣费和基准净值；不扣费净值最大回撤；扣费净值最大回撤；不扣费和扣费超额收益净值；换手率；不扣费超额收益最大回撤；扣费超额收益最大回撤)",
        timer() - start)
    for i, fig in enumerate(figures):
        fig.show()

    figures = analysis_position.risk_analysis_graph(analysis_df, report_normal_df, show_notebook=False)
    print("生成风险分析图表可视化结果(年化收益率\波动率\信息比率\最大回撤)", timer() - start)
    for i, fig in enumerate(figures):
        fig.show()

    label_df = dataset.prepare("test", col_set="label")
    label_df.columns = ['label']
    pred_label = pd.concat([label_df, pred_df], axis=1, sort=True).reindex(label_df.index)
    figures = analysis_position.score_ic_graph(pred_label, show_notebook=False)
    print("AI模型预测个股收益的IC和Rank IC值可视化结果", timer() - start)
    for i, fig in enumerate(figures):
        # 如果你在支持 Plotly 的环境中（如 Dash 或某些 IDE），也可以直接显示
        fig.show()

    print("✅ 训练与回测完成！")