import multiprocessing
import logging

from timeit import default_timer as timer
from loguru import logger

import qlib
from qlib.config import REG_CN
from qlib.contrib.data.handler import Alpha158
from qlib.contrib.evaluate import backtest_daily, risk_analysis

from qlib.workflow import R
from qlib.data.dataset import DatasetH
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord, PortAnaRecord

from qlib.contrib.report import analysis_position, analysis_model

from custom_handler import CostKDJSignalHandler,Alpha158CostKDJ
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

    exp_name = "cost_kdj_mairu_signal_v097"
    with R.start(experiment_name=exp_name):
        # === 1. 创建 Dataset ===
        # 在Qlib框架中，fit_start_time和fit_end_time是数据处理器（DataHandler）的参数，用于控制数据预处理器的拟合时间段；
        # 而Dataset的segments参数（如train、valid）则用于划分模型训练、验证和测试的数据时间段。
        # 两者的联系在于：fit_start_time和fit_end_time通常与segments中的训练集（train）时间段对齐或重叠，以确保数据预处理（如标准化）的参数仅从训练数据中学习，避免未来信息泄露
        # 预处理器的拟合必须严格使用训练集时间段或更早的数据，而不能包含验证集或测试集的数据。因此，fit_start_time和fit_end_time应设置为训练集（train）的时间范围或其子集
        # Qlib允许fit_start_time/fit_end_time与segments中的train区间不同

        signal_cols = ["COST_K", "COST_D", "COST_J", "MAIRU_SIGNAL"]
        # 要指定 selected_features，只需构造一个合法的 Qlib 特征配置，形式为：
        # 列表：["$expr1", "$expr2"]
        # 元组：(["$expr1", ...], ["name1", ...])
        # 然后直接赋值给 feature= 参数即可。

        handler = Alpha158CostKDJ(
            instruments="all",
            start_time=start_time,    # 整体数据开始时间
            end_time=end_time,      # 整体数据结束时间
            fit_start_time=start_time,# 处理器拟合开始（与train对齐）
            fit_end_time="2020-12-31",  # 处理器拟合结束（与train对齐）
            # freq="day",
            cost_window=250,
            infer_processors=[
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}}],
            learn_processors=[{"class": "DropnaLabel"}],
            include_alpha158=False,  # 若仅需信号，可设为 False 以加速
        )

        # 验证数据加载
        data = handler.fetch(col_set="feature")
        available_cols = [col for col in signal_cols if col in data.columns]
        logger.info(f"可用信号列: {available_cols}")
        print(data[available_cols].head(10))
        #                          COST_K    COST_D    COST_J  MAIRU_SIGNAL
        # datetime   instrument
        # 2020-01-02 SH000300    1.735889  1.684534  1.840051           0.0
        #            SH000852    0.696652  0.629045  0.835493           0.0
        #            SH000905    0.749250  0.677035  0.897105           0.0
        #            SH000906    1.526506  1.447369  1.686254           0.0
        #            SH000985    0.597269  0.596336  0.604120           0.0
        #            SH600000    1.106365  1.073718  1.174914           0.0
        #            SH600004    0.463302  0.474482  0.446456           0.0
        #            SH600006   -0.491942 -0.506512 -0.455473           3.0
        #            SH600007    1.438430  1.468889  1.381055           0.0
        #            SH600008   -0.940429 -0.995247 -0.823091           0.0

        # ⚠️ 关键：设置 process_type="append" 以启用 get_extended_data
        dataset = DatasetH(
            handler=handler,
            segments={
            "train": (start_time, "2020-12-31"), # 与fit时间段一致
            "valid": ("2021-01-01", "2021-12-31"),
            "test": ("2022-01-01", end_time)
            },
            process_type="append",  # 必须设置！否则 get_extended_data 不会调用
            memory_reuse = True
        )
        # data_df = dataset.prepare(segments='test')
        # An exception has been raised[MemoryError: Unable to allocate 2.76 GiB for an array with shape (166, 4456509) and data type float32]
        data_df = dataset.prepare(segments='test',col_set=['feature', 'label'])
        #                         feature                                                                    label
        #                         COST_L1   COST_L2   COST_L3    COST_K    COST_D    COST_J MAIRU_SIGNAL    LABEL0
        # datetime   instrument
        # 2022-01-04 BJ430047   -0.521899 -0.400899  0.818311  0.879079  0.872531  0.896406          0.0  0.015315
        #            BJ430090   -0.657609 -0.671087  1.601823  0.846535  0.395240  1.745890          0.0 -0.114634
        #            BJ430198   -0.473506 -0.791746 -0.210072 -0.167634 -0.266813  0.035854          0.0 -0.011228
        #            BJ430418   -0.454278 -0.714956 -0.271729 -0.332157 -0.443850 -0.103466          0.0 -0.008997
        #            BJ430489   -0.595702 -0.712655 -0.349195 -0.428567 -0.560787 -0.158944          0.0  0.001345
        #            BJ430510   -0.654276 -0.721170 -0.427276 -0.280352 -0.281521 -0.270956          0.0  0.000000
        #            BJ830799   -0.516826 -0.747406 -0.307695 -0.407291 -0.530530 -0.155527          0.0 -0.030368
        #            BJ830832   -0.629242 -0.750254  0.333052  0.275364  0.158595  0.512689          0.0  0.005935
        #            BJ830839   -0.592717 -0.739833 -0.264753 -0.325410 -0.444031 -0.082996          0.0 -0.094832
        #            BJ830946   -0.485984  0.137526  1.292965  1.198949  1.179173  1.241755          0.0 -0.123704
        # 但在 Qlib 0.9.7 的标准用法中，当 col_set 是一个包含多个元素的列表（如 ['feature', 'label']）时，dataset.prepare() 通常返回一个字典
        # {
        #     'feature': <pandas.DataFrame>,
        #     'label': <pandas.DataFrame>
        # }
        # 读取 feature
        feature_df = data_df['feature']
        label_df = data_df['label']
        print(feature_df.head(10))
        pred_score = feature_df["MAIRU_SIGNAL"].rename("score").to_frame()  # 将MAIRU列重命名为score（策略要求）
        logger.info(f"预测分数形状: {pred_score.shape}")

        """
        dataset.prepare的参数说明
            segments：指定要准备的数据时间段
            col_set：选择需要处理的数据列，默认为None，表示选择全部数据列
            data_key：控制返回数据的类型，该参数与Data Handler配合使用，决定返回原始数据还是处理后的数据
                常见取值：
                DataHandlerLP.DK_R：返回原始数据（未处理）
                DataHandlerLP.DK_I：返回经过infer_processors处理的数据（这些处理器会基于历史数据学习参数，并应用于未来数据）
                DataHandlerLP.DK_L：返回经过learn_processors处理的数据（这些处理器通常不依赖历史数据拟合，直接进行处理）

        
        支持两种策略模式：
        模型驱动：用 COST_KDJ_J 作为特征训练 LGB
        信号驱动：直接用 MAIRU == 1 选股
        如果你只想用 MAIRU 信号做策略（不训练模型）：并在 SignalRecord 中设置 signal=("COST_KDJ_MAIRU", "==", 1)。
        # 在回测配置中替换 strategy：
            strategy = TopkDropoutStrategy(
                topk=50,
                n_drop=0,
                signal=("COST_KDJ_MAIRU", "==", 1),  # 仅买入 MAIRU=1 的股票
                keep_hold=True,
            )
            
        TopkDropoutStrategy是一种基于预测分数排序的动态调仓策略。
        其核心逻辑是，在每个交易日，持有预测分数排名前topk的股票，同时卖出持仓中表现最差的n_drop只股票，并买入相同数量的、当前预测分数高但未持有的股票。
        这种策略能保持投资组合的股票数量基本恒定（除非在初始阶段或股票池不足），并通过控制n_drop来管理换手率。
        它非常适合信号驱动型的高频或中频交易场景，旨在通过快速轮换捕捉强势股票的短期收益
        """
        # === 2. 策略：仅交易 MAIRU == 1 的股票 ===
        strategy = TopkDropoutStrategy(
            topk=50,
            n_drop=0,
            signal = pred_score,  # MAIRU信号作为预测分数
            risk_degree = 0.95,  # 95%资金用于投资
            hold_thresh = 1  # 最小持有1天
        )

        # === 4. 执行回测 ===
        report, positions = backtest_daily(
            start_time="2022-01-01",
            end_time=end_time,
            strategy=strategy,
            account=100000000,  # 初始资金1亿
            benchmark="SH000300",  # 沪深300基准
            exchange_kwargs={
                "freq": "day",
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            }
        )

        # Qlib 提供了两个重要的分析记录器（Record）用于可视化：
        #
        # AnalysisRecord（对应 analysis_model）：分析模型预测与实际收益的关系（如 IC、IR 等）
        # PositionRecord（对应 analysis_position）：分析持仓、换手率、行业暴露等
        # 但注意：你当前的 backtest_daily 只返回了 report 和 positions，并未包含模型预测信号（score）

        returns = report["return"]
        benchmark_returns = report["bench"]

        # 风险分析
        analysis_result = risk_analysis(returns)
        print("MAIRU策略回测结果:")
        print("=== 风险绩效分析结果 ===")
        for k, v in analysis_result.items():
            if isinstance(v, float):
                print(f"{k}: {v:.4f}")
            else:
                print(f"{k}: {v}")

        # 风险分析
        analysis_result = risk_analysis(benchmark_returns)
        print("=== benchmark风险绩效分析结果 ===")
        for k, v in analysis_result.items():
            if isinstance(v, float):
                print(f"{k}: {v:.4f}")
            else:
                print(f"{k}: {v}")

        # 累计收益与基准对比
        figures = analysis_position.report_graph(report, show_notebook=False)
        for i, fig in enumerate(figures):
            fig.show()


        """
        analysis_position.report_graph是 Qlib 量化平台中用于生成投资组合综合表现报告的核心可视化函数。
        它通过多维度图表直观展示策略的收益、风险、成本及换手率等关键指标，帮助用户全面评估策略性能
        
        累计收益曲线  cum：
            包括基准累计收益（cum_bench）
            不考虑成本的策略累计收益（cum_return_wo_cost）
            以及考虑交易成本后的策略累计收益（cum_return_w_cost）。
        这些曲线的间距能直观反映交易成本对最终收益的影响程度。
        
        超额收益与回撤：计算策略相对于基准的超额收益，并分别展示其
            cum_ex_return_wo_cost 不考虑成本超额收益
            cum_ex_return_w_cost 考虑成本超额收益
            cum_ex_return_wo_cost_mdd   不考虑成本最大回撤
            cum_ex_return_w_cost_mdd    考虑成本最大回撤
        
        最大回撤 return
            通过阴影区域标注无成本累计收益的最大回撤（return_wo_mdd）和有成本累计收益的最大回撤（return_w_cost_mdd），清晰展示策略在历史周期内的风险暴露情况。
        
        换手率 turnover    以柱状图形式显示策略的日度换手率，帮助用户分析交易频率与策略活跃度
        """

        """
        risk_analysis(report) 返回的是一个包含多种风险与收益指标的 pandas.Series 或 dict，
        常见指标及其含义如下（基于 Qlib 的 qlib.contrib.evaluate.risk_analysis 实现）：
        # 典型的analysis_result包含以下指标：
        {
                                1. 收益相关指标
            'mean': 0.15,                    # 日均收益率	回测期间每日收益率的算术平均值
            'std': 0.15,                     # 日收益率标准差	衡量收益波动性，风险指标
            'annualized_return': 0.15,       # 年化收益率：策略的年化回报率 mean * 252（A股年交易日约252天）
            'cumulative_return': 0.32,       # 累计收益率：整个回测期间的总收益
            'Benchmark Return': 0.32,        # 基准收益率：对照基准（沪深300）的收益率
            
                                2. 风险相关指标
            'annualized_volatility': 0.22,   # 年化波动率：收益波动的年化标准差 std * sqrt(252)，衡量风险程度
            'max_drawdown': -0.18,           # 最大回撤：最大峰值到谷底的损失幅度 投资组合从峰值到谷底的最大损失比例（负值，通常取绝对值理解）
            'mdd_start / mdd_end'	         # 最大回撤起止日期	最大回撤发生的时间区间
            'calmar_ratio': 0.83,            # 卡尔玛比率：年化收益与最大回撤的比率 年化收益率 / 最大回撤绝对值，衡量单位回撤下的收益能力

                                3. 风险调整收益指标
            'sharpe_ratio': 0.68,            # 夏普比率：每单位风险获得的超额收益 (年化收益率 - 无风险利率) / 年化波动率，Qlib 默认无风险利率为0，即 annualized_return / annualized_volatility
            'information_ratio': 0.12,       # 信息比率：超额收益与跟踪误差的比率 超额收益（相对基准）的夏普比率，即 (超额日均收益 / 超额收益标准差) * sqrt(252)
            'sortino_ratio': 0.89,           # 索提诺比率：只考虑下行风险的调整后收益 类似夏普比率，但只考虑下行波动（负收益波动），Qlib 可能不默认计算，需确认版本

                                4. 其他重要指标
            'alpha': 0.05,                   # 阿尔法：相对于基准的超额收益，超额收益中无法被基准解释的部分
            'beta': 0.92,                    # 贝塔：相对于市场基准的系统性风险，相对于基准的系统性风险暴露
            'tracking_error': 0.08,          # 跟踪误差：策略与基准收益差异的标准差
            'downside_risk': 0.15,           # 下行风险：只计算负收益的风险度量
            
                                5. 胜率相关指标
            'win_rate': 0.55,                # 胜率：盈利交易占总交易次数的比例,收益率为正的交易日占比（部分版本支持）
            Profit Loss Ratio                # 盈亏比 平均盈利与平均亏损的比率
        }
        """

        print(f"✅ Qlib v0.9.7 回测完成！实验: {exp_name}")


