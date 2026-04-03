"""
模块名称：mcp
功能描述：
    暴露 MCP 注册中心与资源模型的公共接口。
"""

from funcode.mcp.registry import McpRegistry, McpResource

__all__ = [
    "McpRegistry",
    "McpResource",
]
