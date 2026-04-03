"""
模块名称：swarm.coordinator
功能描述：
    提供团队协作层的真实协调器，负责团队、任务、消息的创建与查询，
    并输出工作区 swarm 的真实快照。

主要组件：
    - SwarmCoordinator: 团队协调器

依赖说明：
    - datetime: 时间戳
    - uuid: 消息与任务标识
    - funcode.swarm.mailbox: 文件邮箱
    - funcode.swarm.models: 团队与任务模型
    - funcode.swarm.store: 持久化存储

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现 swarm 协调器
    - 2026-04-01 JucieOvo: 增加真实快照输出
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from funcode.swarm.mailbox import FileMailbox
from funcode.swarm.models import SwarmMessage, SwarmTask, SwarmTaskUpdate, SwarmTeam, SwarmWorkspaceSnapshot
from funcode.swarm.store import SwarmStore


class SwarmCoordinator:
    """
    团队协调器。

    该对象提供协作层的高层接口，但底层仍然依赖真实文件存储。
    """

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._store = SwarmStore(root_dir=root_dir)
        self._mailbox = FileMailbox(root_dir / "mailbox.jsonl")

    def create_team(self, team_name: str, description: str, workspace_dir: str) -> SwarmTeam:
        """
        创建团队。

        :param team_name: 团队名称。
        :param description: 团队描述。
        :param workspace_dir: 团队所属工作区。
        :return: 团队对象。
        """

        team = SwarmTeam(team_name=team_name, description=description, workspace_dir=workspace_dir)
        self._store.save_team(team)
        return self._store.load_team(team_name)

    def list_teams(self) -> list[SwarmTeam]:
        """
        列出全部团队。

        :return: 团队列表。
        """

        return self._store.list_teams()

    def create_task(
        self,
        team_name: str,
        subject: str,
        detail: str,
        owner: str | None = None,
        dependencies: list[str] | None = None,
    ) -> SwarmTask:
        """
        创建任务。

        :param team_name: 团队名称。
        :param subject: 任务主题。
        :param detail: 任务说明。
        :param owner: 归属代理。
        :param dependencies: 依赖任务列表。
        :return: 任务对象。
        """

        self._store.load_team(team_name)
        task = SwarmTask(
            task_id=str(uuid4()),
            team_name=team_name,
            subject=subject,
            detail=detail,
            owner=owner,
            dependencies=dependencies or [],
        )
        self._store.save_task(task)
        return self._store.load_task(team_name, task.task_id)

    def update_task(self, team_name: str, task_id: str, update: SwarmTaskUpdate) -> SwarmTask:
        """
        更新任务。

        :param team_name: 团队名称。
        :param task_id: 任务标识。
        :param update: 更新对象。
        :return: 更新后的任务。
        """

        task = self._store.load_task(team_name=team_name, task_id=task_id)
        updated_task = task.model_copy(
            update={
                "owner": update.owner if update.owner is not None else task.owner,
                "status": update.status if update.status is not None else task.status,
                "detail": update.detail if update.detail is not None else task.detail,
                "labels": update.labels if update.labels is not None else task.labels,
                "priority": update.priority if update.priority is not None else task.priority,
                "attempt_count": update.attempt_count if update.attempt_count is not None else task.attempt_count,
                "metadata": {**task.metadata, **(update.metadata or {})},
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._store.save_task(updated_task)
        return self._store.load_task(team_name=team_name, task_id=task_id)

    def list_tasks(self, team_name: str) -> list[SwarmTask]:
        """
        列出团队任务。

        :param team_name: 团队名称。
        :return: 任务列表。
        """

        self._store.load_team(team_name)
        return self._store.list_tasks(team_name)

    def send_message(
        self,
        team_name: str,
        sender: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> SwarmMessage:
        """
        发送团队消息。

        :param team_name: 团队名称。
        :param sender: 发送方。
        :param recipient: 接收方。
        :param subject: 消息主题。
        :param body: 消息正文。
        :return: 消息对象。
        """

        self._store.load_team(team_name)
        message = SwarmMessage(
            message_id=str(uuid4()),
            team_name=team_name,
            sender=sender,
            recipient=recipient,
            subject=subject,
            body=body,
            thread_id=str(uuid4()),
        )
        self._mailbox.send(message)
        return message

    def read_mailbox(self, team_name: str, recipient: str) -> list[SwarmMessage]:
        """
        读取邮件箱。

        :param team_name: 团队名称。
        :param recipient: 接收方。
        :return: 消息列表。
        """

        self._store.load_team(team_name)
        return self._mailbox.read_for(recipient)

    def snapshot(self) -> SwarmWorkspaceSnapshot:
        """
        返回当前协作层的真实快照。

        :return: 快照对象。
        """

        return self._store.snapshot()
