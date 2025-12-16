import multiprocessing
import logging
import os

from timeit import default_timer as timer


from loguru import logger
import pandas as pd  # 导入pandas库进行数据处理
import qlib
from qlib.config import REG_CN
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.model import LGBModel
from qlib.contrib.report.analysis_position import report_graph
from qlib.data.filter import ExpressionDFilter, NameDFilter
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.workflow import R
from qlib.data.dataset import DatasetH
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord
from qlib.contrib.report import analysis_model, analysis_position
from qlib.data import D  # 导入数据模块
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA
import plotly.graph_objects as go

from pprint import pprint
from custom_utils import pprint_position_report, analyze_position_by_date, generate_position_report, \
    pprint_risk_analysis

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助

    print(qlib.__version__)  # 如果能够打印出版本号，说明安装成功

    start = timer()

    logger.remove(0)

    # logger.add("Filter.log", filter=lambda record: record["function"].startswith("_filter_stocks_by_return_threshold"))
    # logger.add("Filter.log", filter=lambda record: "custom_strategy:" in record["message"])

    logger.add("Filter.log", filter=lambda record: record["module"] == "custom_strategy")
    logger.add("orders.log", filter=lambda record: record["module"] != "custom_strategy")
    # logger.add("orders.log", filter=lambda record: record["module"] == "qlib.backtest.position")
    # logger.add(
    #     "logs/custom_strategy_{time:YYYY-MM-DD}.log",
    #     format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[name]}:{function}:{line} - {message}",
    #     filter=lambda record: record["extra"].get("name") == "custom_strategy",
    #     level="INFO",
    #     rotation="00:00",  # 每天午夜轮转
    #     retention="30 days",
    #     compression="zip",
    #     encoding="utf-8"
    # )
    #
    # # 其他日志的文件处理器
    # logger.add(
    #     "orders.log",
    #     filter=lambda record: record["extra"].get("name") != "custom_strategy"
    # )

    qlib.init(
        # 数据存储路径
        provider_uri = "~/.qlib/qlib_data/my_data",  # target_dir
        # 中国市场
        region=REG_CN,
        kernels=16,
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

    # 显示所有行
    pd.set_option('display.max_rows', None)
    # 显示所有列
    pd.set_option('display.max_columns', None)
    # 设置列宽，确保长文本完整显示
    pd.set_option('display.max_colwidth', None)
    # 设置显示宽度，防止自动换行
    pd.set_option('display.width', None)

    start_time="2025-10-01"
    end_time="2025-12-12"

    fit_start_time=start_time
    fit_end_time="2025-10-31"

    valid_start_time="2025-11-01"
    valid_end_time="2025-12-09"

    test_start_time="2025-12-10"
    test_end_time=end_time

    # 2. 定义动态过滤规则：排除过去5日涨幅超过10%的股票
    # 注意：表达式中的 $close 等字段需要确保在你的数据中存在
    # f"""
    # (
    #     ($close - Ref($close,5)) / Ref($close,5) < -0.10 &
    #     ($high - $low)/$close < 0.05 &
    #     (EMA($close,12) > EMA($close,26))
    # )
    # """
    # expression_rule = "(Ref($close, 0) / Ref($close, 5) - 1) <= 0.10"

    # 要排除的股票代码列表
    exclude_stocks = ['SZ000004', 'SZ000430', 'SZ000488', 'SZ000504', 'SZ000518', 'SZ000595', 'SZ000608', 'SZ000609', 'SZ000615', 'SZ000638', 'SZ000656', 'SZ000668', 'SZ000669', 'SZ000691', 'SZ000697', 'SZ000698', 'SZ000711', 'SZ000736', 'SZ000752', 'SZ000793', 'SZ000820', 'SZ000903', 'SZ000908', 'SZ000909', 'SZ000929', 'SZ000972', 'SZ001270', 'SZ002005', 'SZ002024', 'SZ002047', 'SZ002058', 'SZ002076', 'SZ002122', 'SZ002168', 'SZ002197', 'SZ002199', 'SZ002200', 'SZ002211', 'SZ002214', 'SZ002231', 'SZ002253', 'SZ002289', 'SZ002305', 'SZ002306', 'SZ002388', 'SZ002425', 'SZ002485', 'SZ002496', 'SZ002528', 'SZ002529', 'SZ002569', 'SZ002581', 'SZ002586', 'SZ002592', 'SZ002620', 'SZ002630', 'SZ002647', 'SZ002650', 'SZ002656', 'SZ002693', 'SZ002713', 'SZ002717', 'SZ002742', 'SZ002762', 'SZ002789', 'SZ002808', 'SZ002816', 'SZ002822', 'SZ002848', 'SZ002868', 'SZ002872', 'SZ002898', 'SZ003004', 'SZ003032', 'SZ300020', 'SZ300029', 'SZ300044', 'SZ300052', 'SZ300093', 'SZ300096', 'SZ300097', 'SZ300125', 'SZ300137', 'SZ300147', 'SZ300152', 'SZ300159', 'SZ300165', 'SZ300167', 'SZ300175', 'SZ300198', 'SZ300205', 'SZ300211', 'SZ300225', 'SZ300237', 'SZ300268', 'SZ300301', 'SZ300311', 'SZ300313', 'SZ300326', 'SZ300338', 'SZ300343', 'SZ300344', 'SZ300366', 'SZ300376', 'SZ300379', 'SZ300391', 'SZ300419', 'SZ300462', 'SZ300472', 'SZ300477', 'SZ300506', 'SZ300527', 'SZ300555', 'SZ300561', 'SZ300716', 'SZ300899', 'SZ301288', 'SH600107', 'SH600130', 'SH600136', 'SH600165', 'SH600169', 'SH600193', 'SH600200', 'SH600228', 'SH600238', 'SH600243', 'SH600265', 'SH600289', 'SH600355', 'SH600358', 'SH600360', 'SH600365', 'SH600381', 'SH600421', 'SH600525', 'SH600568', 'SH600599', 'SH600608', 'SH600624', 'SH600636', 'SH600696', 'SH600735', 'SH600753', 'SH600777', 'SH600892', 'SH603007', 'SH603021', 'SH603261', 'SH603268', 'SH603377', 'SH603388', 'SH603389', 'SH603398', 'SH603517', 'SH603557', 'SH603559', 'SH603580', 'SH603595', 'SH603721', 'SH603789', 'SH603813', 'SH603825', 'SH603828', 'SH603838', 'SH603843', 'SH603869', 'SH605081', 'SH605199', 'SH688053', 'SH688076', 'SH688184', 'SH688287', 'SH688511', 'SH688646', 'BJ920305', 'BJ920680']
    # exclude_stocks = ['SZ000004', 'SZ000430', 'SZ000488']

    # 创建排除表达式
    # 这里使用NotIn操作来排除特定股票
    exclude_filter = NameDFilter(name_rule_re='^(?!(' + '|'.join(exclude_stocks) + ')).*$')  # 正则排除

    # 创建表达式过滤器
    # exclude_filter = ExpressionDFilter(rule_expression=exclude_expression)

    expression_rule = f"""
    (
        ($close - Ref($close,5)) / Ref($close,5) < -0.10
    )
    """
    dynamic_filter = ExpressionDFilter(rule_expression=expression_rule)

    # 3. 获取基础股票池（例如全市场或沪深300）应用动态过滤器，获取筛选后的股票列表
    filtered_instruments = D.instruments(market='all',
                                     start_time=start_time,  # 调整为你需要的开始时间
                                     end_time=end_time,  # 调整为你需要的结束时间
                                     filter_pipe=[exclude_filter],  # 应用过滤器
                                     )  # 或者使用 market='all'

    # 定义策略相关的市场和分析基准
    # market = "all"
    # market = "csi300"


    benchmark = "SH601727"  # 设置业绩比较基准为沪深300指数代码
    # market = ['SH600000','SH600010','SH600028','SH600025','SH600019','SH600900','SH600941','SZ300059','SZ300124','SZ300274']

    exp_name = "alpha158_cost_kdj_lgb"

    signal_cols = ["COST_K", "COST_D", "COST_J", "MAIRU_SIGNAL","ZHANGTING"]

    # 定义数据处理器配置，指定数据获取的时间范围、训练集时间区间和投资标的
    data_handler_config = {
        "start_time": start_time,  # 整体数据开始时间
        "end_time": end_time,  # 整体数据结束时间
        "fit_start_time": fit_start_time,  # 特征计算起始时间（通常与start_time一致）
        "fit_end_time": fit_end_time,  # 特征计算结束时间（训练集截止时间）
        # "cost_window": 250,  # 特征计算结束时间（训练集截止时间）
        # "infer_processors": [
        #         {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}}],  # 特征计算结束时间（训练集截止时间）
        # "learn_processors": [{"class": "DropnaLabel"}],  # 特征计算结束时间（训练集截止时间）
        "infer_processors": [
            {"class": "ProcessInf"},
            {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"method": "ffill"}}
        ],
        "instruments": filtered_instruments,  # 投资标的，这里使用前面定义的market（csi300）
        "include_alpha158": True,  # 若仅需自定义因子，可设为 False 以加速
        "include_cost_kdj": True,
        "include_signal": False,
        "include_lz": True,
    }

    handler = Alpha158CostKDJ(**data_handler_config)
    # handler = Alpha158(**data_handler_config) #  **运算符将字典展开为关键字参数

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
                "handler":
                {  # 数据处理器配置
                    "class": "Alpha158CostKDJ",  # 使用Alpha158特征集,一个预定义的数据处理器，它实现了 158 个常用的 Alpha 因子
                    "module_path": "custom_handler",  # 数据处理器所在模块路径
                    # "kwargs": data_handler_config,  # 使用前面定义的data_handler_config
                    # "class": "Alpha158",  # 使用Alpha158特征集,一个预定义的数据处理器，它实现了 158 个常用的 Alpha 因子
                    # "module_path": "qlib.contrib.data.handler",  # 数据处理器所在模块路径
                    "kwargs": data_handler_config,  # 使用前面定义的data_handler_config
                },
                "segments": {  # 定义数据集的分段（训练集、验证集、测试集）
                    "train": (fit_start_time, fit_end_time),  # 训练集时间范围，用于模型训练。
                    "valid": (valid_start_time, valid_end_time),  # 验证集时间范围，用于调参、早停等。
                    "test": (test_start_time, test_end_time),  # 测试集时间范围，用于最终回测评估。
                },
            },
        },
    }

    # 验证数据加载
    data = handler.fetch(col_set="feature")

    print(data.head(10))
    #                            KMID      KLEN  ...    COST_D    COST_J
    # datetime   instrument                      ...
    # 2023-01-03 SH600000   -0.298624 -0.706633  ... -0.085372 -0.023536
    #            SH600009   -1.546573  0.264609  ...       NaN       NaN
    #            SH600010    0.475908 -0.207787  ... -0.688093 -0.629647
    #            SH600011    2.071525  3.000000  ... -0.203372  0.317179
    #            SH600015    0.238334 -1.020868  ...  0.510582  0.613794
    #            SH600016   -0.318746 -1.018924  ... -0.211149 -0.147461
    #            SH600018    0.099265 -0.398185  ... -0.363264 -0.186470
    #            SH600019    0.358459 -0.619303  ... -0.132547 -0.161108
    #            SH600025    1.410132  0.216171  ...  0.223375  0.598955
    #            SH600028    0.429478 -0.831903  ...  1.067183  1.107931
    #
    # [10 rows x 161 columns]
    print(f"所有feature列: {data.columns}")
    all_features = data.columns
    available_cols = [col for col in signal_cols if col in data.columns]
    print(f"可用信号列: {available_cols}")
    print(data[available_cols].head(10))
    # 2023-01-03 SH600000   -0.066754 -0.085372 -0.023536
    #            SH600009         NaN       NaN       NaN
    #            SH600010   -0.671162 -0.688093 -0.629647
    #            SH600011   -0.030015 -0.203372  0.317179
    #            SH600015    0.543704  0.510582  0.613794
    #            SH600016   -0.192020 -0.211149 -0.147461
    #            SH600018   -0.306091 -0.363264 -0.186470
    #            SH600019   -0.144487 -0.132547 -0.161108
    #            SH600025    0.348180  0.223375  0.598955
    #            SH600028    1.079720  1.067183  1.107931

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
            # "class": "TopkDropoutStrategy",  # 使用TopK丢弃策略,一个简单但有效的策略，它每天选择模型预测分数最高的 50 只股票，并剔除其中 5 只持仓最久的股票
            # "module_path": "qlib.contrib.strategy.signal_strategy",  # 策略所在模块路径
            "class": "TopkDropoutStrategyWithFilter",  # 使用TopK丢弃策略,一个简单但有效的策略，它每天选择模型预测分数最高的 50 只股票，并剔除其中 5 只持仓最久的股票
            "module_path": "custom_strategy",  # 策略所在模块路径
            "kwargs": {  # 策略参数
                "model": model,  # 使用的预测模型
                "dataset": dataset,  # 使用的数据集
                "topk": 10,  # 选择信号最强的50只股票
                "n_drop": 3,  # 每次调仓时丢弃排名最后5只股票
                "hold_thresh": 1  # 最小持有1天
            },
        },
        "backtest": {  # 回测参数配置
            "start_time": test_start_time,  # 回测开始时间（与测试集一致）
            "end_time": test_end_time,  # 回测结束时间（与测试集一致）
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

    recorder_path = None
    r_start = timer()
    rid = None
    with R.start(experiment_name=exp_name):
        R.log_params(**flatten_dict(task))  # 将任务配置参数扁平化后记录到实验中，便于追踪
        model.fit(dataset)  # 方法根据数据集对模型进行训练，这个过程会生成模型参数和训练指标 在训练集上训练模型，并在验证集上进行验证
        R.save_objects(trained_model=model)  # 将训练好的模型保存到当前实验记录中
        # 保存的模型可以通过 recorder.load_object("trained_model")在后续流程（如回测阶段）中重新加载使用，确保模型的一致性和可复用性

        rid = R.get_recorder().id  # 获取当前实验记录器的ID，用于后续检索

        # 5. 特征重要性分析与选择
        # 获取特征重要性（新版本QLib模型通常内置该方法）
        # 方式一：直接使用模型提供的 `feature_importance` (如果可用)
        if hasattr(model, 'feature_importance'):
            feat_imp = model.feature_importance()
        else:
            # 方式二：使用模型训练器中的特征重要性（适用于某些版本）
            # 注意：具体方法可能因版本而异，请查阅官方文档
            try:
                feat_imp = model.get_feature_importance()
            except:
                # 方式三：回退方案 - 基于训练数据手动计算（近似）
                # 此方法可能计算较慢，且为近似值
                print(
                    "Warning: Using fallback method for feature importance. Check Qlib documentation for the recommended way.")
                # 此处可能需要根据实际模型类型调整获取方式
                feat_imp = None

        print(f"直接使用模型提供的 `feature_importance` (如果可用)")
        print(feat_imp)
        # Column_17     103
        # Column_1       95
        # Column_178     89
        # Column_175     80
        # Column_27      77

        # 将特征重要性转换为Series并按降序排序
        feat_imp_series = feat_imp.sort_values(ascending=False)

        # 选择前K个最重要的特征
        selected_features = feat_imp_series.index.tolist()
        print(f"将特征重要性转换为Series并按降序排序:")
        print(selected_features)

        selected_features_name = []
        for col in selected_features:
            parts = col.split('_') # Column_17
            if parts:
                number = int(parts[-1])
                selected_features_name.append(all_features[number])
        print(f"重要的特征列名对应的特征名")
        print(selected_features_name)

        K = 50
        # 6. (可选) 可视化特征重要性
        top_features = feat_imp_series.head(K)
        top_features_name = pd.Series(selected_features_name)
        top_features_name=top_features_name.head(K)

        # 创建水平条形图
        feature_importance_fig = go.Figure()

        # 添加条形图轨迹
        feature_importance_fig.add_trace(go.Bar(
            y=top_features_name.values,
            # y=top_features.index.tolist(),
            x=top_features.values,
            orientation='h',
            marker=dict(
                color=top_features.values,
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(title="重要性分数")
            ),
            hovertemplate='<b>%{y}</b><br>重要性: %{x:.4f}<extra></extra>'
        ))

        # 更新布局
        feature_importance_fig.update_layout(
            title=dict(
                text=f'Top {K} 特征重要性',
                x=0.5,
                xanchor='center'
            ),
            xaxis_title='重要性分数',
            yaxis_title='特征名称',
            height=600 + K * 10,  # 动态调整高度以适应特征数量
            template='plotly_white',
            showlegend=False
        )

        # 调整y轴顺序，使最重要的特征在顶部
        feature_importance_fig.update_yaxes(autorange="reversed")

        feature_importance_fig.show()