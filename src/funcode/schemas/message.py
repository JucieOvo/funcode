"""
模块名称：schemas.message
功能描述：
    作为消息与工具调用记录的兼容导出层，统一从 schemas.core 提供真实模型。

主要组件：
    - MessageRecord: 消息记录
    - ToolCallRecord: 工具调用记录
"""

from funcode.schemas.core import MessageRecord, ToolCallRecord

__all__ = [
    "MessageRecord",
    "ToolCallRecord",
]
