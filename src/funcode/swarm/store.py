"""
模块名称：swarm.store
功能描述：
    提供团队、任务与邮箱消息的真实文件持久化实现。
    该层直接读写磁盘中的 JSON 与 JSONL 文件，不使用任何 mock 或假数据。

主要组件：
    - SwarmStore: 团队持久化存储

依赖说明：
    - json: 数据序列化
    - pathlib: 路径处理
    - funcode.swarm.mailbox: 真实邮箱实现
    - funcode.swarm.models: 团队/任务/消息模型

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现 swarm 持久化存储
    - 2026-04-01 JucieOvo: 增加团队/任务/邮箱快照与统计
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from funcode.swarm.mailbox import FileMailbox
from funcode.swarm.models import (
    SwarmMailboxSnapshot,
    SwarmMessage,
    SwarmTask,
    SwarmTeam,
    SwarmTeamSummary,
    SwarmWorkspaceSnapshot,
)


class SwarmStore:
    """
    团队持久化存储。

    所有团队、任务与邮箱消息都落盘到工作区下的 `.funcode/swarm` 目录。
    """

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._teams_dir = root_dir / "teams"
        self._tasks_dir = root_dir / "tasks"
        self._mailbox_path = root_dir / "mailbox.jsonl"
        self._teams_dir.mkdir(parents=True, exist_ok=True)
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._mailbox_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._mailbox_path.exists():
            self._mailbox_path.write_text("", encoding="utf-8")

    def _task_file(self, team_name: str, task_id: str) -> Path:
        """
        构造任务文件路径。

        :param team_name: 团队名称。
        :param task_id: 任务标识。
        :return: 任务文件路径。
        """

        return self._tasks_dir / team_name / f"{task_id}.json"

    def _mailbox(self) -> FileMailbox:
        """
        构造共享邮箱对象。

        :return: 邮箱对象。
        """

        return FileMailbox(self._mailbox_path)

    def _team_tasks(self, team_name: str) -> list[SwarmTask]:
        """
        读取团队下的所有真实任务。

        :param team_name: 团队名称。
        :return: 任务列表。
        """

        task_dir = self._tasks_dir / team_name
        if not task_dir.exists():
            return []
        tasks: list[SwarmTask] = []
        for path in sorted(task_dir.glob("*.json")):
            task = SwarmTask.model_validate_json(path.read_text(encoding="utf-8"))
            tasks.append(task.model_copy(update={"source_path": str(path)}))
        return tasks

    def _enrich_team(self, team: SwarmTeam) -> SwarmTeam:
        """
        根据真实任务统计丰富团队对象。

        :param team: 团队对象。
        :return: 丰富后的团队对象。
        """

        tasks = self._team_tasks(team.team_name)
        open_task_count = sum(1 for task in tasks if task.status in {"pending", "blocked", "in_progress"})
        blocked_task_count = sum(1 for task in tasks if task.status == "blocked")
        completed_task_count = sum(1 for task in tasks if task.status == "completed")
        failed_task_count = sum(1 for task in tasks if task.status == "failed")
        latest_times = [task.updated_at for task in tasks]
        if team.created_at not in latest_times:
            latest_times.append(team.created_at)
        latest_times = [item for item in latest_times if item is not None]
        last_activity_at = max(latest_times) if latest_times else None
        if any(task.status == "in_progress" for task in tasks):
            runtime_status = "running"
        elif blocked_task_count > 0 and open_task_count == blocked_task_count:
            runtime_status = "blocked"
        elif open_task_count > 0:
            runtime_status = "pending"
        elif failed_task_count > 0 and completed_task_count == 0:
            runtime_status = "failed"
        elif completed_task_count > 0:
            runtime_status = "completed"
        else:
            runtime_status = "idle"
        runtime_metadata = {
            **(team.metadata if isinstance(team.metadata, dict) else {}),
            "runtime": {
                "status": runtime_status,
                "task_count": len(tasks),
                "open_task_count": open_task_count,
                "blocked_task_count": blocked_task_count,
                "completed_task_count": completed_task_count,
                "failed_task_count": failed_task_count,
                "last_activity_at": last_activity_at.isoformat() if last_activity_at is not None else None,
            },
        }
        return team.model_copy(
            update={
                "task_count": len(tasks),
                "open_task_count": open_task_count,
                "blocked_task_count": blocked_task_count,
                "completed_task_count": completed_task_count,
                "failed_task_count": failed_task_count,
                "last_activity_at": last_activity_at,
                "updated_at": last_activity_at or team.updated_at,
                "metadata": runtime_metadata,
            }
        )

    def save_team(self, team: SwarmTeam) -> None:
        """
        保存团队定义。

        :param team: 团队对象。
        """

        target_path = self._teams_dir / f"{team.team_name}.json"
        target_path.write_text(
            json.dumps(team.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_team(self, team_name: str) -> SwarmTeam:
        """
        读取团队定义，并附带真实任务统计。

        :param team_name: 团队名称。
        :return: 团队对象。
        :raises FileNotFoundError: 团队文件不存在时触发。
        """

        target_path = self._teams_dir / f"{team_name}.json"
        if not target_path.exists():
            raise FileNotFoundError(f"团队不存在：{team_name}")
        team = SwarmTeam.model_validate_json(target_path.read_text(encoding="utf-8"))
        return self._enrich_team(team)

    def list_teams(self) -> list[SwarmTeam]:
        """
        列出全部团队，并附带真实统计。

        :return: 团队列表。
        """

        teams: list[SwarmTeam] = []
        for path in sorted(self._teams_dir.glob("*.json")):
            team = SwarmTeam.model_validate_json(path.read_text(encoding="utf-8"))
            teams.append(self._enrich_team(team))
        return teams

    def save_task(self, task: SwarmTask) -> None:
        """
        保存任务。

        :param task: 任务对象。
        """

        task_dir = self._tasks_dir / task.team_name
        task_dir.mkdir(parents=True, exist_ok=True)
        target_path = task_dir / f"{task.task_id}.json"
        payload = task.model_copy(
            update={
                "source_path": str(target_path),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        target_path.write_text(
            json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_task(self, team_name: str, task_id: str) -> SwarmTask:
        """
        加载单个任务。

        :param team_name: 团队名称。
        :param task_id: 任务标识。
        :return: 任务对象。
        :raises FileNotFoundError: 当任务不存在时触发。
        """

        target_path = self._task_file(team_name, task_id)
        if not target_path.exists():
            raise FileNotFoundError(f"任务不存在：{team_name}/{task_id}")
        task = SwarmTask.model_validate_json(target_path.read_text(encoding="utf-8"))
        return task.model_copy(update={"source_path": str(target_path)})

    def list_tasks(self, team_name: str) -> list[SwarmTask]:
        """
        列出团队下全部任务。

        :param team_name: 团队名称。
        :return: 任务列表。
        """

        return self._team_tasks(team_name)

    def list_messages(self) -> list[SwarmMessage]:
        """
        读取共享邮箱中的全部消息。

        :return: 消息列表。
        """

        return self._mailbox().read_all()

    def team_summary(
        self,
        team_name: str,
        messages: list[SwarmMessage] | None = None,
    ) -> SwarmTeamSummary:
        """
        返回单个团队的汇总视图。

        :param team_name: 团队名称。
        :param messages: 可选的已读取消息列表，避免重复打开邮箱文件。
        :return: 团队汇总对象。
        """

        team = self.load_team(team_name)
        tasks = self.list_tasks(team_name)
        team_messages = messages if messages is not None else self.list_messages()
        message_count = sum(1 for message in team_messages if message.team_name == team_name)
        return SwarmTeamSummary(
            team=team,
            tasks=tasks,
            message_count=message_count,
            open_task_count=team.open_task_count,
            blocked_task_count=team.blocked_task_count,
            completed_task_count=team.completed_task_count,
            failed_task_count=team.failed_task_count,
        )

    def snapshot(self) -> SwarmWorkspaceSnapshot:
        """
        返回工作区 swarm 的真实快照。

        :return: 快照对象。
        """

        teams = self.list_teams()
        messages = self.list_messages()
        summaries = [self.team_summary(team.team_name, messages=messages) for team in teams]
        mailbox_snapshot = self._mailbox().snapshot()
        return SwarmWorkspaceSnapshot(
            workspace_dir=str(self._root_dir),
            team_count=len(teams),
            task_count=sum(len(summary.tasks) for summary in summaries),
            message_count=len(messages),
            teams=summaries,
            mailbox=mailbox_snapshot,
        )
