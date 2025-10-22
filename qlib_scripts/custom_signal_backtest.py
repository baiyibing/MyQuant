import json
import multiprocessing
import logging

from timeit import default_timer as timer
from loguru import logger
import pandas as pd
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
from pprint import pprint, pformat, PrettyPrinter

from custom_utils import pprint_position_report, analyze_position_by_date, generate_position_report, \
    pprint_risk_analysis, analyze_and_visualize_positions

if __name__ == '__main__':
    multiprocessing.freeze_support() # 添加这一行，特别是在 Windows 上打包时可能有帮助
    # Python 中用于支持将多进程程序打包为 Windows 可执行文件（如通过 PyInstaller、cx_Freeze 等工具）的特殊函数，
    # 需在 if __name__ == '__main__':块内首先调用，以避免打包后运行时出现子进程无限递归或崩溃问题。其核心作用与 Windows 系统的进程创建机制相关。

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

    # start_time = "2020-01-01"
    # end_time = "2022-12-31"

    start_time = "2019-01-01"
    end_time = "2021-12-31"

    # 定义策略相关的市场和分析基准
    market = "all"  # 设置股票池为沪深300指数成分股
    market = "csi300"
    benchmark = "SH000300"  # 设置业绩比较基准为沪深300指数代码

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
            instruments=market,
            start_time=start_time,    # 整体数据开始时间
            end_time=end_time,      # 整体数据结束时间
            fit_start_time=start_time,# 处理器拟合开始（与train对齐）
            fit_end_time="2019-12-31",  # 处理器拟合结束（与train对齐）
            infer_processors=[
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}}],
            learn_processors=[{"class": "DropnaLabel"}],
            cost_window=250,
            include_alpha158=False,  # 若仅需自定义因子，可设为 False 以加速
            include_signal=True
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
            "train": (start_time, "2019-12-31"),    # 与fit时间段一致
            "valid": ("2020-01-01", "2020-12-31"),  # 验证集，不用于最终回测，虽然也属于模型开发阶段的“样本外”数据，但其主要作用在于模型开发流程内部（如超参数优化）
            "test": ("2021-01-01", end_time)        # 测试集，投资组合回测配置：明确指定回测使用测试集的时间
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
        feature_df.to_excel('feature_df.xlsx')

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
            topk=10,
            n_drop=3,
            signal = pred_score,  # MAIRU信号作为预测分数
            risk_degree = 0.95,  # 95%资金用于投资
            hold_thresh = 1  # 最小持有1天
        )

        # Qlib 提供了两个重要的分析记录器（Record）用于可视化：
        #
        # AnalysisRecord（对应 analysis_model）：分析模型预测与实际收益的关系（如 IC、IR 等）
        # PositionRecord（对应 analysis_position）：分析持仓、换手率、行业暴露等
        # 但注意：你当前的 backtest_daily 只返回了 report_df 和 positions，并未包含模型预测信号（score）
        # === 4. 执行回测 ===
        report_df, positions = backtest_daily(
            start_time="2021-01-01",    # 与测试集的开始时间一致
            end_time=end_time,          # 与测试集的结束时间一致
            strategy=strategy,
            account=100000000,  # 初始资金1亿
            benchmark=benchmark,  # 沪深300基准
            exchange_kwargs={
                "freq": "day",
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            }
        )

        # 显示所有行
        pd.set_option('display.max_rows', None)
        # 显示所有列
        pd.set_option('display.max_columns', None)
        # 设置列宽，确保长文本完整显示
        pd.set_option('display.max_colwidth', None)
        # 设置显示宽度，防止自动换行
        pd.set_option('display.width', None)

        # 从2021-01-01至2021-12-31，backtest_daily的start_time至end_time,DataFrame
        print(report_df)
        # account：账户总价值，即投资组合的总资产（持仓市值+现金）
        # return：投资组合的单日收益率，反映当日账户价值相对于前一日的变化比例
        # total_turnover：总换手率，衡量投资组合的交易活跃程度
        # turnover：换手率，可能与total_turnover含义相同或略有差异，具体取决于qlib版本
        # total_cost：总交易成本，包括所有交易产生的费用和成本
        # cost：单日交易成本，指当日产生的交易费用
        # value：持仓市值，即投资组合中所有持仓的当前市场价值
        # cash：现金余额，账户中剩余的可用现金
        # bench：基准收益率，用于比较的基准指数（如沪深300）的当日收益率

        #                  account        return  total_turnover  turnover    total_cost      cost         value          cash     bench
        # datetime
        # 2021-01-04  1.000000e+08  0.000000e+00    0.000000e+00  0.000000  0.000000e+00  0.000000  0.000000e+00  1.000000e+08  0.010828
        # 2021-01-05  9.995251e+07  6.912160e-18    9.498056e+07  0.949806  4.749028e+04  0.000475  9.498056e+07  4.971954e+06  0.019132
        # 2021-01-06  1.018981e+08  1.988128e-02    1.384478e+08  0.434879  8.910869e+04  0.000416  1.006655e+08  1.232591e+06  0.009159
        # 2021-01-07  1.021438e+08  2.960938e-03    1.943103e+08  0.548219  1.451089e+05  0.000550  1.006918e+08  1.451956e+06  0.017718
        # 2021-01-08  1.040115e+08  1.895535e-02    2.625986e+08  0.668551  2.135980e+05  0.000671  1.022264e+08  1.785079e+06 -0.003306

        # 2021-12-27  1.124363e+08 -1.415215e-02    1.182544e+10  0.433459  1.178199e+07  0.000433  1.111319e+08  1.304365e+06 -0.000410
        # 2021-12-28  1.122715e+08 -1.031063e-03    1.187426e+10  0.434186  1.183081e+07  0.000434  1.109976e+08  1.273874e+06  0.007448
        # 2021-12-29  1.103502e+08 -1.667956e-02    1.192295e+10  0.433686  1.187953e+07  0.000434  1.090751e+08  1.275081e+06 -0.014625
        # 2021-12-30  1.115607e+08  1.141607e-02    1.197219e+10  0.446223  1.192880e+07  0.000446  1.102769e+08  1.283748e+06  0.007787
        # 2021-12-31  1.123785e+08  7.769501e-03    1.202110e+10  0.438427  1.197773e+07  0.000439  1.111029e+08  1.275633e+06  0.003832

        returns = report_df["return"]
        benchmark_returns = report_df["bench"]

        # 风险分析
        analysis_result = risk_analysis(returns)
        print("=== 风险绩效分析结果 ===")
        pprint_risk_analysis(analysis_result)

        # benchmark风险分析
        analysis_result = risk_analysis(benchmark_returns)
        print("=== benchmark风险绩效分析结果 ===")
        pprint_risk_analysis(analysis_result)

        # 计算超额收益的风险指标
        analysis_result = risk_analysis(report_df["return"] - report_df["bench"])
        print("=== 超额收益的风险指标 ===")
        pprint_risk_analysis(analysis_result)

        # 累计收益与基准对比
        figures = analysis_position.report_graph(report_df, show_notebook=False)
        for i, fig in enumerate(figures):
            fig.show()

        print(type(positions)) # <class 'dict'>
        print(dir(positions))

        with open("positions.txt", "w", encoding='utf-8') as file:
            # 创建PrettyPrinter实例，并指定输出流为文件对象
            printer = PrettyPrinter(stream=file, indent=4, sort_dicts=False, compact=False)
            printer.pprint(positions)  # 直接输出到文件，无需调用write方法

        # 获取一个 Position 对象
        date0 = sorted(positions.keys())[100]
        print("key类型:", type(date0)) # <class 'pandas._libs.tslibs.timestamps.Timestamp'>
        pos0 = positions[date0]
        print("item类型:", type(pos0)) # <class 'qlib.backtest.position.Position'>
        pprint(pos0)
        # init_cash:        回测策略的初始资金。这是策略开始运行时投入的总本金。
        # cash:             当前时刻，投资组合中剩余的可用现金。这部分资金可用于购买新的资产或应对赎回。
        # now_account_value:当前时刻的总账户价值​（或称净资产）。其计算公式通常为：总账户价值 = 所有持仓股票的当前市值 + 现金。这是衡量投资组合规模的核心指标。
        #   amount:             持有该只股票的总市值。其计算公式为：持仓市值 = 持仓数量 × 当前市价。
        #   price:              该股票的平均持仓成本。即建立该头寸的平均买入价格。
        #   weight:             该股票在当前整个投资组合中的权重。其计算公式为：权重 = 该股票持仓市值 / 当前总账户价值。所有权重之和应等于1（100%）。
        #   count_day:          该头寸已经持有的交易天数。这个信息对于需要判断持仓周期（例如，是否超过某个最小持有期）的策略非常有用。
        # {'_settle_type': 'None', 'position': {'cash': 100000000, 'now_account_value': 100000000.0}, 'init_cash': 100000000}
        # {'_settle_type': 'None',
        # 'position': {
        #   'cash': np.float64(7877925.992530895),
        #   'now_account_value': np.float64(97485183.74514942),
        #   'SH600010': {'amount': np.float64(4511249.621682248), 'price': np.float64(2.9330453872680664), 'weight': np.float64(0.13573036830171947), 'count_day': 100},
        #   'SH600011': {'amount': np.float64(6747337.020940266), 'price': np.float64(1.324849247932434), 'weight': np.float64(0.0916980820501779), 'count_day': 100},
        #   'SH600000': {'amount': np.float64(640049.8140541812), 'price': np.float64(12.793843269348145), 'weight': np.float64(0.08399940063704361), 'count_day': 99},
        #   'SH600004': {'amount': np.float64(1924131.3789502233), 'price': np.float64(3.497685194015503), 'weight': np.float64(0.0690361917262088), 'count_day': 99},
        #   'SH600009': {'amount': np.float64(1752442.0547387858), 'price': np.float64(4.942648887634277), 'weight': np.float64(0.08885150993962371), 'count_day': 93},
        #   'SH600015': {'amount': np.float64(1795791.6638856505), 'price': np.float64(5.597679138183594), 'weight': np.float64(0.10311582896264358), 'count_day': 39},
        #   'SH600196': {'amount': np.float64(265916.42417387536), 'price': np.float64(37.25113296508789), 'weight': np.float64(0.10161224192178457), 'count_day': 7},
        #   'SH600018': {'amount': np.float64(5586233.65207548), 'price': np.float64(1.8073878288269043), 'weight': np.float64(0.10356948947379772), 'count_day': 3},
        #   'SH601669': {'amount': np.float64(7738423.138459998), 'price': np.float64(0.8899430632591248), 'weight': np.float64(0.07064412999046171), 'count_day': 2},
        #   'SH601238': {'amount': np.float64(3212911.487739786), 'price': np.float64(2.1521739959716797), 'weight': np.float64(0.07093123580039729), 'count_day': 2}
        #  },
        #  'init_cash': 100000000}

        """qlib.backtest.position.Position

        current state of position
        a typical example is :{
          <instrument_id>: {
            'count': <how many days the security has been hold>,
            'amount': <the amount of the security>,
            'price': <the close price of security in the last trading day>,
            'weight': <the security weight of total position value>,
          },
        }
        """

        # 打印关键结果
        print("===== 持仓分析报告 =====")
        # 分析最近交易日的持仓
        pprint_position_report(positions)
        # 分析最近交易日的持仓
        analyze_position_by_date(positions)

        # 将key Timestamp转为str
        position_dict = {str(key): value for key, value in positions.items()}
        # with open('positions.json', 'w', encoding='utf-8') as f:
        #     json.dump(position_dict, f, ensure_ascii=False, indent=4)   # TypeError: Object of type Position is not JSON serializable
        # 生成报告
        generate_position_report(position_dict)



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


