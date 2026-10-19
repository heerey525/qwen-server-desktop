"""qwen-desktop 核心层。

把 ~/.local/bin/qwen-server 脚本的行为封装成可编程的模块：
模型扫描、参数构建、进程管理、日志采集。

设计约束：仅使用 Python 标准库，保证打包后零依赖可独立运行。
"""

__version__ = "1.0.0"
__all__ = ["paths", "models", "config", "server"]
