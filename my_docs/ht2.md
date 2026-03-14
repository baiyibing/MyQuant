Qlib进阶

**一、自定义策略组件

    AI选股模型包含因子生成和预处理、模型训练、策略回测各组件。在Qlib中这些组件通过工作流workflow串联在一起，每个组件均有参数控制。
    因此最简单的自定义策略方式是直接修改参数。
    另外，每个组件都有其对应源码，更灵活的自定义策略方式是修改源码或者仿照源码创建新的继承类。


**二、自定义特征---get_feature_config

    如果不满足于Qlib自带的Alpha158和Alpha360两个因子库，如何自定义新的特征（因子）？
    Alpha158和Alpha360的源码位于qlib.contrib.data.handler，这两个因子库继承了qlib.data.dataset.handler.DataHandlerLP类。
    DataHandlerLP类计算因子的核心方法是get_feature_config。

    通过修改get_feature_config以及它所调用的方法parse_config_to_fields，可以自定义特征。
    例如：qlib/contrib/data/handler_custom.py中的AlphaSimpleCustom它继承了Alpha158类，共包含6个因子，定义单个因子的方式是直接写出该因子的表达式


**三、自定义标签

    Alpha158因子库默认的标签定义方式为：股票t日的标签对应t+2日收盘价相对于t+1日收盘价的涨跌幅，相当于t日收盘后发信号，t+1日收盘时刻开仓，t+2日收盘时刻平仓。
    两种自定义标签方法：

1）、如果希望以vwap价交易，将标签定义为t+2日vwap价相对于t+1日vwap价的涨跌幅，
    那么可以在设置模型训练参数task时，将task[‘dataset’][‘handler’][’class’]的值从Alpha158改为Alpha158vwap，
    Alpha158vwap见qlib/contrib/data/handler_custom.py
    同时在设置回测参数port_analysis_config时，将交易价格deal_price的值从close改为vwap即可
        
    # 方法一:
    # 修改task参数
    # 标签改为vwap价格计算的下期收益，回测改为使用vwap价格交易
    task = {
        "model": {...},
        "dataset": {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158vwap",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": data_handler_config,
                },
                "segments": {...},
            },
        },
    }
    port_analysis_config = {
        "strategy": {...},
        "backtest": {
            ...
            "deal_price": "vwap",
            ...
        },
    }
       
2）更灵活的自定义标签方式是修改因子库源码---get_label_config
   在DataHandlerLP类（即Alpha158因子库的父类）中，计算标签的核心方法是get_label_config，修改该方法可以自定义标签。

    # 图表32：通过修改因子库源码自定义标签代码

    # 方法二：
    # 参考qlib.contrib.data.handler
    # 自定义data.dataset.handler.DataHandlerLP类的get_label_config方法
    
    # Alpha158vwap继承Alpha158类，仅更改标签计算方式
    class Alpha158vwap(Alpha158):
        def get_label_config(self):
            return (["Ref($vwap, -2)/Ref($vwap, -1) - 1"], ["LABEL0"])
    
    # 若t日收盘生成因子，t+1日开盘买入，t+6日开盘卖出
    class AlphaSimpleOpen(Alpha158):
        def get_label_config(self):
            return (["Ref($open, -6)/Ref($open, -1) - 1"], ["LABEL0"])
    

**四、更换数据预处理方法

    Qlib中内置多种数据预处理方法，源码位于qlib.data.dataset.processor，包含样本处理、特征处理、异常值处理、缺失值填充和标准化共5大类13小类，如下表所示。


---

**图表：Qlib内置数据预处理方法**

| 类别 | 方法 | 说明 |
| :--- | :--- | :--- |
| **样本处理** | DropnaProcessor | 删除指定特征为缺失值的样本 |
| | DropnaLabel | 删除标签为缺失值的样本 |
| **特征处理** | DropCol | 删除指定特征 |
| | FilterCol | 筛选指定特征 |
| **异常值处理** | TanhProcess | tanh处理 |
| | ProcessInf | inf以均值替换 |
| **缺失值填充** | Fillna | 以0填充缺失值 |
| | CSZFillna | 以截面均值填充缺失值 |
| **标准化** | MinMaxNorm | 最小最大值标准化至[0,1]范围 |
| | ZScoreNorm | Z分数标准化至标准正态分布，即对原始数据减去均值除以标准差 |
| | RobustZScoreNorm | 稳健Z分数标准化，即对原始数据减去中位数除以1.48倍MAD统计量 |
| | CSZScoreNorm | 截面Z分数标准化至标准正态分布 |
| | CSRankNorm | 截面先转换为rank序数，再Z分数标准化至标准正态分布 |

    实际数据预处理是上述操作的任意组合。例如Alpha158和Alpha360因子库中：
    训练集和验证集的预处理是先剔除标签为缺失值的样本，再对标签（即收益）进行截面标准化；训练集和验证集对应learn_processors
    测试集的预处理是先将inf替换为均值，再进行Z分数标准化，最后将缺失值填充为0。测试集对应infer_processors
    下图为因子库数据预处理的源码，两者均为多项预处理操作组合而成的列表形式。

    自定义数据预处理方法的较简单方式是直接修改数据集参数data_handler_config，增加learn_processors和 infer_processors两个键，值为目标预处理操作组合而成的列表。
    如上图所示：
    训练集和验证集的预处理是先剔除标签缺失的样本，再将每个截面的标签转换为rank序数；
    测试集的预处理是先提取指定的三个因子，再对因子做稳健Z分数标准化，最后将因子缺失值填充为0。
    
**五、更换AI模型


**Qlib内置了丰富的AI模型，官方文档称为Quant Model Zoo，源码位于qlib.contrib.model，支持的模型如下表所示

# 图表36：Qlib内置AI模型（qlib.contrib.model）

| 分类 | 模型 |
| :--- | :--- |
| **线性模型** | Linear（参数可选择 `"ols"`, `"nnls"`, `"ridge"` 和 `"lasso"`） |
| **Boosting 集成学习模型** | LightGBM |
| | Catboost |
| | XGBoost |
| **时间序列相关神经网络模型** | GRU |
| | LSTM |
| | ALSTM |
| | SFM |
| | TFT |
| **图神经网络** | GATs |
| **其它神经网络** | MLP |
| | DNN |

**如果希望使用Qlib内置模型，可以较方便地通过设置模型训练参数task下的AI模型参数model实现，模型本身的超参数也在model中设置。

**如果希望使用的模型并未在Qlib提供的Quant Model Zoo中，可以创建新的类继承Model类，再通过参数model调用新创建的类。创建新类的关键是写模型拟合fit和模型预测predict两个方法。，

**六、其它功能

    下面讨论用户可能关心的其它功能，这些功能有的尚未实现，有的已实现但源码尚未公开，有的源码或已公开但缺少文档。

    预测和调仓频率均为日频，能否更换频率？若数据库为日频，目前可能无法直接通过设置参数的方式实现，相对可行的方式是重新通过dump_all方法读入月频或分钟频原始数据。
    
    如何更新数据？据Qilb开发团队在GitHub上的讨论，目前团队内部已实现该功能，但暂未开源。
    
    能否更换选股组合构建方式？目前仅开源TopkDropoutStrategy 一种已实现的组合构建方法，如需自定义组合构建方式，需要通过继承qlib.contrib.strategy.BaseStrategy类的方式创建新的策略类。
    
    如何实现模型调参？在Qlib原始论文中提到Qlib提供调参引擎Hyperparameters Tuning Engine（HTE），同时笔者观察到源码包含qlib.contrib.tuner模块，但在官方文档里未公布使用方法。截至2020年12月22日，GitHub的产品线路图中包含自动调参（automatic parameter tuning）项目，预计该功能未来可能上线。
    
    能否实现模型滚动训练，例如自动实现2008~2014年训练2015年测试，2009~2015年训练2016年测试，而非手动写循环？笔者在源码和官方文档中暂未找到相关功能。

**七、Qlib特色及使用体会