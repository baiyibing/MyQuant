import multiprocessing
import logging

import qlib  # 导入Qlib核心库
import pandas as pd  # 导入pandas库进行数据处理
from qlib.constant import REG_CN  # 导入中国区域常量
from qlib.utils import init_instance_by_config, flatten_dict  # 导入根据配置初始化实例和扁平化字典的工具函数
from qlib.workflow import R  # 导入工作流管理模块，用于实验记录和管理
from qlib.workflow.record_temp import SignalRecord, PortAnaRecord  # 导入生成信号和组合分析记录的工具类
from qlib.data import D  # 导入数据模块

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
        redis_task_db=1,  # Redis 数据库编号
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

    ba_rid = '23df121c100d4968b21ba11973083657'

    from qlib.contrib.report import analysis_model, analysis_position

    # 获取记录器
    recorder = R.get_recorder(recorder_id=ba_rid, experiment_name="backtest_analysis")

    # 加载回测结果
    pred_df = recorder.load_object("pred.pkl")  # 预测结果
    report_normal_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")  # 普通报告
    positions = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")  # 持仓记录
    analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")  # 分析报告

    # 生成综合报告图表
    # 这个函数会生成一个包含多个子图的综合报告，包括：
    # 累计收益率曲线（含基准和有无交易成本的对比）
    # 最大回撤曲线
    # 超额收益率曲线
    # 换手率曲线
    analysis_position.report_graph(report_normal_df)


    # 生成风险分析图表
    # 风险分析图表通常包括：
    # 年化收益率
    # 波动率
    # 信息比率
    # 最大回撤
    analysis_position.risk_analysis_graph(analysis_df, report_normal_df)

    # 生成 IC 分析图表
    # 对于因子模型，IC（信息系数）是一个重要的评估指标，它衡量了因子预测值与实际收益率之间的相关性：
    # IC 分析图表通常包括：
    # IC 值序列
    # IC 均值和标准差
    # IC 的分布直方图
    # 高 IC 值表明因子具有较强的预测能力。

    print("Columns in pred_df:", pred_df.columns.tolist())  # 查看所有列名
    print("Does 'label' exist?", 'label' in pred_df.columns)  # 检查特定列是否存在

    analysis_position.score_ic_graph(pred_df, freq="day")
    # 报错 ERROR - qlib.workflow - [utils.py:41] - An exception has been raised[KeyError: 'label'].
    # QLib 采用分层的数据架构，主要包括以下几个层次：
    #
    # 原始数据层：存储最基础的行情数据，如开盘价、收盘价、最高价、最低价、成交量等
    # 特征层：基于原始数据计算得到的各种技术指标和因子
    # label 标签层：用于模型训练的目标变量，如未来收益率
    # 这种分层架构使得数据的组织更加清晰，也方便了不同层次数据的管理和复用。