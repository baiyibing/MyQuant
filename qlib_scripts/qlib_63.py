import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场
from qlib.data.cache import DiskExpressionCache  # 导入磁盘缓存类
from qlib.utils import init_instance_by_config
import pandas as pd
# 多模型比较（执行不成功）
"""
 
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
        # expression_cache=DiskExpressionCache,  # 使用磁盘表达式缓存 加上此句报错
        # dataset_cache=DiskDatasetCache,      # 如需数据集缓存也可配置
        # mem_cache_size=10,                  # 内存缓存大小 (GB)
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
    import pandas as pd
    import numpy as np
    # from qlib.constant import REG_CN
    from qlib.utils import init_instance_by_config, flatten_dict
    from qlib.workflow import R
    from qlib.data import D
    from qlib.contrib.evaluate import risk_analysis, backtest_daily
    from qlib.contrib.report import analysis_position

    # 1. 初始化Qlib环境
    # qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region=REG_CN)

    # 2. 定义模型配置字典（新版推荐方式）
    model_configs = {
        "LGBM": {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8879,
                "learning_rate": 0.0421,
                "subsample": 0.8789,
                "lambda_l1": 205.6999,
                "lambda_l2": 580.9768,
                "max_depth": 8,
                "num_leaves": 210,
                "num_threads": 20,
            }
        },
        "XGBoost": {
            "class": "XGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8,
                "learning_rate": 0.05,
                "subsample": 0.8,
                "max_depth": 7,
                "n_estimators": 200,
            }
        },
        "MLP": {
            "class": "MLPModel",
            "module_path": "qlib.contrib.model.pytorch",
            "kwargs": {
                "input_dim": 158,  # 根据实际特征维度调整
                "output_dim": 1,
                "hidden_dim": [64, 32],
                "dropout": 0.2,
                "learning_rate": 0.001,
                "num_epochs": 100,
                "early_stop": 20,
                "batch_size": 800,
            }
        },
        "LSTM": {
            "class": "LSTMModel",
            "module_path": "qlib.contrib.model.pytorch",
            "kwargs": {
                "input_dim": 158,  # 根据实际特征维度调整
                "output_dim": 1,
                "hidden_size": 64,
                "num_layers": 2,
                "dropout": 0.2,
                "learning_rate": 0.001,
                "num_epochs": 100,
                "early_stop": 20,
                "batch_size": 800,
            }
        }
    }

    # 3. 数据集配置
    dataset_config = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": {
                "class": "Alpha158",
                "module_path": "qlib.contrib.data.handler",
                "kwargs": {
                    "start_time": "2010-01-01",
                    "end_time": "2020-12-31",
                    "fit_start_time": "2010-01-01",
                    "fit_end_time": "2015-12-31",
                    "instruments": "csi300",
                }
            },
            "segments": {
                "train": ("2010-01-01", "2014-12-31"),
                "valid": ("2015-01-01", "2016-12-31"),
                "test": ("2017-01-01", "2020-08-01"),
            }
        }
    }

    # 初始化数据集
    dataset = init_instance_by_config(dataset_config)

    # 4. 训练和评估每个模型
    eval_results = {}
    backtest_results = {}

    for model_name, model_config in model_configs.items():
        print(f"\n=== 训练模型: {model_name} ===")

        # 为每个模型创建独立实验
        with R.start(experiment_name=f"model_comparison_{model_name}"):
            # 记录模型配置
            R.log_params(**flatten_dict({"model": model_config}))

            # 初始化模型
            model = init_instance_by_config(model_config)

            # 训练模型
            model.fit(dataset)

            # 保存模型
            R.save_objects(trained_model=model)

            # 生成预测
            pred_df = model.predict(dataset)
            R.save_objects(predictions=pred_df)

            # 评估指标计算 (新版推荐方式)
            # 获取真实标签
            label_df = dataset.prepare("test", col_set="label")
            label_df.columns = ["label"]

            # 合并预测和标签
            eval_df = pd.concat([label_df, pred_df], axis=1, sort=True).reindex(label_df.index)

            # 计算回归指标
            from sklearn.metrics import mean_squared_error, r2_score
            import scipy.stats as stats

            mse = mean_squared_error(eval_df['label'], eval_df['score']) # qlib.workflow - [utils.py:41] - An exception has been raised[KeyError: 'score'].
            rmse = np.sqrt(mse)
            r2 = r2_score(eval_df['label'], eval_df['score'])

            # 计算IC (信息系数)
            ic, p_value = stats.spearmanr(eval_df['label'], eval_df['score'])

            # 记录评估结果
            model_metrics = {
                'MSE': mse,
                'RMSE': rmse,
                'R2': r2,
                'IC': ic,
                'IC_pvalue': p_value
            }

            R.log_metrics(**model_metrics)
            eval_results[model_name] = model_metrics

            # 执行回测 (可选)
            try:
                backtest_config = {
                    "strategy": {
                        "class": "TopkDropoutStrategy",
                        "module_path": "qlib.contrib.strategy.signal_strategy",
                        "kwargs": {"topk": 50, "n_drop": 5},
                    },
                    "backtest": {
                        "start_time": "2017-01-01",
                        "end_time": "2020-08-01",
                        "account": 100000000,
                        "benchmark": "SH000300",
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

                # 执行回测
                portfolio_metrics, pos_record = backtest_daily(pred_df, **backtest_config)
                backtest_results[model_name] = portfolio_metrics

                # 记录回测结果
                R.save_objects(backtest_results=portfolio_metrics)

            except Exception as e:
                print(f"模型 {model_name} 回测执行失败: {e}")

            print(f"{model_name} 训练和评估完成")

    # 5. 结果汇总和比较
    print("\n" + "=" * 60)
    print("模型性能比较")
    print("=" * 60)

    # 创建比较表格
    metrics_df = pd.DataFrame(eval_results).T
    print("回归指标比较:")
    print(metrics_df[['MSE', 'RMSE', 'R2', 'IC']])

    # 如果有回测结果，也进行比较
    if backtest_results:
        backtest_metrics = pd.DataFrame(backtest_results).T
        print("\n回测绩效比较:")
        print(backtest_metrics[['annualized_return', 'sharpe_ratio', 'max_drawdown', 'information_ratio']])

    # 6. 可视化比较结果
    print("\n生成可视化报告...")

    # 为每个模型加载预测结果并进行比较
    all_preds = {}
    for model_name in model_configs.keys():
        recorder = R.get_recorder(experiment_name=f"model_comparison_{model_name}")
        pred_df = recorder.load_object("predictions")
        all_preds[model_name] = pred_df

    # 生成IC分析图表
    analysis_position.score_ic_graph(all_preds, freq="day")

    # 生成模型性能对比图表
    try:
        from qlib.contrib.report import analysis_model

        analysis_model.model_performance_graph(all_preds, dataset)
    except ImportError:
        print("analysis_model 模块可能已变更，跳过部分可视化")

    # 7. 保存完整比较结果
    with R.start(experiment_name="model_comparison_summary"):
        R.save_objects(
            evaluation_results=eval_results,
            backtest_comparison=backtest_results if backtest_results else None,
            all_predictions=all_preds
        )

        # 记录最佳模型
        best_model_by_ic = metrics_df['IC'].idxmax()
        best_model_by_sharpe = backtest_metrics['sharpe_ratio'].idxmax() if backtest_results else None

        R.log_metrics(
            best_model_ic=best_model_by_ic,
            best_model_sharpe=best_model_by_sharpe
        )

        print(f"\n根据IC值，最佳模型: {best_model_by_ic}")
        if best_model_by_sharpe:
            print(f"根据夏普比率，最佳模型: {best_model_by_sharpe}")

