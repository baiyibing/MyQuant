import multiprocessing
import qlib
import logging
from qlib.constant import REG_CN    # 中国市场
from qlib.data.cache import DiskExpressionCache  # 导入磁盘缓存类
from qlib.utils import init_instance_by_config
import pandas as pd
# Qlib 模型滚动更新策略（执行不成功）
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
    # from qlib.constant import REG_CN
    from qlib.utils import init_instance_by_config
    from qlib.workflow import R
    from qlib.data import D
    from qlib.contrib.evaluate import risk_analysis, backtest_daily

    # 初始化Qlib环境
    # qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region=REG_CN)

    # 1. 配置滚动更新策略
    from qlib.workflow.task.gen import RollingGen, TimeAdjuster

    # 创建滚动生成器 - 支持两种滚动模式[1](@ref)
    rolling_gen = RollingGen(
        step=20,  # 滚动步长（交易日）
        rtype=RollingGen.ROLL_SD,  # 滑动窗口模式 (ROLL_EX: 扩展窗口)
        trunc_days=5,  # 截断天数避免未来信息泄露
        test_key="test",  # 测试集键名
        train_key="train"  # 训练集键名
    )

    # 2. 定义基础任务模板
    base_task = {
        "model": {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "max_depth": 8,
                "num_leaves": 210,
                "learning_rate": 0.05,
                "num_threads": 20,
            }
        },
        "dataset": {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": {
                        "start_time": "2010-01-01",
                        "end_time": "2020-12-31",
                        "instruments": "csi300",
                    }
                },
                "segments": {
                    "train": ("2010-01-01", "2015-12-31"),
                    "test": ("2016-01-01", "2016-12-31"),
                }
            }
        }
    }

    # 3. 生成滚动任务序列
    rolling_tasks = rolling_gen.generate(base_task)
    print(f"生成了 {len(rolling_tasks)} 个滚动任务")

    # 4. 初始化OnlineManager[1](@ref)
    # from qlib.workflow.online import OnlineManager
    from qlib.workflow.online.manager import OnlineManager

    online_config = {
        "begin_time": "2016-01-01",
        "freq": "day",
        "strategies": [
            {
                "class": "TopkDropoutStrategy",
                "module_path": "qlib.contrib.strategy.signal_strategy",
                "kwargs": {"topk": 50, "n_drop": 5}
            }
        ],
        "trainer": {
            "class": "DefaultTrainer",
            "module_path": "qlib.workflow.train",
            "kwargs": {"max_epoch": 100, "early_stop": 20}
        }
    }

    online_manager = OnlineManager(**online_config)

    # 5. 执行滚动更新流程
    current_best_ic = -float('inf')
    update_history = []

    for i, task in enumerate(rolling_tasks):
        print(f"\n=== 执行第 {i + 1}/{len(rolling_tasks)} 个滚动任务 ===")

        # 使用工作流记录每次更新
        with R.start(experiment_name=f"rolling_update_{i}"):
            # 初始化模型和数据集
            model = init_instance_by_config(task["model"])
            dataset = init_instance_by_config(task["dataset"])

            # 训练模型
            model.fit(dataset)
            R.save_objects(trained_model=model)

            # 生成预测
            pred_df = model.predict(dataset)
            R.save_objects(predictions=pred_df)

            # 评估模型性能
            label_df = dataset.prepare("test", col_set="label")
            label_df.columns = ["label"]

            eval_df = pd.concat([label_df, pred_df], axis=1, sort=True).reindex(label_df.index)

            # 计算IC值
            from scipy.stats import spearmanr

            ic_value, _ = spearmanr(eval_df['label'], eval_df['score']) # ERROR - qlib.workflow - [utils.py:41] - An exception has been raised[KeyError: 'score'].

            # 记录评估结果
            R.log_metrics(IC=ic_value, task_index=i)

            # 决策是否部署新模型
            if ic_value > current_best_ic:
                # 部署新模型
                model_version = f"lgb_model_v{i + 1}"
                online_manager.deploy_model(model, model_version)

                # 更新最佳IC值和版本记录
                current_best_ic = ic_value
                update_history.append({
                    "version": model_version,
                    "deploy_time": task["dataset"]["kwargs"]["segments"]["test"][1],
                    "IC": ic_value,
                    "improvement": True
                })
                print(f"✅ 已部署新模型: {model_version}, IC: {ic_value:.4f}")
            else:
                update_history.append({
                    "version": f"lgb_model_v{i + 1}",
                    "deploy_time": task["dataset"]["kwargs"]["segments"]["test"][1],
                    "IC": ic_value,
                    "improvement": False
                })
                print(f"❌ 模型未部署, IC: {ic_value:.4f} (当前最佳: {current_best_ic:.4f})")

    # 6. 输出更新历史报告
    print("\n" + "=" * 50)
    print("模型滚动更新历史报告")
    print("=" * 50)

    for update in update_history:
        status = "✅ 已部署" if update["improvement"] else "❌ 未部署"
        print(f"{update['version']}: {status} | IC: {update['IC']:.4f} | 更新时间: {update['deploy_time']}")

    # 7. 在线预测服务配置[1](@ref)
    # 配置预测缓存和更新策略
    prediction_cache_config = {
        "max_size": 1000,  # 缓存最大容量
        "expire_time": "24h"  # 缓存过期时间
    }

    # 配置自动更新策略
    auto_update_config = {
        "update_freq": "day",  # 每日更新
        "trigger_conditions": [
            {"metric": "IC", "threshold": 0.01, "comparison": "increase"},
            {"metric": "MSE", "threshold": 0.05, "comparison": "decrease"}
        ]
    }

    # 保存完整更新历史
    with R.start(experiment_name="rolling_update_summary"):
        R.save_objects(
            update_history=update_history,
            rolling_config=rolling_gen.__dict__,
            online_config=online_config
        )
        R.log_metrics(final_best_IC=current_best_ic)

    print(f"\n滚动更新完成! 最佳模型IC值: {current_best_ic:.4f}")

