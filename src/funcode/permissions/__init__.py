"""
模块名称：permissions
功能描述：
    暴露权限上下文与路径校验的公共接口。
"""

from funcode.permissions.context import PermissionContext, create_permission_context
from funcode.permissions.validators import ensure_tool_path_allowed

__all__ = [
    "PermissionContext",
    "create_permission_context",
    "ensure_tool_path_allowed",
]
