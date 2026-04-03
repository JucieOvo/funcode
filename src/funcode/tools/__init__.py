"""
模块名称：tools
功能描述：
    提供 Python 版 Funcode 的工具层惰性导出入口。
    该包只暴露必要的公共类型与默认注册表构建函数，避免在导入
    任意子模块时提前加载完整工具实现并触发循环导入。
主要组件：
    - ToolExecutionContext: 工具执行上下文。
    - create_default_tool_registry: 默认工具注册表构建函数。
依赖说明：
    - funcode.tools.context: 工具执行上下文。
    - funcode.tools.registry: 默认工具注册表。
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 改为惰性导出，避免工具包初始化时提前加载完整注册表。
"""

from __future__ import annotations

from funcode.tools.context import ToolExecutionContext


def create_default_tool_registry():
    """
    构建默认工具注册表。

    该函数采用惰性导入，避免在导入 tools 包时提前加载完整工具实现。
    """

    from funcode.tools.registry import create_default_tool_registry as _create_default_tool_registry

    return _create_default_tool_registry()


__all__ = [
    "ToolExecutionContext",
    "create_default_tool_registry",
]
