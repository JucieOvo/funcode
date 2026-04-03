"""
模块名称：memory.injector
功能描述：
    提供会话记忆注入能力，负责从消息列表中提取最近消息、摘要文本，
    并将记忆摘要以可复用的系统消息形式注入到后续上下文中。

主要组件：
    - ConversationMemorySnapshot: 会话记忆快照
    - MemoryInjector: 记忆提取与注入器
    - extract_recent_messages: 提取最近消息
    - extract_summary_text: 提取摘要文本
    - inject_memory_context: 注入记忆上下文

依赖说明：
    - dataclasses: 用于结构化数据容器
    - typing: 用于类型注解

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现会话记忆注入器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MessageMapping = Mapping[str, Any]
MessageInput = Mapping[str, Any] | Any

_SUMMARY_ROLES = {"system", "developer"}
_SUMMARY_TYPES = {"summary", "memory_summary", "compact_summary"}
_RECENT_MESSAGE_DEFAULT_LIMIT = 24


def _coerce_message(message: MessageInput) -> dict[str, Any]:
    """
    将任意消息对象规范化为字典，保证后续处理逻辑可统一工作。

    :param message: 原始消息对象，可以是字典、Pydantic 对象或任意带属性对象
    :return: 规范化后的消息字典
    :raises TypeError: 当消息无法转换为字典时抛出
    """

    if isinstance(message, Mapping):
        return dict(message)

    if hasattr(message, "model_dump") and callable(getattr(message, "model_dump")):
        return dict(message.model_dump(mode="python"))

    if hasattr(message, "__dict__"):
        payload = {
            key: value
            for key, value in vars(message).items()
            if not key.startswith("_")
        }
        if payload:
            return payload

    raise TypeError(f"无法将消息对象转换为字典：{type(message)!r}")


def _normalize_content(content: Any) -> str:
    """
    将消息内容统一转换为字符串，支持字符串、块列表与其他结构。

    :param content: 消息内容
    :return: 统一后的文本
    """

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                for candidate_key in ("text", "content", "value"):
                    candidate_value = item.get(candidate_key)
                    if candidate_value:
                        parts.append(str(candidate_value))
                        break
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _message_role(message: Mapping[str, Any]) -> str:
    """
    提取消息角色，并做统一归一化。

    :param message: 消息字典
    :return: 标准化后的角色名
    """

    role = message.get("role") or message.get("author") or message.get("speaker") or "unknown"
    return str(role).strip().lower() or "unknown"


def _message_type(message: Mapping[str, Any]) -> str:
    """
    提取消息类型字段，用于识别摘要类消息。

    :param message: 消息字典
    :return: 标准化后的消息类型
    """

    raw_type = message.get("type") or message.get("message_type") or ""
    return str(raw_type).strip().lower()


def _count_message_statistics(messages: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    """
    统计消息列表中真实出现的角色与类型分布。

    :param messages: 已规范化的消息序列。
    :return: 角色统计与类型统计两个字典。
    """

    role_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    for message in messages:
        role = _message_role(message)
        message_type = _message_type(message)
        role_counts[role] = role_counts.get(role, 0) + 1
        if message_type:
            type_counts[message_type] = type_counts.get(message_type, 0) + 1
    return role_counts, type_counts


def extract_summary_text(messages: Sequence[MessageInput]) -> str:
    """
    从消息列表中提取摘要文本。

    规则：
    1. 优先提取显式摘要类消息中的文本。
    2. 其次提取带有 summary 字段的消息。
    3. 再其次提取系统/开发者消息中标记为摘要的内容。

    :param messages: 原始消息序列
    :return: 摘要文本，可能为空字符串
    """

    summary_fragments: list[str] = []
    for raw_message in messages:
        message = _coerce_message(raw_message)
        message_type = _message_type(message)
        role = _message_role(message)
        content_text = _normalize_content(message.get("content"))

        if message_type in _SUMMARY_TYPES:
            if content_text:
                summary_fragments.append(content_text)
            continue

        summary_field = message.get("summary") or message.get("summary_text")
        if summary_field:
            summary_fragments.append(_normalize_content(summary_field))
            continue

        if role in _SUMMARY_ROLES and content_text and (
            "summary" in message
            or "摘要" in content_text
            or "总结" in content_text
            or "memory" in message_type
        ):
            summary_fragments.append(content_text)

    return "\n".join(fragment for fragment in summary_fragments if fragment).strip()


def extract_recent_messages(
    messages: Sequence[MessageInput],
    recent_limit: int = _RECENT_MESSAGE_DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    提取最近若干条消息。

    该函数保持原始顺序，只保留末尾的窗口内容。

    :param messages: 原始消息序列
    :param recent_limit: 要保留的最近消息条数
    :return: 最近消息列表
    :raises ValueError: 当 recent_limit 小于 1 时抛出
    """

    if recent_limit < 1:
        raise ValueError("recent_limit 必须大于等于 1")

    normalized_messages = [_coerce_message(item) for item in messages]
    if len(normalized_messages) <= recent_limit:
        return normalized_messages
    return normalized_messages[-recent_limit:]


def _build_summary_message(summary_text: str, recent_count: int, total_count: int) -> dict[str, Any]:
    """
    构造可注入到后续上下文中的摘要消息。

    :param summary_text: 摘要文本
    :param recent_count: 最近消息条数
    :param total_count: 原始消息总数
    :return: 系统摘要消息
    """

    summary_body = summary_text.strip()
    if not summary_body:
        summary_body = "无可用摘要文本。"

    return {
        "role": "system",
        "type": "memory_summary",
        "name": "conversation_memory",
        "content": (
            "以下内容是为后续推理保留的会话摘要，"
            f"原始消息总数：{total_count}，保留最近消息数：{recent_count}。\n"
            f"{summary_body}"
        ),
    }


@dataclass(slots=True)
class ConversationMemorySnapshot:
    """
    会话记忆快照。

    属性：
        summary_text: 提取到的摘要文本
        recent_messages: 最近消息窗口
        total_messages: 原始消息总数
    """

    summary_text: str
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    total_messages: int = 0
    role_counts: dict[str, int] = field(default_factory=dict)
    type_counts: dict[str, int] = field(default_factory=dict)

    def to_context_messages(self) -> list[dict[str, Any]]:
        """
        将快照转换为可直接输入模型的上下文消息。

        :return: 记忆注入后的消息列表
        """

        context_messages: list[dict[str, Any]] = []
        if self.summary_text.strip():
            context_messages.append(
                _build_summary_message(
                    summary_text=self.summary_text,
                    recent_count=len(self.recent_messages),
                    total_count=self.total_messages,
                )
            )
        context_messages.extend(self.recent_messages)
        return context_messages


@dataclass(slots=True)
class MemoryInjector:
    """
    会话记忆注入器。

    负责从消息历史中提取摘要，并选择最近窗口中的消息，形成可供模型继续推理的上下文。
    """

    recent_limit: int = _RECENT_MESSAGE_DEFAULT_LIMIT

    def build_snapshot(self, messages: Sequence[MessageInput]) -> ConversationMemorySnapshot:
        """
        从消息列表构造记忆快照。

        :param messages: 原始消息序列
        :return: 记忆快照
        """

        normalized_messages = [_coerce_message(item) for item in messages]
        summary_text = extract_summary_text(normalized_messages)
        recent_messages = extract_recent_messages(
            normalized_messages,
            recent_limit=self.recent_limit,
        )
        role_counts, type_counts = _count_message_statistics(normalized_messages)
        return ConversationMemorySnapshot(
            summary_text=summary_text,
            recent_messages=recent_messages,
            total_messages=len(normalized_messages),
            role_counts=role_counts,
            type_counts=type_counts,
        )

    def inject(self, messages: Sequence[MessageInput]) -> list[dict[str, Any]]:
        """
        将记忆注入上下文。

        :param messages: 原始消息序列
        :return: 注入后的消息列表
        """

        snapshot = self.build_snapshot(messages)
        return snapshot.to_context_messages()


def inject_memory_context(
    messages: Sequence[MessageInput],
    recent_limit: int = _RECENT_MESSAGE_DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    便捷函数：将消息列表注入为记忆上下文。

    :param messages: 原始消息序列
    :param recent_limit: 最近消息保留条数
    :return: 注入后的消息列表
    """

    injector = MemoryInjector(recent_limit=recent_limit)
    return injector.inject(messages)


def build_memory_snapshot(
    messages: Sequence[MessageInput],
    recent_limit: int = _RECENT_MESSAGE_DEFAULT_LIMIT,
) -> ConversationMemorySnapshot:
    """
    便捷函数：构造会话记忆快照。

    :param messages: 原始消息序列
    :param recent_limit: 最近消息保留条数
    :return: 记忆快照
    """

    injector = MemoryInjector(recent_limit=recent_limit)
    return injector.build_snapshot(messages)


__all__ = [
    "ConversationMemorySnapshot",
    "MemoryInjector",
    "build_memory_snapshot",
    "extract_recent_messages",
    "extract_summary_text",
    "inject_memory_context",
]
