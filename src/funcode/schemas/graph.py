"""
模块名称：schemas.graph
功能描述：
    作为图执行状态的兼容导出层，统一从 schemas.core 提供真实模型。

主要组件：
    - GraphState: 图执行状态
"""

from funcode.schemas.core import GraphState

__all__ = [
    "GraphState",
]
