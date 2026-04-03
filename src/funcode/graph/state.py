"""
模块名称：state
功能描述：
    作为 graph 子系统的兼容导出层，统一从 schemas 中暴露图状态与工具调用记录，避免 graph
    目录重复维护独立的数据结构定义。

主要组件：
    - GraphState: 图执行状态模型。
    - ToolCall: 工具调用记录模型兼容别名。

依赖说明：
    - funcode.schemas.graph: 统一图状态模型。
    - funcode.schemas.message: 统一工具调用模型。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 切换为统一 schemas 导出。
"""

from funcode.schemas.core import GraphState
from funcode.schemas.core import ToolCallRecord as ToolCall

__all__ = ["GraphState", "ToolCall"]
