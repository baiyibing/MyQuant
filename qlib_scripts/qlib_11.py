import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场

# 特征选择（执行成功）
"""
在实际应用中，并非所有特征都对模型有贡献。过多的特征可能导致维度灾难和过拟合。因此，特征选择是量化投资中的重要步骤。
QLib 提供了多种特征选择方法，例如基于特征重要性的选择：
通过特征选择，我们可以减少特征数量，提高模型的泛化能力和解释性。

from qlib.contrib.model.gbdt import LGBModel
from qlib.model.selection import feature_importance

# 训练一个 LightGBM 模型
model = LGBModel()
model.fit(features, labels)

# 计算特征重要性
importance = feature_importance(model, features, labels)

# 选择重要性最高的 50 个特征
selected_features = importance.head(50).index.tolist()

# 使用选择后的特征
features_selected = features[selected_features]
"""

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
    # from qlib.constant import REG_CN
    from qlib.contrib.data.handler import Alpha158
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP
    from qlib.model.ens.group import RollingGroup
    from qlib.workflow import R
    from qlib.workflow.record_temp import SignalRecord
    import matplotlib.pyplot as plt
    import numpy as np

    # 1. 初始化Qlib环境 (建议显式初始化，确保环境一致)
    # 假设使用中国市场数据，请根据你的数据路径调整 `provider_uri`
    # qlib.init(provider_uri='~/.qlib/qlib_data/cn_data', region=REG_CN)

    # 2. 定义数据处理器 (Handler) - 使用内置Alpha158因子或自定义
    # 数据处理器负责加载数据、进行预处理和特征工程
    handler_config = {
        "start_time": "2010-01-01",
        "end_time": "2020-12-31",
        "fit_start_time": "2010-01-01",
        "fit_end_time": "2014-12-31",
        "instruments": "csi300",  # 使用沪深300成分股
        "infer_processors": [
            {"class": "ProcessInf", "kwargs": {}},  # 处理无穷值
            {"class": "Fillna", "kwargs": {}},  # 处理缺失值
        ],
        "learn_processors": [
            {"class": "DropnaLabel", "kwargs": {}},  # 丢弃标签缺失的数据
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "label"}},  # 标签标准化
        ],
    }

    # 创建数据处理器实例
    # 如需使用自定义因子，可参考 `qlib.contrib.data.handler` 创建自定义 Handler
    try:
        # 尝试使用内置的 Alpha158 处理器
        handler = Alpha158(**handler_config)
    except:
        # 回退到通用处理器
        handler = DataHandlerLP(**handler_config)

    # 3. 获取数据集
    # 定义数据集分段
    segments = {
        "train": ("2010-01-01", "2014-12-31"),
        "valid": ("2015-01-01", "2015-12-31"),
        "test": ("2016-01-01", "2020-12-31"),
    }
    # 创建数据集
    ds = DatasetH(handler, segments)

    # 4. 配置与训练 LightGBM 模型
    model_config = {
        "loss": "mse",
        "colsample_bytree": 0.8879,
        "learning_rate": 0.2,
        "subsample": 0.8789,
        "n_estimators": 100,
        "max_depth": 8,
        "num_leaves": 210,
        "min_child_samples": 20,
        "verbosity": -1,
        "random_state": 42,
    }

    model = LGBModel(**model_config)

    # 在训练集上训练模型
    model.fit(ds)

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

    # 将特征重要性转换为Series并按降序排序
    feat_imp_series = feat_imp.sort_values(ascending=False)

    # 选择前K个最重要的特征
    K = 50
    selected_features = feat_imp_series.head(K).index.tolist()

    print(f"Selected top {K} features:")
    print(selected_features)

    # 6. (可选) 可视化特征重要性
    plt.figure(figsize=(10, 12))
    feat_imp_series.head(K).sort_values().plot(kind='barh')
    plt.title(f'Top {K} Feature Importance')
    plt.xlabel('Importance')
    plt.tight_layout()
    plt.savefig('feature_importance.png')
    plt.show()

    # 7. 使用筛选后的特征重新训练模型（可选但推荐）
    # 可以创建一个新的Handler或Dataset，仅包含选定的特征
    # 例如，可以修改handler的配置，只包含selected_features
    # 然后重新训练模型，可能会获得更好的性能或更快的训练速度

    # 8. 集成到工作流中进行回测（示例）
    # 以下代码展示了如何将特征选择集成到QLib的实验工作流中
    with R.start(experiment_name="lgbm_with_feature_selection"):
        # 记录模型和特征重要性
        R.log_params(**model_config)
        R.log_object("feature_importance", feat_imp_series)
        R.log_object("selected_features", selected_features)

        # 训练最终模型（使用全部数据或特定分段）
        model.fit(ds)

        # 生成信号
        sr = SignalRecord(model, ds, R.get_recorder())
        sr.generate()

        # 可以进行组合分析和回测...
        # 具体回测配置请参考QLib文档

    # 注意：以上代码为示例，实际使用时请根据您的数据路径、时间段和需求进行调整。
    # 强烈建议查阅对应版本的QLib官方文档以获取最准确的API信息。