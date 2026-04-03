"""
模块名称：session
功能描述：
    提供会话存储与会话管理对象的惰性导出入口。
    该包不会在初始化时主动加载管理器和仓储实现，避免循环导入。
主要组件：
    - SessionManager: 会话管理器。
    - SessionRepository: 会话仓储。
    - SessionState: 会话状态模型。
依赖说明：
    - funcode.session.manager: 会话管理器。
    - funcode.session.repository: 会话仓储。
    - funcode.schemas.core: 会话状态模型。
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 改为惰性导出，避免包初始化时提前加载会话实现。
"""

from __future__ import annotations

from typing import Any

_EXPORT_MAP = {
    "SessionManager": ("funcode.session.manager", "SessionManager"),
    "SessionRepository": ("funcode.session.repository", "SessionRepository"),
    "SessionState": ("funcode.schemas.core", "SessionState"),
}


def __getattr__(name: str) -> Any:
    """
    按需导入并返回导出的会话符号。
    """

    if name not in _EXPORT_MAP:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _EXPORT_MAP[name]
    module = __import__(module_name, fromlist=[attribute_name])
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """
    返回当前包可见的导出符号。
    """

    return sorted(list(globals().keys()) + list(_EXPORT_MAP.keys()))


__all__ = list(_EXPORT_MAP.keys())
