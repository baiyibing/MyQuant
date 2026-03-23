par = PortAnaRecord(recorder, port_analysis_config, "day")  # 传入记录器、回测配置和时间频率
par.generate()  # 系统会基于配置启动完整的回测流程，包括初始化投资组合、模拟每日交易、计算持仓价值，并最终生成包含收益曲线、夏普比率和最大回撤等指标的分析报告

# 'The following are analysis results of benchmark return(1day).'
#                        risk
# mean               0.000297
# std                0.009591
# annualized_return  0.070800
# information_ratio  0.478475
# max_drawdown      -0.108001
# 'The following are analysis results of the excess return without cost(1day).'
#                        risk
# mean               0.000512
# std                0.007390
# annualized_return  0.121823
# information_ratio  1.068579
# max_drawdown      -0.049597
# 'The following are analysis results of the excess return with cost(1day).'
#                        risk
# mean               0.000329
# std                0.007401
# annualized_return  0.078281
# information_ratio  0.685570
# max_drawdown      -0.057426
# 'The following are analysis results of indicators(1day).'
#      value
# ffr    1.0
# pa     0.0
# pos    0.0
"""
在 Qlib 中，调用 par.generate()生成的回测分析报告默认会保存到本地，主要通过 Qlib 的工作流记录系统进行管理
报告保存位置与内容
回测完成后，生成的分析报告和相关数据会以 Python pickle 文件（.pkl格式）的形式，保存在您当前运行的“实验”所对应的记录器中。您可以通过以下步骤获取这些报告：
获取记录器：首先需要获取执行回测的那个记录器对象。
加载报告文件：使用记录器的 load_object方法加载特定的报告文件。
以下是生成的主要分析报告文件及其含义：
report_normal_1day.pkl：这是核心的每日组合表现报告。它是一个 DataFrame，包含了投资组合每天的关键指标，例如：
    return：投资组合的日收益率
    cost：交易成本
    bench：基准（如沪深300）的日收益率
    turnover：换手率
positions_normal_1day.pkl：此文件保存了每日详细的持仓信息，包括现金、每个持仓的股票代码、数量、市值、权重等。
port_analysis_1day.pkl：此文件包含风险分析结果，如计算出的夏普比率、最大回撤等风险指标
"""

report_normal_df = recorder.load_object("portfolio_analysis/report_normal_1day.pkl")  # 普通报告
print("普通报告")
print(report_normal_df.head(10))
#                  account        return  total_turnover  turnover     total_cost      cost         value          cash     bench
# datetime
# 2025-01-02  1.000000e+08  0.000000e+00    0.000000e+00  0.000000       0.000000  0.000000  0.000000e+00  1.000000e+08 -0.029101
# 2025-01-03  9.995250e+07 -6.184564e-17    9.499240e+07  0.949924   47496.200661  0.000475  9.499240e+07  4.960102e+06 -0.011842
# 2025-01-06  9.977200e+07 -1.599917e-03    1.177013e+08  0.227197   68087.926556  0.000206  9.906677e+07  7.052291e+05 -0.001640
# 2025-01-07  9.963182e+07 -1.132319e-03    1.448909e+08  0.272517   95293.228832  0.000273  9.892239e+07  7.094250e+05  0.007201
# 2025-01-08  9.962876e+07  2.424084e-04    1.720861e+08  0.272957  122502.487049  0.000273  9.891853e+07  7.102330e+05 -0.001815
# 2025-01-09  9.825507e+07 -1.351865e-02    1.989188e+08  0.269327  149344.902865  0.000269  9.755221e+07  7.028590e+05 -0.002465
# 2025-01-10  9.710504e+07 -1.143511e-02    2.253884e+08  0.269397  175822.280388  0.000269  9.641307e+07  6.919667e+05 -0.012540
# 2025-01-13  9.683369e+07 -2.517667e-03    2.522351e+08  0.276471  202686.771864  0.000277  9.613312e+07  7.005769e+05 -0.002671
# 2025-01-14  9.919015e+07  2.462459e-02    2.802384e+08  0.289189  230718.374729  0.000289  9.846085e+07  7.293065e+05  0.026334
# 2025-01-15  9.939273e+07  2.323229e-03    3.080876e+08  0.280766  258580.614262  0.000281  9.866534e+07  7.273911e+05 -0.006415
returns = report_normal_df["return"]
benchmark_returns = report_normal_df["bench"]

# 风险分析
analysis_result = risk_analysis(returns)
print("=== 风险绩效分析结果 ===")
pprint_risk_analysis(analysis_result)
# === 风险绩效分析结果 ===
# risk: mean                 0.000809
# std                  0.009135
# annualized_return    0.192622
# information_ratio    1.366866
# max_drawdown        -0.071131
# Name: risk, dtype: float64

# benchmark风险分析
analysis_result = risk_analysis(benchmark_returns)
print("=== benchmark风险绩效分析结果 ===")
pprint_risk_analysis(analysis_result)
# === benchmark风险绩效分析结果 ===
# risk: mean                 0.000297
# std                  0.009591
# annualized_return    0.070800
# information_ratio    0.478475
# max_drawdown        -0.108001
# Name: risk, dtype: float64

# 计算超额收益的风险指标
analysis_result = risk_analysis(report_normal_df["return"] - report_normal_df["bench"])
print("=== 超额收益的风险指标 ===")
pprint_risk_analysis(analysis_result)
# === 超额收益的风险指标 ===
# risk: mean                 0.000512
# std                  0.007390
# annualized_return    0.121823
# information_ratio    1.068579
# max_drawdown        -0.049597
# Name: risk, dtype: float64

positions = recorder.load_object("portfolio_analysis/positions_normal_1day.pkl")  # 持仓记录
print("持仓记录")
# 分析最近交易日的持仓
pprint_position_report(positions)
# 分析最近交易日的持仓
analyze_position_by_date(positions)
# 生成报告
position_dict = {str(key): value for key, value in positions.items()}
generate_position_report(position_dict)

analysis_df = recorder.load_object("portfolio_analysis/port_analysis_1day.pkl")  # 分析报告
print("分析报告")
print(analysis_df.head(10))
#                                                   risk
# excess_return_without_cost mean               0.000512
#                            std                0.007390
#                            annualized_return  0.121823
#                            information_ratio  1.068579
#                            max_drawdown      -0.049597
# excess_return_with_cost    mean               0.000329
#                            std                0.007401
#                            annualized_return  0.078281
#                            information_ratio  0.685570
#                            max_drawdown      -0.057426

figures = analysis_position.report_graph(report_df=report_normal_df, show_notebook=False)
print(
    "展示回测净值可视化结果(不扣费、扣费和基准净值；不扣费净值最大回撤；扣费净值最大回撤；不扣费和扣费超额收益净值；换手率；不扣费超额收益最大回撤；扣费超额收益最大回撤)",
    timer() - start)
for i, fig in enumerate(figures):
    fig.show()

figures = analysis_position.risk_analysis_graph(analysis_df=analysis_df, report_normal_df=report_normal_df,
                                                show_notebook=False)
print("生成风险分析图表可视化结果(年化收益率\波动率\信息比率\最大回撤)", timer() - start)
for i, fig in enumerate(figures):
    fig.show()

data_df = dataset.prepare(segments='test', col_set=['feature', 'label'])
print(data_df.head(10))
#                         feature            ...               label
#                            KMID      KLEN  ...    COST_J    LABEL0
# datetime   instrument                      ...
# 2025-01-02 SH600000   -1.094309  1.112157  ...  1.419466  0.008949
#            SH600009   -1.885474  1.238996  ...       NaN  0.000000
#            SH600010   -1.844725  1.732232  ...  0.256333  0.011371
#            SH600011   -2.143927  1.458528  ... -0.898165 -0.002981
#            SH600015   -2.509159  1.886665  ...  1.472711  0.001351
#            SH600016   -2.171542  1.984429  ...  1.141696  0.004983
#            SH600018   -1.323347  0.981285  ...  0.583204 -0.006141
#            SH600019   -0.624932 -0.027884  ...  1.010373  0.004384
#            SH600023   -2.076626  1.375968  ...  0.017027 -0.011719
#            SH600025   -1.655245  1.014867  ... -0.275800 -0.001794
#
# [10 rows x 162 columns]
feature_df = data_df['feature']
label_df = data_df['label']

print("feature_df结果head")
print(feature_df.head(10))
#                            KMID      KLEN  ...    COST_D    COST_J
# datetime   instrument                      ...
# 2025-01-02 SH600000   -1.094309  1.112157  ...  1.337797  1.419466
#            SH600009   -1.885474  1.238996  ...       NaN       NaN
#            SH600010   -1.844725  1.732232  ...  0.529145  0.256333
#            SH600011   -2.143927  1.458528  ... -0.687459 -0.898165
#            SH600015   -2.509159  1.886665  ...  1.588773  1.472711
#            SH600016   -2.171542  1.984429  ...  1.224480  1.141696
#            SH600018   -1.323347  0.981285  ...  0.534174  0.583204
#            SH600019   -0.624932 -0.027884  ...  1.044818  1.010373
#            SH600023   -2.076626  1.375968  ...  0.207711  0.017027
#            SH600025   -1.655245  1.014867  ... -0.070628 -0.275800
#
# [10 rows x 161 columns]
print("label_df结果head")
print(label_df.head(10))
#                          LABEL0
# datetime   instrument
# 2025-01-02 SH600000    0.008949
#            SH600009    0.000000
#            SH600010    0.011371
#            SH600011   -0.002981
#            SH600015    0.001351
#            SH600016    0.004983
#            SH600018   -0.006141
#            SH600019    0.004384
#            SH600023   -0.011719
#            SH600025   -0.001794
print("pred_df结果head")
print(pred_df.head(10))
# pred_df结果head
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
label_df = dataset.prepare("test", col_set="label")
label_df.columns = ['label']
pred_label = pd.concat([label_df, pred_df], axis=1, sort=True).reindex(label_df.index)
print("pred_label结果head")
print(pred_label.head(10))
#                           label     score
# datetime   instrument
# 2025-01-02 SH600000    0.008949 -0.000373
#            SH600009    0.000000 -0.000373
#            SH600010    0.011371 -0.000373
#            SH600011   -0.002981 -0.000373
#            SH600015    0.001351 -0.000373
#            SH600016    0.004983 -0.000373
#            SH600018   -0.006141 -0.000373
#            SH600019    0.004384 -0.000373
#            SH600023   -0.011719 -0.000373
#            SH600025   -0.001794 -0.000373

figures = analysis_position.score_ic_graph(pred_label, show_notebook=False)
print("AI模型预测个股收益的IC和Rank IC值可视化结果", timer() - start)
for i, fig in enumerate(figures):
    # 如果你在支持 Plotly 的环境中（如 Dash 或某些 IDE），也可以直接显示
    fig.show()

# 打印完成信息
print("策略回测完成！", rid, timer() - r_start)

print("✅ 训练与回测完成！")

"""
在Qlib中，pred.pkl文件保存了模型在测试集上生成的预测结果，其核心字段包括时间戳、股票代码以及模型给出的预测分数。这个文件是连接模型预测与后续回测分析的关键输出。
预测分数：这是文件中最核心的数值。模型会为每一个股票在每一个交易日期预测一个代表其未来潜力的分数。
一般而言，分数越高，表示模型认为该股票在未来时间段内的预期收益也越高。这个分数是后续构建投资组合（如买入高分股票、卖出低分股票）的直接依据
分数含义：预测分数的具体含义取决于模型训练时使用的标签（label）。如果标签是未来收益率，那么预测分数就直接与预期收益率相关

在 Qlib 中，dataset.prepare(segments='test', col_set=['feature', 'label'])的 label表示机器学习模型要预测的目标变量。
具体到量化投资场景，label通常是未来某个时间段的收益率或其他能够衡量投资回报的指标。

标签在量化投资中的具体含义
在 Qlib 的框架中，label是监督学习的核心组成部分，它代表了模型需要学习和预测的金融目标。

常见的 label定义包括：
未来收益率：最常用的标签，计算为 (未来N日价格 - 当前价格) / 当前价格，模型的目标是预测股票未来的价格走势
涨跌分类：将未来收益率转化为分类问题，例如设定阈值将股票分为"上涨"和"下跌"两类
相对排名：根据未来收益率对股票进行排名，用于构建投资组合

特征与标签的关系
在 Qlib 的数据集中，col_set=['feature', 'label']表示同时获取特征和标签数据：
特征（feature）：描述股票当前状态的各种指标，如价格、成交量、技术指标等，作为模型的输入变量
标签（label）：基于未来数据计算的目标值，作为模型训练时的监督信号

标签在模型训练中的作用
当使用 segments='test'参数时，Qlib 会准备测试集的数据，其中标签用于评估模型在未见数据上的表现。通过比较模型预测的标签值与真实的标签值，可以评估模型的预测准确性。
需要注意的是，在实际的量化策略中，标签的定义直接影响模型的学习目标和最终的交易性能，因此需要谨慎设计以避免未来函数和保证实际可交易性。

"""