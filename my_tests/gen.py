# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
TaskGenerator模块可以根据TaskGen和一些任务模板生成多个任务。
这个模块是QLib工作流管理的核心组件之一，主要功能是任务生成和滚动测试。
以下是各部分的详细说明：

1. 核心架构
task_generator函数：主入口函数，通过组合多个TaskGen生成器和任务模板，生成最终的任务列表
TaskGen抽象基类：定义了任务生成器的统一接口，所有具体生成器都需要实现generate方法

2. 主要生成器类
RollingGen：实现时间序列滚动训练，支持两种滚动模式：
ROLL_EX（扩展模式）：训练集随时间扩展，测试集固定大小滑动
ROLL_SD（滑动模式）：训练集和测试集都固定大小滑动
MultiHorizonGenBase：基类，用于生成不同预测周期（horizon）的任务

3. 关键特性
避免数据泄露：通过trunc_segments函数截断训练数据，确保不会使用未来信息
灵活性：支持自定义任务复制函数，可以优化内存使用和性能
可扩展性：通过继承TaskGen可以轻松实现新的任务生成策略
这个模块是QLib自动化量化研究工作流的重要组成部分，支持用户构建自定义的量化研究流程
。

"""
import abc
import copy
import pandas as pd
from typing import Dict, List, Union, Callable

from qlib.utils import transform_end_date
from .utils import TimeAdjuster


def task_generator(tasks, generators) -> list:
    """
    使用TaskGen列表和任务模板列表生成不同的任务。

    示例：

        有3个任务模板a、b、c和2个TaskGen A、B。A会从一个模板生成2个任务，B会从一个模板生成3个任务。
        task_generator([a, b, c], [A, B])最终会生成3 * 2 * 3 = 18个任务。

    参数
    ----------
    tasks : List[dict] or dict
        任务模板列表或单个任务
    generators : List[TaskGen] or TaskGen
        TaskGen列表或单个TaskGen

    返回
    -------
    list
        任务列表
    """

    # 如果输入是单个字典，转换为列表形式
    if isinstance(tasks, dict):
        tasks = [tasks]
    # 如果输入是单个TaskGen，转换为列表形式
    if isinstance(generators, TaskGen):
        generators = [generators]

    # 遍历所有生成器，依次生成任务
    for gen in generators:
        new_task_list = []
        for task in tasks:
            # 每个生成器基于当前任务列表生成新任务
            new_task_list.extend(gen.generate(task))
        tasks = new_task_list  # 更新任务列表为生成的新任务

    return tasks


class TaskGen(metaclass=abc.ABCMeta):
    """
    生成不同任务的基类（抽象类）

    示例1：

        输入：特定任务模板和滚动步长
        输出：任务的滚动版本

    示例2：

        输入：特定任务模板和损失函数列表
        输出：具有不同损失函数的任务集合
    """

    @abc.abstractmethod
    def generate(self, task: dict) -> List[dict]:
        """
        基于任务模板生成不同的任务（抽象方法，子类必须实现）

        参数
        ----------
        task: dict
            任务模板

        返回
        -------
        typing.List[dict]:
            任务列表
        """

    def __call__(self, *args, **kwargs):
        """
        语法糖，使得实例可以像函数一样调用
        """
        return self.generate(*args, **kwargs)


def handler_mod(task: dict, rolling_gen):
    """
    在使用RollingGen时帮助修改处理器的结束时间
    尝试处理以下情况：

    - 处理器的数据结束时间早于数据集测试数据分段的时间。

        - 为了解决这个问题，扩展处理器的数据结束时间。

    如果处理器的结束时间为None，则不需要更改其结束时间。

    参数：
        task (dict): 任务模板
        rg (RollingGen): RollingGen实例
    """
    try:
        # 计算处理器结束时间与测试分段结束时间之间的间隔
        interval = rolling_gen.ta.cal_interval(
            task["dataset"]["kwargs"]["handler"]["kwargs"]["end_time"],
            task["dataset"]["kwargs"]["segments"][rolling_gen.test_key][1],
        )
        # 如果结束时间 < 测试分段的结束时间，则更改结束时间以允许加载更多数据
        if interval < 0:
            task["dataset"]["kwargs"]["handler"]["kwargs"]["end_time"] = copy.deepcopy(
                task["dataset"]["kwargs"]["segments"][rolling_gen.test_key][1]
            )
    except KeyError:
        # 数据集可能没有处理器，则不执行任何操作
        pass
    except TypeError:
        # 处理器可能是字符串。`"handler.pkl"["kwargs"]`会引发TypeError
        # 例如：像file:///<file>/这样的转储文件
        pass


def trunc_segments(ta: TimeAdjuster, segments: Dict[str, pd.Timestamp], days, test_key="test"):
    """
    为避免未来信息泄露，应根据测试开始时间截断分段

    注意：
        此函数会**原地**更改分段
    """
    # 调整分段
    test_start = min(t for t in segments[test_key] if t is not None)  # 获取测试分段的开始时间
    for k in list(segments.keys()):
        if k != test_key:  # 对非测试分段进行截断
            segments[k] = ta.truncate(segments[k], test_start, days)


class RollingGen(TaskGen):
    """滚动任务生成器，用于生成时间序列滚动训练的任务"""

    ROLL_EX = TimeAdjuster.SHIFT_EX  # 固定开始日期，扩展结束日期
    ROLL_SD = TimeAdjuster.SHIFT_SD  # 固定分段大小，从开始日期滑动

    def __init__(
            self,
            step: int = 40,
            rtype: str = ROLL_EX,
            ds_extra_mod_func: Union[None, Callable] = handler_mod,
            test_key="test",
            train_key="train",
            trunc_days: int = None,
            task_copy_func: Callable = copy.deepcopy,
    ):
        """
        生成滚动任务

        参数
        ----------
        step : int
            滚动步长
        rtype : str
            滚动类型（扩展、滑动）
        ds_extra_mod_func: Callable
            类似handler_mod(task: dict, rg: RollingGen)的方法
            在生成任务后执行一些额外操作。例如，使用``handler_mod``修改数据集处理器的结束时间。
        trunc_days: int
            截断一些数据以避免未来信息泄露
        task_copy_func: Callable
            复制整个任务的函数。当用户希望在任务之间共享某些内容时非常有用[1](@ref)
        """
        self.step = step
        self.rtype = rtype
        self.ds_extra_mod_func = ds_extra_mod_func
        self.ta = TimeAdjuster(future=True)  # 时间调整器，future=True表示处理未来时间

        self.test_key = test_key  # 测试分段键名
        self.train_key = train_key  # 训练分段键名
        self.trunc_days = trunc_days  # 截断天数
        self.task_copy_func = task_copy_func  # 任务复制函数

    def _update_task_segs(self, task, segs):
        """更新任务的分段配置"""
        # 更新此任务的分段
        task["dataset"]["kwargs"]["segments"] = copy.deepcopy(segs)
        if self.ds_extra_mod_func is not None:
            self.ds_extra_mod_func(task, self)  # 执行额外的分段修改

    def gen_following_tasks(self, task: dict, test_end: pd.Timestamp) -> List[dict]:
        """
        为`task`生成后续滚动任务，直到test_end

        参数
        ----------
        task : dict
            Qlib任务格式
        test_end : pd.Timestamp
            最新的滚动任务包含`test_end`

        返回
        -------
        List[dict]:
            `task`的后续任务（不包括`task`本身）
        """
        prev_seg = task["dataset"]["kwargs"]["segments"]  # 上一个分段
        while True:
            segments = {}
            try:
                for k, seg in prev_seg.items():
                    # 决定如何移动
                    # 扩展仅用于训练数据，测试数据和验证数据的分段大小不会改变
                    if k == self.train_key and self.rtype == self.ROLL_EX:
                        rtype = self.ta.SHIFT_EX  # 扩展模式
                    else:
                        rtype = self.ta.SHIFT_SD  # 滑动模式
                    # 移动分段数据
                    segments[k] = self.ta.shift(seg, step=self.step, rtype=rtype)
                if segments[self.test_key][0] > test_end:  # 检查是否超过测试结束时间
                    break
            except KeyError:
                # 到达任务末尾，无法继续滚动
                break

            prev_seg = segments
            t = self.task_copy_func(task)  # 深拷贝避免原地替换任务
            self._update_task_segs(t, segments)
            yield t  # 使用生成器逐个返回任务

    def generate(self, task: dict) -> List[dict]:
        """
        将任务转换为滚动任务。

        参数
        ----------
        task: dict
            描述任务的字典。例如：

            .. code-block:: python

                DEFAULT_TASK = {
                    "model": {
                        "class": "LGBModel",
                        "module_path": "qlib.contrib.model.gbdt",
                    },
                    "dataset": {
                        "class": "DatasetH",
                        "module_path": "qlib.data.dataset",
                        "kwargs": {
                            "handler": {
                                "class": "Alpha158",
                                "module_path": "qlib.contrib.data.handler",
                                "kwargs": {
                                    "start_time": "2008-01-01",
                                    "end_time": "2020-08-01",
                                    "fit_start_time": "2008-01-01",
                                    "fit_end_time": "2014-12-31",
                                    "instruments": "csi100",
                                },
                            },
                            "segments": {
                                "train": ("2008-01-01", "2014-12-31"),
                                "valid": ("2015-01-01", "2016-12-20"),  # 请避免将未来测试数据泄露到验证中
                                "test": ("2017-01-01", "2020-08-01"),
                            },
                        },
                    },
                    "record": [
                        {
                            "class": "SignalRecord",
                            "module_path": "qlib.workflow.record_temp",
                        },
                    ]
                }

        返回
        ----------
        List[dict]: 任务列表
        """
        res = []  # 存储结果任务列表

        t = self.task_copy_func(task)  # 复制原始任务

        # 计算分段

        # 第一次滚动
        # 1) 准备结束点
        segments: dict = copy.deepcopy(self.ta.align_seg(t["dataset"]["kwargs"]["segments"]))
        test_end = transform_end_date(segments[self.test_key][1])  # 转换结束日期格式
        # 2) 初始化测试分段
        test_start_idx = self.ta.align_idx(segments[self.test_key][0])  # 测试开始时间的索引
        # 设置测试分段为从开始索引到开始索引+步长-1
        segments[self.test_key] = (self.ta.get(test_start_idx), self.ta.get(test_start_idx + self.step - 1))
        if self.trunc_days is not None:
            # 截断分段以避免未来信息泄露
            trunc_segments(self.ta, segments, self.trunc_days, self.test_key)

        # 更新此任务的分段
        self._update_task_segs(t, segments)

        res.append(t)  # 添加第一个滚动任务

        # 更新后续滚动
        res.extend(self.gen_following_tasks(t, test_end))
        return res


class MultiHorizonGenBase(TaskGen):
    """多时间范围任务生成器基类，用于生成不同预测周期（horizon）的任务"""

    def __init__(self, horizon: List[int] = [5], label_leak_n=2):
        """
        此任务生成器尝试基于现有任务为不同的时间范围生成任务

        参数
        ----------
        horizon : List[int]
            任务可能的时间范围
        label_leak_n : int
            在进行预测后，需要多少天才能获得完整的标签
            例如：
            - 用户在`T`日进行预测（在获取`T`日收盘价后）
            - 标签是在`T + 1`日买入股票并在`T + 2`日卖出的收益
            - `label_leak_n`将为2（例如，泄露两天的信息以利用此样本）
        """
        self.horizon = list(horizon)  # 时间范围列表
        self.label_leak_n = label_leak_n  # 标签泄露天数
        self.ta = TimeAdjuster()  # 时间调整器
        self.test_key = "test"  # 测试分段键名

    @abc.abstractmethod
    def set_horizon(self, task: dict, hr: int):
        """
        此方法旨在**原地**更改任务（抽象方法）

        参数
        ----------
        task : dict
            Qlib的任务
        hr : int
            任务的时间范围
        """

    def generate(self, task: dict):
        """生成多时间范围的任务"""
        res = []
        for hr in self.horizon:  # 遍历所有时间范围
            # 添加时间范围
            t = copy.deepcopy(task)  # 复制任务
            self.set_horizon(t, hr)  # 设置时间范围

            # 调整分段
            segments = self.ta.align_seg(t["dataset"]["kwargs"]["segments"])
            # 截断分段以避免未来信息泄露
            trunc_segments(self.ta, segments, days=hr + self.label_leak_n, test_key=self.test_key)
            t["dataset"]["kwargs"]["segments"] = segments
            res.append(t)
        return res