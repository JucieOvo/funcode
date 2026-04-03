"""
模块名称：compact.compressor
功能描述：
    提供上下文压缩能力，包含按长度裁剪、按角色整理与摘要压缩三类真实逻辑，
    用于在会话上下文超过阈值时保留高价值信息并减少模型输入负担。

主要组件：
    - CompressionResult: 压缩结果对象
    - ContextCompressor: 上下文压缩器
    - compress_messages: 便捷压缩函数

依赖说明：
    - dataclasses: 用于结果对象定义
    - typing: 用于类型注解

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现上下文压缩器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MessageInput = Mapping[str, Any] | Any

_DEFAULT_MAX_MESSAGES = 64
_DEFAULT_MAX_CHARACTERS = 24_000
_DEFAULT_KEEP_HEAD = 4
_DEFAULT_KEEP_TAIL = 16
_DEFAULT_SUMMARY_CHAR_LIMIT = 2_000

_ROLE_PRIORITY = {
    "system": 0,
    "developer": 1,
    "user": 2,
    "assistant": 3,
    "tool": 4,
}


def _coerce_message(message: MessageInput) -> dict[str, Any]:
    """
    将任意消息对象规范化为字典。

    :param message: 原始消息对象
    :return: 消息字典
    :raises TypeError: 无法转换时抛出
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
    将消息内容统一为字符串。

    :param content: 原始内容
    :return: 文本内容
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
    获取消息角色。

    :param message: 消息字典
    :return: 角色名
    """

    role = message.get("role") or message.get("author") or message.get("speaker") or "unknown"
    return str(role).strip().lower() or "unknown"


def _estimate_message_length(message: Mapping[str, Any]) -> int:
    """
    估算消息长度，用于压缩判断。

    :param message: 消息字典
    :return: 估算后的字符长度
    """

    role_text = _message_role(message)
    content_text = _normalize_content(message.get("content"))
    extra_text = _normalize_content(message.get("summary") or message.get("summary_text"))
    return len(role_text) + len(content_text) + len(extra_text)


def _build_summary_message(
    removed_messages: Sequence[Mapping[str, Any]],
    summary_limit: int,
) -> dict[str, Any]:
    """
    基于被压缩消息构造摘要消息。

    :param removed_messages: 被移除的消息
    :param summary_limit: 摘要文本上限
    :return: 系统摘要消息
    """

    role_counts: dict[str, int] = {}
    excerpts: list[str] = []
    for index, message in enumerate(removed_messages, start=1):
        role = _message_role(message)
        role_counts[role] = role_counts.get(role, 0) + 1
        content_text = _normalize_content(message.get("content")).strip()
        if content_text:
            first_line = content_text.splitlines()[0].strip()
            if first_line:
                excerpts.append(f"{index}. {role}: {first_line[:160]}")

    role_summary = ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items()))
    summary_parts = [
        "以下内容是压缩后的上下文摘要，用于保留被裁剪消息中的关键信息。",
        f"被压缩消息数量：{len(removed_messages)}。",
    ]
    if role_summary:
        summary_parts.append(f"角色分布：{role_summary}。")
    if excerpts:
        summary_parts.append("关键信息摘录：")
        summary_parts.extend(excerpts)

    summary_text = "\n".join(summary_parts).strip()
    if len(summary_text) > summary_limit:
        summary_text = summary_text[:summary_limit].rstrip()
    return {
        "role": "system",
        "type": "memory_summary",
        "name": "compressed_context",
        "content": summary_text,
    }


def _order_messages_by_role(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    按角色整理消息，保证系统消息和用户输入优先出现。

    该排序保持同角色内的原始相对顺序不变。

    :param messages: 消息序列
    :return: 排序后的消息列表
    """

    return [dict(message) for message in messages]


def _count_message_statistics(messages: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """
    统计消息列表中各角色的出现次数。

    :param messages: 消息序列。
    :return: 角色计数字典。
    """

    role_counts: dict[str, int] = {}
    for message in messages:
        role = _message_role(message)
        role_counts[role] = role_counts.get(role, 0) + 1
    return role_counts


def _slice_messages(messages: Sequence[Mapping[str, Any]], keep_head: int, keep_tail: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    按前后窗口裁剪消息。

    :param messages: 消息序列
    :param keep_head: 保留前部消息数量
    :param keep_tail: 保留尾部消息数量
    :return: 保留消息与被移除消息
    """

    total = len(messages)
    if total <= keep_head + keep_tail:
        return [dict(message) for message in messages], []

    head = [dict(message) for message in messages[:keep_head]]
    tail = [dict(message) for message in messages[-keep_tail:]]
    removed = [dict(message) for message in messages[keep_head:-keep_tail]]
    return head + tail, removed


@dataclass(slots=True)
class CompressionResult:
    """
    上下文压缩结果。

    属性：
        messages: 压缩后的消息列表
        summary_message: 摘要消息，若无需压缩则为空
        original_message_count: 原始消息数
        compressed_message_count: 压缩后消息数
        original_character_count: 原始字符数
        compressed_character_count: 压缩后字符数
        strategy: 使用的压缩策略名称
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    summary_message: dict[str, Any] | None = None
    original_message_count: int = 0
    compressed_message_count: int = 0
    removed_message_count: int = 0
    original_character_count: int = 0
    compressed_character_count: int = 0
    strategy: str = "none"
    role_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ContextCompressor:
    """
    上下文压缩器。

    通过角色整理、窗口裁剪与摘要压缩减少上下文长度，同时保留足够的对话语义。
    """

    max_messages: int = _DEFAULT_MAX_MESSAGES
    max_characters: int = _DEFAULT_MAX_CHARACTERS
    keep_head: int = _DEFAULT_KEEP_HEAD
    keep_tail: int = _DEFAULT_KEEP_TAIL
    summary_char_limit: int = _DEFAULT_SUMMARY_CHAR_LIMIT

    def compress_messages(self, messages: Sequence[MessageInput]) -> CompressionResult:
        """
        压缩消息序列。

        :param messages: 原始消息序列
        :return: 压缩结果
        :raises ValueError: 当阈值配置无效时抛出
        """

        if self.max_messages < 1:
            raise ValueError("max_messages 必须大于等于 1")
        if self.max_characters < 1:
            raise ValueError("max_characters 必须大于等于 1")
        if self.keep_head < 0 or self.keep_tail < 0:
            raise ValueError("keep_head 与 keep_tail 不能为负数")

        normalized_messages = [_coerce_message(item) for item in messages]
        ordered_messages = _order_messages_by_role(normalized_messages)
        original_character_count = sum(_estimate_message_length(message) for message in ordered_messages)

        if not ordered_messages:
            return CompressionResult(
                messages=[],
                original_message_count=0,
                compressed_message_count=0,
                removed_message_count=0,
                original_character_count=0,
                compressed_character_count=0,
                strategy="empty",
                role_counts={},
            )

        if (
            len(ordered_messages) <= self.max_messages
            and original_character_count <= self.max_characters
        ):
            return CompressionResult(
                messages=ordered_messages,
                original_message_count=len(ordered_messages),
                compressed_message_count=len(ordered_messages),
                removed_message_count=0,
                original_character_count=original_character_count,
                compressed_character_count=original_character_count,
                strategy="none",
                role_counts=_count_message_statistics(ordered_messages),
            )

        retained_messages, removed_messages = _slice_messages(
            ordered_messages,
            keep_head=self.keep_head,
            keep_tail=self.keep_tail,
        )
        if len(retained_messages) > self.max_messages:
            retained_messages = retained_messages[-self.max_messages :]
            removed_messages = ordered_messages[: len(ordered_messages) - len(retained_messages)]

        summary_message = _build_summary_message(
            removed_messages=removed_messages,
            summary_limit=self.summary_char_limit,
        )

        compressed_messages = list(retained_messages)
        if removed_messages:
            insertion_index = 0
            while insertion_index < len(compressed_messages) and _message_role(compressed_messages[insertion_index]) in {"system", "developer"}:
                insertion_index += 1
            compressed_messages.insert(insertion_index, summary_message)
            strategy = "summary_trim"
        else:
            strategy = "role_trim"

        compressed_character_count = sum(_estimate_message_length(message) for message in compressed_messages)
        if compressed_character_count > self.max_characters:
            compressed_messages = compressed_messages[-self.max_messages :]
            compressed_character_count = sum(_estimate_message_length(message) for message in compressed_messages)
            strategy = f"{strategy}_hard_limit"

        return CompressionResult(
            messages=compressed_messages,
            summary_message=summary_message if removed_messages else None,
            original_message_count=len(ordered_messages),
            compressed_message_count=len(compressed_messages),
            removed_message_count=len(removed_messages),
            original_character_count=original_character_count,
            compressed_character_count=compressed_character_count,
            strategy=strategy,
            role_counts=_count_message_statistics(ordered_messages),
        )

    def compress_text(self, text: str) -> str:
        """
        对单段文本执行摘要式压缩。

        :param text: 待压缩文本
        :return: 压缩后文本
        """

        normalized_text = text.strip()
        if len(normalized_text) <= self.summary_char_limit:
            return normalized_text

        lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
        if not lines:
            return normalized_text[: self.summary_char_limit].rstrip()

        head = lines[: max(1, self.keep_head)]
        tail = lines[-max(1, self.keep_tail) :] if len(lines) > self.keep_tail else []
        body = [
            "以下是压缩后的文本摘要。",
            f"原始行数：{len(lines)}。",
        ]
        if head:
            body.append("开头摘录：")
            body.extend(head)
        if tail:
            body.append("结尾摘录：")
            body.extend(tail)

        compressed = "\n".join(body).strip()
        if len(compressed) > self.summary_char_limit:
            return compressed[: self.summary_char_limit].rstrip()
        return compressed

    def compress(self, messages: Sequence[MessageInput]) -> CompressionResult:
        """
        便捷别名，与 compress_messages 保持一致。

        :param messages: 原始消息序列
        :return: 压缩结果
        """

        return self.compress_messages(messages)


def compress_messages(
    messages: Sequence[MessageInput],
    *,
    max_messages: int = _DEFAULT_MAX_MESSAGES,
    max_characters: int = _DEFAULT_MAX_CHARACTERS,
    keep_head: int = _DEFAULT_KEEP_HEAD,
    keep_tail: int = _DEFAULT_KEEP_TAIL,
    summary_char_limit: int = _DEFAULT_SUMMARY_CHAR_LIMIT,
) -> CompressionResult:
    """
    便捷函数：压缩消息序列。

    :param messages: 原始消息序列
    :param max_messages: 最大消息数
    :param max_characters: 最大字符数
    :param keep_head: 保留前部消息数量
    :param keep_tail: 保留尾部消息数量
    :param summary_char_limit: 摘要文本上限
    :return: 压缩结果
    """

    compressor = ContextCompressor(
        max_messages=max_messages,
        max_characters=max_characters,
        keep_head=keep_head,
        keep_tail=keep_tail,
        summary_char_limit=summary_char_limit,
    )
    return compressor.compress_messages(messages)


__all__ = [
    "CompressionResult",
    "ContextCompressor",
    "compress_messages",
]
