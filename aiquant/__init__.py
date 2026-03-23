# my_quant_project/__init__.py
import sys
import os


def _setup_qlib_source():
    """
    将本地 Qlib 源码路径插入到 sys.path 最前，确保优先于 pip 安装的版本
    """
    # 获取当前文件所在目录 (my_quant_project/)
    current_package_dir = os.path.dirname(os.path.abspath(__file__))

    # 获取项目根目录（my_quant_project/ 的父目录）
    project_root = os.path.dirname(current_package_dir)

    # Qlib 源码的 Python 包路径（注意：qlib/qlib/ 才是实际的包）
    qlib_source_path = os.path.join(project_root, 'qlib')

    # 关键：插入到 sys.path 的索引 0 位置（最前面）
    if qlib_source_path not in sys.path:
        sys.path.insert(0, qlib_source_path)

    # 可选：打印确认信息（开发时调试用）
    print(f"[DEBUG] Qlib source path added: {qlib_source_path}")


# 模块被导入时立即执行路径配置
_setup_qlib_source()