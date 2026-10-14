# 本机 qlib 初始化记录（2026-10-14）

- 日期：2026-10-14
- 机器：当前开发机，Python `D:\anaconda3\envs\vanna312`（3.12）
- 目的：ETF 日线实验要在本机导入 qlib。环境里已有 pandas / numpy / pyarrow，没有 qlib。
- 基准：`requirements.txt` 头注。源码 editable 安装，commit `79633dd9`（v0.9.8.dev32）。不用 PyPI 上的 `pyqlib` 轮子（当时可见 0.9.6 / 0.9.7）。
- 对照：`docs/runbook-newdev-qlib-longwindow-2026-09-13.md` §2 是配方；本页是这次在本机走通的记录，含两处配方里没写的失败。

源码放在仓库外面：`D:\PycharmProjects\qlib-dev`。不要克隆进 MyQuant。

## 结果

| 项 | 值 |
|---|---|
| 导入路径 | `D:\PycharmProjects\qlib-dev\qlib\__init__.py` |
| 版本 | `0.9.8.dev32+g79633dd95` |
| 扩展 | `qlib\data\_libs\rolling.cp312-win_amd64.pyd` |
| 编译器 | VS 2022 Build Tools 17.14.41，MSVC 14.44.35207（`cl` 19.44.35229） |
| Windows SDK | 10.0.26100.0（编译命令的 include 路径） |
| Cython | 3.3.0 |
| 同环境另装 | LightGBM 4.7.0、MLflow 3.17.1。scikit-learn 1.9.0 原本就在 |

验收：

```text
D:\anaconda3\envs\vanna312\python.exe -c "import qlib, qlib.data._libs.rolling as r; print(qlib.__file__); print(qlib.__version__); print(r.__file__)"
```

装完之后普通 shell 就能导入。`vcvars64` 只在编译那一次需要。

## 实际步骤

1. 克隆并钉到基准提交（detached HEAD）：

```text
git clone --filter=blob:none https://github.com/microsoft/qlib.git D:\PycharmProjects\qlib-dev
git -C D:\PycharmProjects\qlib-dev checkout 79633dd9
```

2. 装 C++ 生成工具。本机原来没有 `cl.exe`。

```text
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --accept-package-agreements --accept-source-agreements --disable-interactivity --override "--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

编译器落在 `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe`。

3. 装 Cython，再在开发者环境里做 editable 安装：

```text
D:\anaconda3\envs\vanna312\python.exe -m pip install cython
cmd /c "call ""C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"" && D:\anaconda3\envs\vanna312\python.exe -m pip install -e D:\PycharmProjects\qlib-dev --no-build-isolation"
```

`--no-build-isolation` 是为了用当前环境里的 numpy / Cython，而不是再隔离出一套构建环境。

## 两次失败

1. **没有 MSVC。** 直接 `pip install -e` 停在 `qlib.data._libs.rolling`：`Microsoft Visual C++ 14.0 or greater is required`。装 Build Tools 的 C++ 工作负载后，`cl.exe` 才会出现。
2. **有编译器，没有 Cython。** 源码里只有 `qlib/data/_libs/rolling.pyx` 和 `expanding.pyx`，没有 `.cpp`。第二次编译报 `C1083`，打不开 `qlib/data/_libs/rolling.cpp`。先 `pip install cython`，同一条 editable 安装会先生成 cpp 再编译出 `.pyd`。

## 这次没做的事

- 没有 `pip install pyqlib`。
- 没有把 qlib 源码放进 MyQuant 仓库。
- 没有灌 ETF bin，也没有跑训练。那是 `docs/plan-etf-qlib-daily-2026-10-14.md` 的后续。
