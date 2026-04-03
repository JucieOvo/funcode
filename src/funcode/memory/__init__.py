"""
模块名称：memory
功能描述：
    汇总会话记忆相关能力，暴露记忆快照、注入器以及便捷函数。

主要组件：
    - ConversationMemorySnapshot: 会话记忆快照
    - MemoryInjector: 会话记忆注入器
    - build_memory_snapshot: 构造记忆快照
    - extract_recent_messages: 提取最近消息
    - extract_summary_text: 提取摘要文本
    - inject_memory_context: 注入记忆上下文

依赖说明：
    - funcode.memory.injector: 记忆核心实现

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现记忆包导出。
"""

from __future__ import annotations

from .injector import (
    ConversationMemorySnapshot,
    MemoryInjector,
    build_memory_snapshot,
    extract_recent_messages,
    extract_summary_text,
    inject_memory_context,
)

__all__ = [
    "ConversationMemorySnapshot",
    "MemoryInjector",
    "build_memory_snapshot",
    "extract_recent_messages",
    "extract_summary_text",
    "inject_memory_context",
]
