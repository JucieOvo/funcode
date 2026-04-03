"""
模块名称：schemas.session
功能描述：
    作为会话状态的兼容导出层，统一从 schemas.core 提供真实模型。

主要组件：
    - SessionState: 会话持久化状态
"""

from funcode.schemas.core import SessionState

__all__ = [
    "SessionState",
]
