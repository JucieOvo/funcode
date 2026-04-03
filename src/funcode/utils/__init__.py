"""
模块名称：utils
功能描述：
    提供 Python 版 Funcode 在 graph、tools、permissions、mcp 等子系统之间
    共用的通用工具函数与异常类型。

主要组件：
    - FuncodeError: 顶层业务异常基类。
    - ensure_directory: 目录存在性保障函数。
    - run_powershell_command: PowerShell 命令执行函数。

依赖说明：
    - funcode.config.settings: 运行配置对象。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 utils 子系统导出。
"""

from funcode.utils.errors import FuncodeError, ConfigurationMissingError, ToolExecutionError
from funcode.utils.fs import ensure_directory, normalize_workspace_path, read_text_file
from funcode.utils.powershell import run_powershell_command

__all__ = [
    "FuncodeError",
    "ConfigurationMissingError",
    "ToolExecutionError",
    "ensure_directory",
    "normalize_workspace_path",
    "read_text_file",
    "run_powershell_command",
]
