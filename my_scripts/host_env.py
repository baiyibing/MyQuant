# -*- coding: utf-8 -*-
"""共享宿主环境变量（单一来源）。

所有触碰 qlib / mlflow 工作流的入口在 **任何 qlib import 之前**
``import host_env``，避免每个脚本各自一份 setdefault 逃生口。

setdefault：已有环境变量不被覆盖。
"""

from __future__ import annotations

import os

# 本机新版 mlflow 将 file store(./mlruns) 置于 maintenance mode；
# 历史实验在 my_scripts/mlruns，继续走 file store（mlflow 官方逃生口）。
os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
# 静音 mlflow agent 提示刷屏（幂等）。
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
