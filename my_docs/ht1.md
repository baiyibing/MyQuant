
**一、数据准备 dump_all转换用户数据格式

    除官方数据外，Qlib支持用户提供的csv格式数据，需要调用dump_all指令将csv格式数据转换为bin和txt格式。
    每只股票存成一个csv文件，文件名为股票代码，文件夹命名为hk_data。数据从2008年初至2020年11月末，共计3739只股票（含权证，含已退市）
    股票csv数据需要至少包含下表所示字段。其中有两个“坑”需要注意：
        1. 价格数据的要求在官方文档中未提及，笔者建议采用复权价格，原因在于后续数据标注（源码见qlib.contrib.data.handler）采用close或vwap计算股票未来收益率，
            且回测（源码见qlid.contrib.evaluate.backtest）使用close、open或vwap进行交易。
        2. 数据需包含factor或change字段，否则运行Qlib官方提供的策略全流程范例代码examples/workflow_by_code.py时，策略收益和净值将出现异常。
    stock_code  股票代码与文件名称一致
    date        日频日期
    volume      成交量
    money       成交额
    open        复权开盘价
    high        复权最高价
    low         复权最低价
    close       复权收盘价
    factor      复权因子
    vwap        复权均价
    change      相对前一个交易日涨跌幅
    除个股数据外，还需准备指数数据作为基准。将恒生指数行情数据以和股票数据相同形式保存在相同路径下，命名为hkhsi.csv。

    python scripts/dump_bin.py dump_all 
        --csv_path  ~/.qlib/csv_data/hk_data 
        --qlib_dir ~/.qlib/qlib_data/hk_data 
        --symbol_field_name stock_code                                          csv文件中股票代码列名，此处为stock_code
        --date_field_name date                                                  csv文件中日期列名，此处为date
        --include_fields open,high,low,close,volume,money,factor,vwap,change    其余字段名，注意逗号后不能有空格，否则数据转换将出现错误

**转换完成后，新数据保存在如下路径：C:/Users/username/.qlib/qlib_data/hk_data。该路径下包含calendar、features和instruments三个子文件夹，分别存放交易日历、行情特征和股票池。其中行情特征为bin格式


**三、初始化运行环境和原始数据读取

    调用qlib.data模块可读取原始数据。
    qlib.data.calendar命令可读取指定时间区间内交易日期
    qlib.data.instruments命令可定义股票池，参数market=’all’代表选取全部个股构成股票池
    qlib.data.list_instruments命令可以展示指定时间区间内的股票池，时间区间的意义在于，股票池可能会随时间动态变化，如指数成分股票池。
    qlib.data.features模块可以获取指定股票指定日期指定字段数据


**四、自定义股票池

    上述代码中，股票池定义为全部个股，这种定义方式存在两个问题。
    首先，我们的原始数据中包含恒生指数，但恒生指数是作为基准用，不参与到选股中，在计算因子和后续选股模型构建环节应予以剔除。
    其次，股票是否进入选股池需考虑其它因素，如A股选股模型通常剔除风险警示股票、次新股等，港股中的低价股也不适合纳入。

    qlib.data.filter模块自定义股票池
    首先，使用qlib.data.filter.NameDFilter命令进行股票名称静态筛选，参数name_rule_re为纳入股票代码的正则表达式，如HK[0-9!]表示以HK开头，后续为数字或感叹号的股票代码，感叹号代表目前已退市股票。
    其次，使用qlib.data.filter.ExpressionDFilter命令进行股票因子表达式的动态筛选，参数rule_expression为入选的因子表达式，如$close>=1代表收盘价应大于等于1元。
    随后，通过qlib.data.instruments命令的参数filter_pipe，将两个筛选条件组装到一起。

**五、Alpha158因子库

    日频量价因子AI选股策略，核心环节之一是生成量价因子。
    Qlib提供两套自带的量价因子库，分别为Alpha158和Alpha360，分别包含158和360个Alpha因子，用户也可根据需要自定义因子库。
    这里的因子库并非是计算好的因子值，而是一套生成因子的算法（Qlib中称表达式），因此可迁移至任意股票池。

    from qlib.contrib.data.handler import Alpha158      # 创建并初始化一个 Alpha158 数据处理器后
    h = Alpha158(**data_handler_config)                 # 返回值 `h` 是一个 **`DataHandlerLP` 对象**（具体是 `Alpha158` 类的实例）
    其中参数data_handler_config相当于配置文件，字典类型，用来定义完整数据起止日期（start_time和end_time），拟合数据起止日期（fit_start_time和fit_end_time），股票池（instruments）等。
    拟合数据起止日期区间应为完整数据起止日期数据的子集。拟合数据日期（训练和验证集）和余下日期（测试集）在数据预处理的方式上有所不同?

    执行上述指令后，程序将计算从start_time至end_time的当期因子值和下期收益，分别作为后续AI模型训练的特征和标签。
    当期因子值===特征
    下期收益值===标签
    默认参数下，股票t日的特征对应t日收盘后计算出的因子值。
    默认参数下，股票t日的标签对应t+2日收盘价相对于t+1日收盘价的涨跌幅，相当于t日收盘后发信号，t+1日收盘时刻开仓，t+2日收盘时刻平仓。
    **请注意**：`Alpha158` 处理器默认的标签是 `Ref($close, -2)/Ref($close, -1) - 1`，这表示未来第T+2天收盘价相对于T+1天收盘价的收益率，适用于A股市场的T+1交易制度。

这个对象是 Qlib 中用于处理学习任务（Learning Task）数据的核心组件之一，它封装了特征数据、标签数据以及相应的数据处理流程。
为了让你更清楚地了解这个对象，下面用一个表格来概括它的主要属性和方法：

| 属性/方法                               | 说明                                                                 | 常用程度 |
| :-------------------------------------- | :------------------------------------------------------------------- | :------- |
| **`h.fetch(col_set="feature")`**        | **获取特征数据**。返回一个 DataFrame，索引为 (datetime, instrument)。 | ⭐⭐⭐⭐⭐  |
| **`h.fetch(col_set="label")`**          | **获取标签数据**。返回一个 DataFrame，索引与特征数据一致。            | ⭐⭐⭐⭐⭐  |
| **`h.fetch(col_set="test")`**         | 获取测试集数据（如果配置了测试集）                                   | ⭐⭐⭐    |
| **`h.get_cols()`**                      | 返回所有特征列的名称列表。                                           | ⭐⭐⭐⭐   |
| **`h.get_label_config()`**              | 返回标签的配置信息，例如默认是 `Ref($close, -2)/Ref($close, -1) - 1`。 | ⭐⭐     |
| **`h.infer_processors`**                | 推理阶段使用的数据处理器列表（用于验证集和测试集）。                 | ⭐⭐     |
| **`h.learn_processors`**                | 训练阶段使用的数据处理器列表（用于训练集）。                         | ⭐⭐     |


**简要来说**，`h` 这个 `Alpha158` 实例是一个**数据接口**，它帮你完成了从原始数据中计算、加载、处理 Alpha158 因子特征和相应标签的复杂工作，并以一种规整的表格形式（DataFrame）提供给你，方便后续的机器学习模型直接使用。
**两个因子KMID和KLEN为例
    
    KMID=(close-open)/open，其含义为日内涨跌幅
    KLEN=(high-low)/open，其含义为日内振幅
    
**六、LightGBM选股策略构建（参考Qlib范例workflow_by_code_py）


**模型训练参数task为字典类型，较复杂，也是整个模型的核心部分，又可以分为model和dataset两个字典。

    第一项model为AI模型参数，必须包含class（AI模型名称）和module_path（AI模型所在路径）两个子键；kwargs为model的可选子键，通过kwargs设置指定AI模型的超参数。

    第二项dataset为数据集参数，必须包含class（数据集名称）和module_path（数据集所在路径）两个子键；kwargs为dataset的可选子键，通过kwargs设置指定数据集的参数。

**通过qlib.utils.init_instance_by_config命令将上述参数分别写入模型，分别返回模型model和数据集dataset。

**完成模型训练参数定义后，调用qlib.workflow模块正式进行训练，

    依次执行如下命令：
        qlib.workflow.start开启训练；
        model.fit拟合模型；
        qlib.workflow.save_objects保存模型；
        qlib.workflow.get_recorder().id获取“实验”（即模型训练）记录的编号。

**LightGBM模型迭代的实质是参数优化，当验证集损失连续50轮未降低时停止迭代，

**七、选股策略回测

**设置策略回测参数port_analysis_config，该参数为字典类型，又可以分为strategy和backtest两个子键。

    第一项strategy为策略参数，例如此处使用TopkDropout策略，每日等权持有topk=50只股票，同时每日卖出持仓股票中最新预测收益最低的n_drop=5只股票，买入未持仓股票中最新预测收益最高的n_drop=5只股票。

    第二项backtest为回测参数，用于设置涨跌停限制、起始资金、业绩比较基准、成交价格、交易费率等信息。

**调用qlib.workflow模块正式进行回测，依次执行如下命令：
    
    qlib.workflow.start开启回测；
    qlib.workflow.get_recorder获取此前模型训练“实验”记录；
    recorder.load_object读取模型；
    qlib.workflow.get_recorder初始化回测“实验”记录；
    qlib.workflow.record_temp.SignalRecord初始化调仓信号；
    sr.generate生成调仓信号；
    qlib.workflow.record_temp.PortAnaRecord初始化回测及绩效分析；
    par.generate生成回测及绩效分析结果。

**回测代码运行过程中，还显示部分预测结果。
    
    例如在测试集第一个交易日（2020年7月2日）对个股下期收益的预测值，如HK00001预测值为-0.018582；
    又如不扣费及扣费后的日均收益、日度波动率、年化收益、信息比率和最大回撤。

**八、回测和绩效分析结果展示

**完成策略回测后，调用qlib.contrib.report模块展示回测和绩效分析结果。

    展示前首先执行qlib.workflow.get_recorder获取回测“实验”记录，相关结果均储存为pkl格式，
    执行recorder.load_object读取
    预测结果pred.pkl
    回测报告report_normal.pkl
    仓位情况positions_normal.pkl
    持仓分析port_analysis.pkl。

**执行下列命令展示AI模型预测个股收益的IC和Rank IC值，可视化结果如下图所示。

    label_df = dataset.prepare("test", col_set="label")
    label_df.columns = ['label']
    pred_label=pd.concat([label_df,pred_df],axis=1,sort=True).reindex(label_df.index)
    analysis_position.score_ic_graph(pred_label)


**执行analysis_position.report_graph(report_normal_df)展示回测净值相关结果。如下图所示，7张子图自上而下分别为：

    不扣费、扣费和基准净值；
    不扣费净值最大回撤；
    扣费净值最大回撤；
    不扣费和扣费超额收益净值；
    换手率；
    不扣费超额收益最大回撤；
    扣费超额收益最大回撤。

**至此，我们走完了港股日频量价因子AI选股策略的全流程，希望帮助读者快速上手Qlib。

**下面我们将介绍Qlib进阶功能，如需自定义AI选股策略的组件，应如何通过代码实现。