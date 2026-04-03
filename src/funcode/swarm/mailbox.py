"""
模块名称：swarm.mailbox
功能描述：
    提供基于 JSON Lines 文件的真实邮箱实现，支持消息发送、全量读取、
    指定接收方过滤与真实统计快照。

主要组件：
    - FileMailbox: 文件邮箱

依赖说明：
    - json: 消息序列化
    - pathlib: 路径处理
    - datetime: 时间统计
    - funcode.swarm.models: 团队消息模型

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现文件邮箱
    - 2026-04-01 JucieOvo: 增加全量读取与快照统计
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from funcode.swarm.models import SwarmMailboxSnapshot, SwarmMessage


class FileMailbox:
    """
    基于文件的真实邮箱实现。
    """

    def __init__(self, mailbox_path: Path) -> None:
        self._mailbox_path = mailbox_path
        self._mailbox_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._mailbox_path.exists():
            self._mailbox_path.write_text("", encoding="utf-8")

    def send(self, message: SwarmMessage) -> None:
        """
        发送消息到邮箱。

        :param message: 消息对象。
        """

        with self._mailbox_path.open("a", encoding="utf-8") as mailbox_file:
            mailbox_file.write(json.dumps(message.model_dump(mode="json"), ensure_ascii=False))
            mailbox_file.write("\n")

    def read_all(self) -> list[SwarmMessage]:
        """
        读取全部消息。

        :return: 消息列表。
        :raises ValueError: 当文件中存在非法 JSON 行时触发。
        """

        messages: list[SwarmMessage] = []
        with self._mailbox_path.open("r", encoding="utf-8") as mailbox_file:
            for line_number, raw_line in enumerate(mailbox_file, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"邮箱文件存在非法 JSON 行：{self._mailbox_path}:{line_number}") from exc
                messages.append(SwarmMessage.model_validate(payload))
        return messages

    def read_for(self, recipient: str) -> list[SwarmMessage]:
        """
        读取指定接收方的消息。

        :param recipient: 接收方名称，使用 `*` 表示读取全部消息。
        :return: 消息列表。
        """

        messages = self.read_all()
        if recipient == "*":
            return messages
        return [message for message in messages if message.recipient == recipient or message.recipient == "*"]

    def snapshot(self) -> SwarmMailboxSnapshot:
        """
        返回邮箱的真实快照。

        :return: 邮箱快照对象。
        """

        messages = self.read_all()
        recipient_counts = Counter(message.recipient for message in messages)
        team_counts = Counter(message.team_name for message in messages)
        latest_message_at: datetime | None = None
        if messages:
            latest_message_at = max(message.created_at for message in messages)
        return SwarmMailboxSnapshot(
            mailbox_path=str(self._mailbox_path),
            message_count=len(messages),
            recipient_counts=dict(sorted(recipient_counts.items())),
            team_counts=dict(sorted(team_counts.items())),
            latest_message_at=latest_message_at,
        )
