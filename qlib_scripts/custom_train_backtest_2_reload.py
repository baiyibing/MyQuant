import multiprocessing
import logging
import os
import pprint
from timeit import default_timer as timer

from loguru import logger
import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.data import D
from qlib.data.filter import ExpressionDFilter, NameDFilter
from custom_handler import Alpha158CostKDJ
from custom_ops import SMA

import sys
from pathlib import Path as _Path
_my_scripts = str(_Path(__file__).resolve().parent.parent / "my_scripts")
if _my_scripts not in sys.path:
    sys.path.insert(0, _my_scripts)
from handler_frame_cache import resolve_qlib_kernels
from custom_utils import pprint_position_report, analyze_position_by_date, generate_position_report, \
    pprint_risk_analysis
import plotly.graph_objects as go
from qlib.contrib.evaluate import risk_analysis
from qlib.contrib.report.analysis_position import report_graph
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord

if __name__ == '__main__':
    multiprocessing.freeze_support()

    print(qlib.__version__)

    start = timer()

    logger.remove(0)
    logger.add("Filter.log", filter=lambda record: record["module"] == "custom_strategy")
    logger.add("orders.log", filter=lambda record: record["module"] != "custom_strategy")

    _kernels = resolve_qlib_kernels()
    print(f"[qlib] kernels={_kernels} (QLIB_KERNELS, default 1)", flush=True)
    qlib.init(
        provider_uri="~/.qlib/qlib_data/my_data",
        region=REG_CN,
        kernels=_kernels,
        redis_host='127.0.0.1',
        redis_port=6379,
        redis_password='123456',
        redis_task_db=1,
        custom_ops=[SMA],
        exp_manager={
            "class": "MLflowExpManager",
            "module_path": "qlib.workflow.expm",
            "kwargs": {
                "uri": "mlruns",
                "default_exp_name": "MyExperiment",
            }
        },
        logging_level=logging.INFO
    )

    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_colwidth', None)
    pd.set_option('display.width', None)

    # 从文件读取最后一个实验ID，或让用户输入
    rid = None
    exp_name = None
    try:
        with open("last_experiment_info_2020-01-01_2025-12-12.txt", 'r', encoding='utf-8') as f:
            content = f.read().strip()
            print(f"文件内容: {content}")

            # 检查文件格式是否符合预期
            if '=' in content:
                rid, exp_name = content.split('=', 1)  # 只分割一次，防止exp_name中有等号
                rid = rid.strip()
                exp_name = exp_name.strip()

                print(f"成功提取 - 实验ID: {rid}")
                print(f"成功提取 - 实验名称: {exp_name}")
            else:
                print(f"文件格式不正确，期望格式: rid=exp_name")

    except FileNotFoundError:
        print(f"错误: 找不到文件")
    except Exception as e:
        print(f"读取文件时发生错误: {e}")

    if not rid or not exp_name:
        print("错误: 未提供实验ID和名称")
        exit(1)

    # 获取实验记录器
    try:
        recorder = R.get_recorder(recorder_id=rid, experiment_name=exp_name)  # 根据rid获取训练记录器
        print(f"成功加载实验记录器: {rid}")
    except Exception as e:
        print(f"加载实验记录器失败: {e}")
        print("可用的实验记录:")
        try:
            experiments = R.list_experiments()
            for exp in experiments:
                print(f"实验: {exp}")
                recorders = R.list_recorders(experiment_name=exp)
                for rec in recorders:
                    print(f"  - 记录器ID: {rec}")
        except:
            pass
        exit(1)

    # 从recorder加载所有保存的对象
    try:
        model = recorder.load_object("trained_model")
        model_config = recorder.load_object("model_config")
        dataset_config = recorder.load_object("dataset_config")
        data_handler_config = recorder.load_object("data_handler_config")
        backtest_config = recorder.load_object("backtest_config")
        test_start_time = backtest_config["test_start_time"]
        test_end_time = backtest_config["test_end_time"]
        benchmark = backtest_config["benchmark"]

        print("成功加载训练好的模型和配置")
        print(f"回测时间段: {test_start_time} 至 {test_end_time}")
        print(f"基准: {benchmark}")

    except Exception as e:
        print(f"加载模型或配置失败: {e}")
        exit(1)

    # test_start_time = '2025-01-01'
    test_end_time = '2025-12-31'

    print("重新创建数据集（使用测试时间段）0")
    pprint.pprint(dataset_config)

    # 重新创建数据集（使用测试时间段）
    dataset_config['kwargs']['segments'] = {
        'test': (test_start_time, test_end_time)
    }

    data_handler_config['end_time'] = test_end_time

    dataset_config['kwargs']['handler'] = {
                    "class": "Alpha158CostKDJ",
                    "module_path": "custom_handler",
                    "kwargs": data_handler_config,
                }

    print("重新创建数据集（使用测试时间段）1")
    pprint.pprint(dataset_config)

    dataset = init_instance_by_config(dataset_config)
    print("数据集创建完成")

    print("\n✅ 数据集创建完成！耗时:", timer() - start)

    # data_df = dataset.prepare(segments='test', col_set=['feature', 'label'])
    # data_df.to_csv('data_test.csv', encoding='utf-8')
    # print("测试数据集保存到本地")

    # 假设已有一个 DatasetH 实例 ds
    handler = dataset.handler  # 直接获取 DataHandler 实例
    print("# 获取特征名称列表")
    feature_names = handler.get_cols()

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
        parts = col.split('_')  # Column_17
        if parts:
            number = int(parts[-1])
            selected_features_name.append(feature_names[number])
    print(f"重要的特征列名对应的特征名")
    print(selected_features_name)

    K = 100
    # 6. (可选) 可视化特征重要性
    top_features = feat_imp_series.head(K)
    top_features_name = pd.Series(selected_features_name)
    top_features_name = top_features_name.head(K)

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

    # 生成预测信号用于验证
    sr = SignalRecord(model, dataset, recorder)
    sr.generate()

    # 创建信号分析记录
    sar = SigAnaRecord(recorder)
    sar.generate()


    # 回测配置
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
            # "class": "TopkDropoutStrategyWithFilter",
            # "module_path": "custom_strategy",
            "class": "TopkDropoutStrategy",  # 使用TopK丢弃策略,一个简单但有效的策略，它每天选择模型预测分数最高的 50 只股票，并剔除其中 5 只持仓最久的股票
            "module_path": "qlib.contrib.strategy.signal_strategy",  # 策略所在模块路径
            "kwargs": {
                "model": model,
                "dataset": dataset,
                "topk": 10,
                "n_drop": 3,
                "hold_thresh": 1
            },
        },
        "backtest": {
            "start_time": test_start_time,
            "end_time": test_end_time,
            "account": 100000000,
            "benchmark": benchmark,
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

    print("打印回测结束时间...")
    pprint.pprint(port_analysis_config['backtest']['end_time'])

    # 执行回测
    print("开始回测...")
    par = PortAnaRecord(recorder, port_analysis_config, "day")
    par.generate()
    print("回测完成")

    # 加载回测结果
    try:
        report_normal_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")    # 每日组合表现报告。它是一个 DataFrame，包含了投资组合每天的关键指标
        positions = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")        # 持仓记录,每日详细的持仓信息，包括现金、每个持仓的股票代码、数量、市值、权重等
        analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")         # 风险分析结果，如计算出的夏普比率、最大回撤等风险指标
        pred_df = recorder.load_object("pred.pkl")  # 预测结果
        print("成功加载回测结果")
    except Exception as e:
        print(f"加载回测结果失败: {e}")
        exit(1)

    # 分析结果
    print("\n=== 回测结果分析 ===")

    print("预测结果head")
    print(pred_df.head(10))
    pred_df.to_csv('预测结果.csv', encoding='utf-8')
    # 预测结果
    #                           score
    # datetime   instrument
    # 2025-01-02 SH600000   -0.000373
    #            SH600009   -0.000373
    #            SH600010   -0.000373
    #            SH600011   -0.000373
    #            SH600015   -0.000373
    #            SH600016   -0.000373
    #            SH600018   -0.000373
    #            SH600019   -0.000373
    #            SH600023   -0.000373
    #            SH600025   -0.000373
    print("预测结果tail")
    print(pred_df.tail(10))

    label_df = dataset.prepare("test", col_set="label")
    label_df.columns = ['label']
    pred_label = pd.concat([label_df, pred_df], axis=1, sort=True).reindex(label_df.index)
    print("pred_label结果head")
    print(pred_label.head(10))
    pred_label.to_csv('预测结果和真实标签.csv', encoding='utf-8')

    # 风险分析
    returns = report_normal_df["return"]
    benchmark_returns = report_normal_df["bench"]

    analysis_result = risk_analysis(returns)
    print("=== 组合风险绩效分析结果 ===")
    pprint_risk_analysis(analysis_result)

    analysis_result = risk_analysis(benchmark_returns)
    print("=== 基准风险绩效分析结果 ===")
    pprint_risk_analysis(analysis_result)

    # 超额收益分析
    analysis_result = risk_analysis(report_normal_df["return"] - report_normal_df["bench"])
    print("=== 超额收益风险指标 ===")
    pprint_risk_analysis(analysis_result)

    # 持仓分析
    print("\n=== 持仓分析 ===")
    analyze_position_by_date(positions)

    # 生成持仓报告
    position_dict = {str(key): value for key, value in positions.items()}
    generate_position_report(position_dict)

    # 可视化结果
    try:
        from qlib.contrib.report import analysis_position

        figures = analysis_position.report_graph(report_df=report_normal_df, show_notebook=False)
        print("生成回测净值图表")
        for i, fig in enumerate(figures):
            fig.show()

        figures = analysis_position.risk_analysis_graph(analysis_df=analysis_df, report_normal_df=report_normal_df,
                                                        show_notebook=False)
        print("生成风险分析图表")
        for i, fig in enumerate(figures):
            fig.show()

        figures = analysis_position.score_ic_graph(pred_label, show_notebook=False)
        print("AI模型预测个股收益的IC和Rank IC值可视化结果", timer() - start)
        for i, fig in enumerate(figures):
            # 如果你在支持 Plotly 的环境中（如 Dash 或某些 IDE），也可以直接显示
            fig.show()

    except Exception as e:
        print(f"图表生成失败: {e}")

    # 保存详细结果到CSV
    report_normal_df.to_csv('backtest_results.csv', encoding='utf-8')
    print("回测结果已保存到 backtest_results.csv")

    print("\n✅ 回测完成！总耗时:", timer() - start)
    print(f"实验ID: {rid}")
    print(f"回测期间: {test_start_time} 至 {test_end_time}")