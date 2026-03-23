# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""
任务管理的一些工具函数和类。
"""
import bisect  # 二分查找模块，用于在有序列表中快速定位元素
from copy import deepcopy  # 深拷贝工具，用于完全复制对象
import pandas as pd  # 数据处理库
from qlib.data import D  # Qlib 数据层接口
from qlib.utils import hash_args  # 生成参数哈希值的工具
from qlib.utils.mod import init_instance_by_config  # 根据配置初始化实例
from qlib.workflow import R  # Qlib 工作流管理模块
from qlib.config import C  # Qlib 配置管理
from qlib.log import get_module_logger  # 日志模块
from pymongo import MongoClient  # MongoDB 客户端
from pymongo.database import Database  # MongoDB 数据库接口
from typing import Union  # 类型注解支持
from pathlib import Path  # 路径操作工具


def get_mongodb() -> Database:
    """
    获取 MongoDB 数据库实例。使用前需先通过 qlib.init() 配置数据库地址和名称。

    配置示例：
        mongo_conf = {
            "task_url": "mongodb://localhost:27017/",  # MongoDB 连接地址
            "task_db_name": "rolling_db"  # 数据库名称
        }
        qlib.init(mongo=mongo_conf)

    返回:
        Database: MongoDB 数据库实例[2](@ref)

    异常:
        KeyError: 当未配置 `C['mongo']` 时抛出
    """
    try:
        cfg = C["mongo"]  # 从全局配置中获取 MongoDB 设置
    except KeyError:
        # 记录错误日志并抛出异常
        get_module_logger("task").error("Please configure `C['mongo']` before using TaskManager")
        raise
    get_module_logger("task").info(f"mongo config:{cfg}")  # 记录配置信息
    client = MongoClient(cfg["task_url"])  # 创建 MongoDB 客户端连接
    return client.get_database(name=cfg["task_db_name"])  # 返回指定名称的数据库


def list_recorders(experiment, rec_filter_func=None):
    """
    列出实验中通过筛选条件的所有记录器（Recorder）。

    参数:
        experiment (str 或 Experiment): 实验名称或实验实例
        rec_filter_func (Callable, 可选): 筛选函数，返回 True 则保留记录器

    返回:
        dict: 经过筛选的记录器字典 {记录器ID: 记录器实例}[5](@ref)

    示例:
        >>> recs = list_recorders("workflow", lambda rec: rec.metrics.get("IC") > 0.1)
        >>> # 返回 IC 大于 0.1 的所有记录器
    """
    if isinstance(experiment, str):
        experiment = R.get_exp(experiment_name=experiment)  # 根据实验名称获取实验对象
    recs = experiment.list_recorders()  # 获取实验中的所有记录器
    recs_flt = {}  # 初始化空字典存储筛选后的记录器
    for rid, rec in recs.items():  # 遍历所有记录器
        if rec_filter_func is None or rec_filter_func(rec):  # 如果无筛选函数或函数返回 True
            recs_flt[rid] = rec  # 将记录器添加到结果字典
    return recs_flt  # 返回筛选后的记录器字典


class TimeAdjuster:
    """
    在交易日历中查找适当日期并调整日期的工具类，主要用于处理时间分段的对齐、截断和移动操作[2,5](@ref)。
    """

    def __init__(self, future=True, end_time=None):
        """
        初始化时间调整器。

        参数:
            future (bool): 是否包含未来日期（True 用于回测，False 用于实时交易）
            end_time: 日历的结束时间，None 表示使用默认结束时间
        """
        self._future = future  # 存储未来日期标志
        self.cals = D.calendar(future=future, end_time=end_time)  # 从 Qlib 数据层获取交易日历

    def set_end_time(self, end_time=None):
        """
        设置日历的结束时间。

        参数:
            end_time: 结束时间，None 表示使用日历的默认结束时间
        """
        self.cals = D.calendar(future=self._future, end_time=end_time)  # 重新生成交易日历

    def get(self, idx: int):
        """
        通过索引获取对应的交易日期。

        参数:
            idx (int): 交易日历中的索引位置

        返回:
            pd.Timestamp 或 None: 对应索引的日期，索引越界时返回 None
        """
        if idx is None or idx >= len(self.cals):  # 检查索引有效性
            return None
        return self.cals[idx]  # 返回指定索引的日期

    def max(self) -> pd.Timestamp:
        """
        返回交易日历中的最晚日期。

        返回:
            pd.Timestamp: 最晚的交易日期
        """
        return max(self.cals)  # 返回日历中的最大值

    def align_idx(self, time_point, tp_type="start") -> int:
        """
        将时间点对齐到交易日历中的索引位置。

        参数:
            time_point: 需要对齐的时间点
            tp_type (str): 对齐类型（"start"：大于等于给定时间的第一个交易日；"end"：小于等于给定时间的最后一个交易日）

        返回:
            int: 在交易日历中的索引位置

        异常:
            NotImplementedError: 当 tp_type 不支持时抛出
        """
        if time_point is None:  # 处理无边界情况
            return None
        time_point = pd.Timestamp(time_point)  # 转换为时间戳格式
        if tp_type == "start":
            idx = bisect.bisect_left(self.cals, time_point)  # 二分查找左边界
        elif tp_type == "end":
            idx = bisect.bisect_right(self.cals, time_point) - 1  # 二分查找右边界并调整
        else:
            raise NotImplementedError(f"This type of input is not supported")
        return idx  # 返回对齐后的索引

    def cal_interval(self, time_point_A, time_point_B) -> int:
        """
        计算两个时间点之间的交易天数间隔（time_point_A - time_point_B）。

        参数:
            time_point_A: 较晚的时间点
            time_point_B: 较早的时间点

        返回:
            int: 间隔的交易天数
        """
        return self.align_idx(time_point_A) - self.align_idx(time_point_B)  # 通过索引差计算间隔

    def align_time(self, time_point, tp_type="start") -> pd.Timestamp:
        """
        将时间点对齐到最近的交易日期。

        参数:
            time_point: 需要对齐的时间点
            tp_type (str): 对齐类型（"start" 或 "end"）

        返回:
            pd.Timestamp: 对齐后的交易日期
        """
        if time_point is None:
            return None
        return self.cals[self.align_idx(time_point, tp_type=tp_type)]  # 先对齐索引再获取日期

    def align_seg(self, segment: Union[dict, tuple]) -> Union[dict, tuple]:
        """
        将时间分段对齐到实际的交易日期。

        示例:
            输入: {'train': ('2008-01-01', '2014-12-31'), 'test': ('2017-01-01', '2020-08-01')}
            输出: {'train': (Timestamp('2008-01-02'), Timestamp('2014-12-31')), ...}

        参数:
            segment: 时间分段（字典或元组）

        返回:
            Union[dict, tuple]: 对齐后的交易日期分段

        异常:
            NotImplementedError: 当输入类型不支持时抛出
        """
        if isinstance(segment, dict):  # 处理字典类型（多分段）
            return {k: self.align_seg(seg) for k, seg in segment.items()}  # 递归处理每个分段
        elif isinstance(segment, (tuple, list)):  # 处理元组或列表（单分段）
            return self.align_time(segment[0], tp_type="start"), self.align_time(segment[1], tp_type="end")
        else:
            raise NotImplementedError(f"This type of input is not supported")

    def truncate(self, segment: tuple, test_start, days: int) -> tuple:
        """
        基于测试开始日期截断时间分段，避免未来信息泄露[5](@ref)。

        参数:
            segment (tuple): 时间分段（开始时间，结束时间）
            test_start: 测试开始时间，作为截断基准
            days (int): 需要截断的交易天数（包含标签计算所需历史天数和预测周期）

        返回:
            tuple: 截断后的新时间分段

        异常:
            AssertionError: 当计算出的索引非正数时抛出
            NotImplementedError: 当输入类型不支持时抛出
        """
        test_idx = self.align_idx(test_start)  # 将测试开始时间转换为索引
        if isinstance(segment, tuple):
            new_seg = []  # 存储新时间分段的列表
            for time_point in segment:  # 处理分段中的每个时间点
                # 计算截断位置，确保不超过 test_idx - days
                tp_idx = min(self.align_idx(time_point), test_idx - days)
                # 调试信息（实际使用时可能需注释掉）
                print(f"tp_idx: {tp_idx}, segments: {segment}, test_start: {test_start}")
                assert tp_idx > 0, f"tp_idx must be positive, but got {tp_idx}"  # 验证索引有效性
                new_seg.append(self.get(tp_idx))  # 获取截断后的日期并添加到新分段
            return tuple(new_seg)  # 返回元组形式的新分段
        else:
            raise NotImplementedError(f"This type of input is not supported")

    SHIFT_SD = "sliding"  # 滑动窗口模式常量
    SHIFT_EX = "expanding"  # 扩展窗口模式常量

    def _add_step(self, index, step):
        """辅助方法：为索引增加步长（处理 None 值）"""
        if index is None:
            return None
        return index + step

    def shift(self, seg: tuple, step: int, rtype=SHIFT_SD) -> tuple:
        """
        移动时间分段（滚动窗口操作）。

        参数:
            seg (tuple): 时间分段（开始时间，结束时间）
            step (int): 滚动步长（交易天数）
            rtype (str): 滚动类型（"sliding"：滑动窗口；"expanding"：扩展窗口）

        返回:
            tuple: 移动后的新时间分段

        异常:
            KeyError: 当索引超出日历范围时抛出
            NotImplementedError: 当输入类型或滚动类型不支持时抛出
        """
        if isinstance(seg, tuple):
            # 获取开始和结束时间的索引
            start_idx, end_idx = self.align_idx(seg[0], tp_type="start"), self.align_idx(seg[1], tp_type="end")
            if rtype == self.SHIFT_SD:  # 滑动窗口：开始和结束时间同时移动
                start_idx = self._add_step(start_idx, step)
                end_idx = self._add_step(end_idx, step)
            elif rtype == self.SHIFT_EX:  # 扩展窗口：仅结束时间移动
                end_idx = self._add_step(end_idx, step)
            else:
                raise NotImplementedError(f"This type of input is not supported")
            if start_idx is not None and start_idx > len(self.cals):  # 检查索引越界
                raise KeyError("The segment is out of valid calendar")
            return self.get(start_idx), self.get(end_idx)  # 返回移动后的新分段
        else:
            raise NotImplementedError(f"This type of input is not supported")


def replace_task_handler_with_cache(task: dict, cache_dir: Union[str, Path] = ".") -> dict:
    """
    将任务中的处理器（handler）替换为缓存处理器，避免重复计算。

    参数:
        task (dict): Qlib 任务配置字典
        cache_dir (str 或 Path): 缓存文件存储目录

    返回:
        dict: 修改后的任务配置[5](@ref)

    示例:
        >>> task = {
        ...     "dataset": {
        ...         "kwargs": {
        ...             "handler": {
        ...                 "class": "Alpha158",
        ...                 "module_path": "qlib.contrib.data.handler",
        ...                 "kwargs": {"start_time": "2008-01-01", "end_time": "2020-08-01"}
        ...             }
        ...         }
        ...     }
        ... }
        >>> new_task = replace_task_handler_with_cache(task)
        >>> # 处理器将被替换为缓存文件路径，如 "file:///path/to/Alpha158.abc123.pkl"
    """
    cache_dir = Path(cache_dir)  # 确保缓存目录为 Path 对象
    task = deepcopy(task)  # 深拷贝任务配置避免修改原数据
    handler = task["dataset"]["kwargs"]["handler"]  # 获取处理器配置
    if isinstance(handler, dict):  # 仅当处理器为字典配置时处理
        hash = hash_args(handler)  # 生成配置的哈希值作为缓存标识
        h_path = cache_dir / f"{handler['class']}.{hash[:10]}.pkl"  # 构建缓存文件路径
        if not h_path.exists():  # 如果缓存文件不存在
            h = init_instance_by_config(handler)  # 根据配置初始化处理器实例
            h.to_pickle(h_path, dump_all=True)  # 将处理器序列化保存到缓存文件
        task["dataset"]["kwargs"]["handler"] = f"file://{h_path}"  # 替换为缓存文件路径
    return task  # 返回修改后的任务配置