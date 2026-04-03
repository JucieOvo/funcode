"""
模块名称：permissions.validators
功能描述：
    提供真实路径权限校验逻辑，确保工具只能访问被权限上下文明确允许的目录。

主要组件：
    - ensure_tool_path_allowed: 工具路径校验函数

依赖说明：
    - pathlib: 路径处理
    - funcode.permissions.context: 权限上下文
    - funcode.utils.errors: 权限异常

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现路径权限校验
    - 2026-04-01 JucieOvo: 支持上下文内派生允许根目录
"""

from __future__ import annotations

from pathlib import Path

from funcode.permissions.context import PermissionContext
from funcode.utils.errors import PermissionViolationError


def _is_relative_to(path: Path, target: Path) -> bool:
    """
    判断路径是否位于目标目录之下。

    :param path: 待校验路径。
    :param target: 目标目录。
    :return: 是否属于目标目录。
    """

    try:
        path.relative_to(target)
        return True
    except ValueError:
        return False


def ensure_tool_path_allowed(permission_context: PermissionContext, target_path: Path) -> Path:
    """
    校验工具访问路径是否在允许范围内。

    :param permission_context: 权限上下文。
    :param target_path: 目标路径。
    :return: 解析后的绝对路径。
    :raises PermissionViolationError: 当路径越界时触发。
    """

    resolved_target = target_path.resolve()
    allowed_roots = tuple(path.resolve() for path in permission_context.allowed_roots)
    if any(_is_relative_to(resolved_target, root) for root in allowed_roots):
        return resolved_target
    raise PermissionViolationError(f"目标路径不在允许访问范围内：{resolved_target}")
