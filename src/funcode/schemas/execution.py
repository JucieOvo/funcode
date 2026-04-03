"""
模块名称：schemas.execution
功能描述：
    作为执行请求与执行结果的兼容导出层，统一从 schemas.core 提供真实模型。

主要组件：
    - ExecutionRequest: 执行请求
    - ExecutionResult: 执行结果
"""

from funcode.schemas.core import ExecutionRequest, ExecutionResult

__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
]
