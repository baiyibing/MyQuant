QLib 的中国市场数据集是进行量化研究的基础。目前，由于官方数据源策略调整，**微软官方的数据集暂时关闭**，但别担心，社区提供了高质量的替代方案。以下是下载和配置数据的详细指南。

| 特性 | 社区数据 (chenditc/investment_data) | QLib 官方数据 (原来源) |
| :--- | :--- | :--- |
| **数据来源** | Tushare 接口 | Yahoo Finance 等 |
| **数据质量** | 经过清洗和复权处理 | 可能存在缺失 |
| **更新频率** | **每日自动更新** | 已暂停 |
| **适用市场** | 中国 A 股 | 多市场 |
| **获取方式** | 直接下载 Releases 包 | 官方脚本已暂时失效 |

### 📊 数据下载与安装

目前最可靠的方式是下载社区维护的高质量数据集。

1.  **使用 `wget` 命令下载**（最直接稳定）
    在终端中执行以下命令，这将从 GitHub Releases 下载压缩包：
    ```bash
    wget https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz
    ```

2.  **创建 QLib 数据目录**
    QLib 的数据有固定的存放路径，请确保创建该目录：
    ```bash
    mkdir -p ~/.qlib/qlib_data/cn_data
    ```

3.  **解压数据到目标位置**
    使用 `tar` 命令解压，并确保使用 `--strip-components=1` 参数来正确设置目录结构：
    ```bash
    tar -zxvf qlib_bin.tar.gz -C ~/.qlib/qlib_data/cn_data --strip-components=1
    
    tar -zxvf qlib_bin.tar.gz -C C:/Users/Thinkpad/.qlib/qlib_data/cn_data --strip-components=1
    ```

4.  **(可选) 清理压缩包**
    解压完成后，可以删除下载的压缩文件以节省空间：
    ```bash
    rm -f qlib_bin.tar.gz
    ```

### ⚙️ 初始化并验证数据

数据准备好后，你可以在 Python 中初始化 QLib 并验证数据是否成功加载。

```python
import qlib
from qlib.constant import REG_CN

# 初始化 QLib，指定数据路径和区域
provider_uri = "~/.qlib/qlib_data/cn_data"  # 这是默认路径
qlib.init(provider_uri=provider_uri, region=REG_CN)

# 尝试获取数据以验证安装成功
from qlib.data import D
data = D.features(["SH600000"], ["$close"], start_time="2020-01-01", end_time="2020-01-10")
print(data.head())
```

### 💡 注意事项

*   **数据目录结构**：解压时 `--strip-components=1` 参数非常重要，它能确保文件被解压到正确的子目录结构下，否则 QLib 可能无法识别。
*   **权限问题**：确保你的用户账户对 `~/.qlib/qlib_data/cn_data` 目录有读写权限。
*   **磁盘空间**：中国市场数据集通常需要几个GB的磁盘空间，请确保你的硬盘有足够容量。
*   **网络环境**：如果从 GitHub 下载缓慢，可以尝试使用网络代理或寻找国内镜像源。
*   **关于官方脚本**：目前已知运行 `python scripts/get_data.py qlib_data --target_dir ~/.qlib/qlib_data/cn_data --region cn` 会因官方数据源关闭而失败，暂时请以社区数据源为主。

### 🤝 替代方案与社区支持

如果上述方法遇到问题，你还可以考虑以下方式：

*   **Docker 环境**：对于想要避免复杂环境配置的用户，可以使用 QLib 提供的 Docker 镜像，其内可能已包含数据或更易配置。
    ```bash
    docker pull pyqlib/qlib_image_stable:stable
    ```
*   **自定义数据**：如果你有自己的 CSV 格式的股票数据，可以通过 QLib 提供的脚本 `dump_bin.py` 将其转换为 QLib 专用的二进制格式并导入。

---

总的来说，通过社区维护的数据源是目前获取 QLib 中国市场数据最可靠的方法。完成数据加载后，你就可以尽情探索 QLib 在量化研究中的强大功能了。

你在使用 `tar.exe` 时遇到的 `could not chdir to '~/.qlib/qlib_data/cn_data'` 错误，通常是因为 **`tar.exe` 无法切换到指定的目录**。这很可能是因为该目录不存在，或者路径表示方式不正确。

你可以通过以下步骤来排查和解决：

### 🔧 解决方案

1.  **使用绝对路径替代 `~` 扩展**
    *   在大多数 Windows 命令行环境中，`tar.exe` **可能无法正确识别或扩展 `~`（波浪号）** 这个代表用户主目录的特殊字符。
    *   **解决方法**：将 `~` 替换为完整的绝对路径。
    *   例如，如果你的用户名是 `YourUsername`，那么：
        *   **原命令可能类似**：
            ```bash
            tar -zxvf qlib_bin.tar.gz -C ~/.qlib/qlib_data/cn_data --strip-components=1
            ```
        *   **应修改为**：
            ```bash
            tar -zxvf qlib_bin.tar.gz -C C:\Users\YourUsername\.qlib\qlib_data\cn_data --strip-components=1
            ```
    *   **查找你的用户主目录绝对路径**：
        *   在 Windows 文件资源管理器的地址栏直接输入 `%USERPROFILE%` 并按回车，会直接打开你的用户主目录（通常类似于 `C:\Users\YourUsername`），地址栏里显示的就是完整的绝对路径。

2.  **确保目标目录存在**
    *   `tar` 命令的 `-C` 参数要求指定的目录**必须已经存在**，它不会自动创建不存在的目录。
    *   **解决方法**：在解压前，手动创建所有必需的目录层级。
        *   你可以在命令行中使用 `mkdir` 命令创建：
            ```bash
            mkdir C:\Users\YourUsername\.qlib
            mkdir C:\Users\YourUsername\.qlib\qlib_data
            mkdir C:\Users\YourUsername\.qlib\qlib_data\cn_data
            ```
        *   或者在 Windows 文件资源管理器中手动逐级新建文件夹。

3.  **检查路径权限**
    *   尽管可能性相对较低，但仍需确认当前用户对目标路径拥有**写入权限**。
    *   **解决方法**：通常你的用户主目录（`C:\Users\YourUsername`）及其下的文件夹你应该都有写入权限。如果遇到权限问题，可以尝试：
        *   **以管理员身份运行命令行**：右键点击命令提示符或 PowerShell，选择“以管理员身份运行”，然后再执行 `tar` 命令。
        *   **检查文件夹安全属性**：右键点击目标文件夹 -> “属性” -> “安全”选项卡，确认你的用户账户有“写入”权限。

### 💡 操作示例

假设你的 Windows 用户名是 `zhangsan`，`qlib_bin.tar.gz` 文件放在 `D:\Downloads` 下。

1.  **创建目标目录**（如果尚未创建）：
    ```bash
    mkdir C:\Users\zhangsan\.qlib
    mkdir C:\Users\zhangsan\.qlib\qlib_data
    mkdir C:\Users\zhangsan\.qlib\qlib_data\cn_data
    ```

2.  **执行解压命令**（使用绝对路径）：
    ```bash
    tar -zxvf D:\Downloads\qlib_bin.tar.gz -C C:\Users\zhangsan\.qlib\qlib_data\cn_data --strip-components=1
    ```

### ⚠️ 注意事项

*   **路径中的空格**：如果绝对路径中包含空格，**务必使用英文引号将整个路径括起来**，例如：
    ```bash
    -C "C:\Users\zhangsan\My Documents\.qlib\qlib_data\cn_data"
    ```
*   **反斜杠**：在 Windows 命令提示符中，路径通常使用反斜杠 `\`。在 PowerShell 或一些其他环境中，也可能支持使用斜杠 `/`，但使用反斜杠 `\` 是标准做法。
*   **命令顺序**：确保 `-C` 选项和其后的路径参数是紧挨着的。

希望这些步骤能帮你成功解决问题。

看到你在使用 QLib 时遇到了多进程相关的错误。别担心，这个问题在 Windows 系统上比较常见，我们来一步步解决它。

这个错误通常是因为在 Windows 系统上，Python 的多进程模块 `multiprocessing` 在创建子进程时，需要特定的保护机制来避免递归创建进程的问题。

### 🔧 解决方法

#### 1. 检查并修改你的代码结构（主要解决方案）

这是最根本的解决方法。请确保你调用 `qlib.init()` 和执行其他主要逻辑的代码都被包含在 `if __name__ == '__main__':` 语句块中。

```python
import qlib
from qlib.constant import REG_CN
from qlib.data import D
from qlib.utils import init_instance_by_config
from qlib.workflow import R
from qlib.workflow.record_temp import SignalRecord, PortAnaRecord
import pandas as pd

# 你的其他函数和类定义，例如：
# def my_function():
#     ...
# class MyModel:
#     ...

if __name__ == '__main__':  # 确保主要代码在这个保护块内
    # 配置 QLib 初始化参数，包括 Redis 密码（如果需要）
    redis_config = {
        "host": "localhost",
        "port": 6379,
        "password": "your_password_here",  # 如果你的 Redis 有密码
        "db": 1,
    }
    
    # 初始化 QLib
    provider_uri = "~/.qlib/qlib_data/cn_data"  # 根据你的数据路径修改
    qlib.init(provider_uri=provider_uri, region=REG_CN, redis=redis_config)
    
    # 你原来的后续代码，例如：
    # instruments = [...]  
    # fields = [...]  
    # start_time = ...  
    # end_time = ...  
    # features = D.features(instruments, fields, start_time, end_time)
    # ...（其他操作）
```

**关键点**：
*   **`if __name__ == '__main__':`** 这个保护块是必须的。在 Windows 上，Python 使用 `spawn` 方式创建新进程，每个新进程都会重新导入主模块。如果没有这个保护，创建进程的代码又会被执行，导致无限递归地创建进程，从而引发你看到的错误。
*   将所有**可能触发多进程操作**的代码（包括 `qlib.init()` 以及后续的数据处理、模型训练等）都放在这个保护块内。

#### 2. 使用 `freeze_support()`（可选，但在打包或有复杂多进程时建议）

如果你的程序可能会被打包（如使用 PyInstaller），或者多进程逻辑比较复杂，可以在 `if __name__ == '__main__':` 块内的最开头添加 `multiprocessing.freeze_support()`。

```python
import multiprocessing
import qlib
# ... 导入其他需要的模块

if __name__ == '__main__':
    multiprocessing.freeze_support()  # 添加这一行，特别是在 Windows 上打包时可能有帮助
    # 你原有的 QLib 初始化和操作代码
    # ...
```

#### 3. 临时禁用多进程处理（权宜之计）

如果问题出在 QLib 内部调用多进程读取或处理数据（从你的错误堆栈看，是在 `D.features` 时触发的），你可以尝试通过设置 `workers` 参数为 0 来**临时禁用并行处理**，以验证是否是核心问题。

```python
# 在你的代码中，如果有指定 workers 数的地方，尝试将其设为 0
# 例如，如果你是自己调用了某些可以指定 workers 的 QLib 函数
data = some_qlib_function(..., workers=0)  # 禁用多进程，使用单进程
```

或者，检查 QLib 的全局配置，看是否有设置默认工作进程数的地方并将其暂时设为 0。**这只是为了快速验证和临时绕过问题，并非长远解决方案。**

### 💡 为什么会出现这个错误？

这个错误的核心原因在于 Windows 和 Linux/macOS 在创建新进程机制上的不同：
*   **Linux/macOS** 默认使用 `fork`：子进程会继承父进程的所有内存状态。
*   **Windows** 默认使用 `spawn`：子进程会**重新启动一个新的 Python 解释器并重新导入主模块**。
如果没有 `if __name__ == '__main__':` 这个保护，在子进程中导入主模块时，又会执行创建子进程的代码，从而导致无限循环。 QLib 内部可能使用了 `joblib` 或 `multiprocessing` 库进行并行计算，从而触发了这个问题。

### 📝 总结与建议

1.  **立即尝试**：将你的代码**主要执行逻辑**（特别是调用 `qlib.init()` 和后续操作的代码）放入 `if __name__ == '__main__':` 块中。这是解决此问题的最可能有效的方法。
2.  **检查脚本结构**：确保你没有在模块的全局作用域（即所有函数和类定义之外）直接调用任何可能触发多进程操作的函数。
3.  **如果问题依旧**：检查你是否在复杂的多线程环境中调用 QLib，或者尝试暂时禁用 QLib 内部的并行处理（如果配置允许）来定位问题。

QLib 是一个强大的工具，但在 Windows 上配置多进程时确实需要额外注意这一点。希望这些方法能帮助你解决问题。如果尝试后仍有疑问，欢迎继续提出。

Qlib 作为微软开源的专业量化投资平台，学习时选择**结构清晰、贴近实战**的教程确实很重要。下面我为你梳理了几个较新且质量较高的中文教程，并用一个表格汇总它们的主要特点，方便你快速了解：

| 教程名称                                       | 发布年份 | 主要特点与内容                                                                 | 形式           | 链接与来源                                       |
| :--------------------------------------------- | :------- | :----------------------------------------------------------------------------- | :------------- | :----------------------------------------------- |
| **扫地僧AI量化平台Qlib给力教程系列一：核心篇** | 2025     | 基于Qlib 2025版，支持Python 3.12。**从安装、数据准备、自定义因子、模型训练（含数十个模型案例）到回测分析**，涵盖核心使用场景。特别讲解了`Infer processor`和`Learn processor`的区别、自定义股票池、策略回测成交细节等**深度内容**。 | **视频课程**   | https://www.bilibili.com/opus/1071833827785048070 |
| **QuantML-Qlib/Qlib 教程及常见问题**           | 2024     | **解答Qlib使用中的高频问题**，涵盖**安装指南**、数据源获取（提供了当前可用的社区数据下载链接）、数据导入（包括直接读取多种数据库）、运行排错等。**实践性很强**，适合边做边查。 | 图文专栏       | http://mp.weixin.qq.com/s?__biz=Mzg2MzAwNzM0NQ==&mid=2247485579&idx=1&sn=2a1609fddd5f18ac770266da91048667&chksm=cfc62db26c4819c28083da6f1875d3b328d8a40be6fb385b01438e0490f9b9446b6d7448e91a#rd |
| **微软Qlib项目入门教学**                      | 2025     | **清晰介绍Qlib核心功能**，并提供了**加密货币数据适配**的示例代码。内容从简介、安装、数据准备（含自定义数据处理脚本）到模型训练和回测，**适合初学者建立完整概念**。 | 图文专栏       | http://mp.weixin.qq.com/s?__biz=MzkyODU4ODEyOA==&mid=2247483933&idx=1&sn=15d540a49260f32009b92315ef909930&chksm=c3cab963512977f47ea7a1c8b522b8143d68e0d7f5d9b5b54c32611de16f1124f1307140a27e#rd |
| **Qlib使用强化学习**                          | 2025     | **详细讲解如何在Qlib中使用强化学习 (RL) 框架**，包括环境配置、策略定义、训练循环和回测评估。包含完整的代码示例和配置说明，**适合对RL在量化交易中应用感兴趣的学习者**。 | CSDN博客       | https://blog.csdn.net/longma666666/article/details/149270182 |
| **Qlib实战案例：从研究到生产**                | 2025     | **以沪深300指数(CSI300)策略为例**，展示从**多因子模型构建、风险控制、资金管理到实盘交易系统集成**的完整流程。包含丰富的代码示例和架构设计，**侧重从理论到实践的完整闭环**。 | CSDN博客       | https://blog.csdn.net/gitblog_00086/article/details/150632952 |

💡 **学习建议**

*   **新手入门**：建议从 **微软Qlib项目入门教学** 开始，建立整体概念，然后跟随 **扫地僧教程** 系统学习核心功能。
*   **遇到问题**：**QuantML-Qlib的常见问题汇总** 是你的好帮手。
*   **深化特定领域**：如果你想探索**强化学习** 或学习**如何构建完整的实战策略**，可以对应选择专项教程。
*   **官方文档**：所有这些教程都建议你**结合Qlib官方文档**（尤其是最新的英文文档）一起学习，因为开源项目更新较快，文档通常最准确。
*   **实践是关键**：**亲自动手操作、复现教程中的例子、尝试根据自己的想法修改代码**，是学习Qlib最有效的方式。

希望这些信息能帮助你快速找到适合自己的Qlib学习路径。




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

根据您提供的错误信息，这是一个涉及内存管理、多进程调试和第三方库兼容性的复杂问题。错误主要出现在PyCharm调试器与qlib库（以及其依赖的joblib、loky等多进程组件）交互时。以下是系统性的解决方案：

## 问题根源分析

您遇到的`BufferError: memoryview has 1 exported buffer`和`BrokenPipeError`通常源于以下几点：
- PyCharm调试器与Python多进程模块的兼容性问题
- 内存视图对象在进程间通信时被不当清理
- 调试器干扰了正常的多进程资源管理

## 解决方案

### 1. 启用Gevent兼容模式
这是解决PyCharm调试器与多进程库兼容性的首要方案：
- 打开PyCharm设置 → Build, Execution, Deployment → Python Debugger
- 勾选"Gevent compatible"选项
- 此设置让调试器使用与协程/多进程更兼容的调试模式

### 2. 调整Python解释器版本
如果使用Python 3.11+版本，建议降级到更稳定的版本：
- 安装Python 3.8或3.9（这些版本与多数科学计算库兼容性更好）
- 在PyCharm中切换解释器：File → Settings → Project → Python Interpreter
- 重新创建虚拟环境并安装依赖

### 3. 配置调试器避免多进程干扰
```python
# 在代码开头添加环境变量设置，避免调试器hook子进程
import os
os.environ["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"
os.environ["JOBLIB_MULTIPROCESSING"] = "0"

# 对于qlib特定配置
if __name__ == "__main__":
    # 确保多进程代码在if __name__ == "__main__"保护下
    your_qlib_code()
```

### 4. 修改PyCharm调试配置
- 打开Run/Debug Configurations
- 在"Execution"部分，取消勾选"Gevent compatible"（如果已尝试无效）
- 或尝试勾选"Emulate terminal in output console"
- 增加环境变量：`PYTHONFAULTHANDLER=1` 用于更详细的错误信息

### 5. 针对qlib和joblib的特定设置
```python
import joblib
from joblib import parallel_backend

# 设置joblib使用sequential模式避免多进程问题
with parallel_backend('sequential'):
    # 你的qlib代码
    pass

# 或者通过环境变量限制进程数
import os
os.environ["LOKY_MAX_CPU_COUNT"] = "1"
os.environ["JOBLIB_START_METHOD"] = "forkserver"
```

### 6. 清理和重建项目环境
- 清除PyCharm缓存：File → Invalidate Caches / Restart
- 删除并重新创建虚拟环境
- 重新安装qlib和相关依赖，确保版本兼容性

### 7. 替代调试方案
如果上述方法仍无效，可以考虑：
- 使用非调试模式运行定位问题大致范围
- 在代码中添加详细日志输出替代调试器
- 对疑似问题模块编写最小复现案例进行隔离调试

## 预防措施

1. **代码结构优化**：确保所有多进程代码都在`if __name__ == "__main__":`保护下
2. **资源管理**：显式关闭和清理内存视图、文件句柄等资源
3. **版本控制**：保持qlib、joblib、numpy等科学计算库版本的兼容性

建议按顺序尝试以上方案，从方案1和2开始通常能解决大部分类似问题。如果问题持续存在，可能需要检查qlib特定版本的多进程实现方式。