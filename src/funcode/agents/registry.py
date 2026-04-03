"""
模块名称：agents.registry
功能描述：
    提供代理定义注册表，并在默认情况下从真实工作区中自动发现代理定义。
    发现来源包括：
    1. `.funcode/agents/*.json` 中持久化的代理定义；
    2. `.funcode/swarm/teams/*.json` 与对应任务中真实存在的团队/任务归属信息。

主要组件：
    - AgentRegistry: 代理注册表

依赖说明：
    - pathlib: 工作区路径处理
    - json: 代理定义文件解析
    - funcode.agents.models: 代理数据模型
    - funcode.swarm.store: 团队与任务持久化存储

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现代理注册表
    - 2026-04-01 JucieOvo: 增加真实工作区代理自动发现能力
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from funcode.agents.models import AgentDefinition, AgentRuntimeState
from funcode.swarm.store import SwarmStore


def _workspace_root_from_env() -> Path:
    """
    根据环境变量与当前工作目录推导真实工作区根目录。

    :return: 工作区根目录。
    """

    for env_name in ("FUNCODE_PY_WORKSPACE_DIR", "FUNCODE_WORKSPACE_DIR"):
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            return Path(env_value).expanduser().resolve()
    return Path.cwd().resolve()


def _definition_priority(definition: AgentDefinition) -> int:
    """
    为代理定义建立覆盖优先级。

    :param definition: 代理定义。
    :return: 越大表示越优先保留。
    """

    priority_map = {
        "manual": 3,
        "workspace_file": 2,
        "task_owner": 1,
        "swarm_team": 0,
    }
    return priority_map.get(definition.source, 0)


class AgentRegistry:
    """
    代理注册表。

    注册表内部既保存显式定义，也保存从真实工作区推导出的代理视图。
    """

    def __init__(self, workspace_dir: Path | None = None, auto_discover: bool = True) -> None:
        self._workspace_dir = (workspace_dir or _workspace_root_from_env()).resolve()
        self._agents: dict[str, AgentDefinition] = {}
        if auto_discover:
            self.discover_workspace_agents()

    def register(self, definition: AgentDefinition) -> None:
        """
        注册代理定义。

        :param definition: 代理定义对象。
        """

        existing = self._agents.get(definition.agent_name)
        if existing is None or _definition_priority(definition) >= _definition_priority(existing):
            self._agents[definition.agent_name] = definition

    def get(self, agent_name: str) -> AgentDefinition:
        """
        获取代理定义。

        :param agent_name: 代理名称。
        :return: 代理定义对象。
        :raises KeyError: 当代理不存在时触发。
        """

        try:
            return self._agents[agent_name]
        except KeyError as exc:
            raise KeyError(f"未找到代理定义：{agent_name}") from exc

    def list(self) -> list[AgentDefinition]:
        """
        列出全部代理定义。

        :return: 代理定义列表。
        """

        return sorted(self._agents.values(), key=lambda item: item.agent_name.lower())

    def discover_workspace_agents(self) -> None:
        """
        从真实工作区发现代理定义。

        发现优先读取持久化代理文件，再根据 swarm 团队与任务归属生成可见代理视图。
        """

        self._discover_agent_files()
        self._discover_swarm_agents()

    def _discover_agent_files(self) -> None:
        """
        读取 `.funcode/agents/*.json` 中保存的代理定义。
        """

        agent_dir = self._workspace_dir / ".funcode" / "agents"
        if not agent_dir.exists():
            return

        for agent_file in sorted(agent_dir.glob("*.json")):
            if not agent_file.is_file():
                continue
            definition = AgentDefinition.model_validate_json(agent_file.read_text(encoding="utf-8"))
            self.register(
                definition.model_copy(
                    update={
                        "source": "workspace_file",
                        "tags": sorted({*definition.tags, "persisted"}),
                    }
                )
            )

    def _discover_swarm_agents(self) -> None:
        """
        基于真实 swarm 团队与任务信息派生代理定义。
        """

        swarm_root = self._workspace_dir / ".funcode" / "swarm"
        store = SwarmStore(swarm_root)

        for team in store.list_teams():
            tasks = store.list_tasks(team.team_name)
            task_owners = [task.owner for task in tasks if task.owner]
            unique_owners = sorted({owner for owner in task_owners if owner})
            team_runtime_state = self._build_team_runtime_state(team.team_name, tasks)

            self.register(
                AgentDefinition(
                    agent_name=team.team_name,
                    role="leader",
                    description=f"由 swarm 团队 {team.team_name} 直接映射得到的团队代理视图",
                    max_concurrency=max(1, len(tasks) or 1),
                    source="swarm_team",
                    team_name=team.team_name,
                    tags=["swarm", "team"],
                    runtime_state=team_runtime_state,
                )
            )

            if unique_owners:
                for owner in unique_owners:
                    owner_tasks = [task for task in tasks if task.owner == owner]
                    owner_state = self._build_owner_runtime_state(team.team_name, owner_tasks)
                    self.register(
                        AgentDefinition(
                            agent_name=owner,
                            role="worker",
                            description=f"由 swarm 团队 {team.team_name} 中真实任务归属推导的代理",
                            max_concurrency=max(1, len(owner_tasks)),
                            source="task_owner",
                            team_name=team.team_name,
                            tags=["swarm", "task-owner"],
                            runtime_state=owner_state,
                        )
                    )

    @staticmethod
    def _build_team_runtime_state(team_name: str, tasks: list[Any]) -> AgentRuntimeState:
        """
        根据团队任务集合生成运行时状态快照。

        :param team_name: 团队名称。
        :param tasks: 团队任务列表。
        :return: 运行状态。
        """

        task_count = len(tasks)
        completed_task_count = sum(1 for task in tasks if getattr(task, "status", "") == "completed")
        failed_task_count = sum(1 for task in tasks if getattr(task, "status", "") == "failed")
        status = "pending"
        if task_count > 0:
            if failed_task_count > 0:
                status = "failed"
            elif completed_task_count == task_count:
                status = "completed"
            elif any(getattr(task, "status", "") == "in_progress" for task in tasks):
                status = "running"
        last_task_id = getattr(tasks[-1], "task_id", None) if tasks else None
        last_seen_at = None
        if tasks:
            task_datetimes = [getattr(task, "updated_at", None) or getattr(task, "created_at", None) for task in tasks]
            task_datetimes = [value for value in task_datetimes if value is not None]
            if task_datetimes:
                last_seen_at = max(task_datetimes)
        return AgentRuntimeState(
            status=status,
            team_name=team_name,
            current_task_id=None,
            last_task_id=last_task_id,
            task_count=task_count,
            completed_task_count=completed_task_count,
            failed_task_count=failed_task_count,
            last_seen_at=last_seen_at,
            metadata={"source": "swarm_team"},
        )

    @staticmethod
    def _build_owner_runtime_state(team_name: str, tasks: list[Any]) -> AgentRuntimeState:
        """
        根据任务归属生成代理运行状态。

        :param team_name: 团队名称。
        :param tasks: 属于同一代理的任务列表。
        :return: 运行状态。
        """

        task_count = len(tasks)
        completed_task_count = sum(1 for task in tasks if getattr(task, "status", "") == "completed")
        failed_task_count = sum(1 for task in tasks if getattr(task, "status", "") == "failed")
        current_task = next((task for task in tasks if getattr(task, "status", "") == "in_progress"), None)
        last_task_id = getattr(tasks[-1], "task_id", None) if tasks else None
        last_seen_at = None
        if tasks:
            task_datetimes = [getattr(task, "updated_at", None) or getattr(task, "created_at", None) for task in tasks]
            task_datetimes = [value for value in task_datetimes if value is not None]
            if task_datetimes:
                last_seen_at = max(task_datetimes)
        status = "pending"
        if task_count > 0:
            if failed_task_count > 0:
                status = "failed"
            elif completed_task_count == task_count:
                status = "completed"
            elif current_task is not None:
                status = "running"
        return AgentRuntimeState(
            status=status,
            team_name=team_name,
            current_task_id=getattr(current_task, "task_id", None),
            last_task_id=last_task_id,
            task_count=task_count,
            completed_task_count=completed_task_count,
            failed_task_count=failed_task_count,
            last_seen_at=last_seen_at,
            metadata={"source": "task_owner"},
        )

    def snapshot(self) -> dict[str, Any]:
        """
        生成代理注册表的真实快照。

        :return: 结构化快照。
        """

        agents = self.list()
        return {
            "workspace_dir": str(self._workspace_dir),
            "agent_count": len(agents),
            "source_counts": {
                source: sum(1 for item in agents if item.source == source)
                for source in sorted({item.source for item in agents})
            },
            "status_counts": {
                status: sum(
                    1
                    for item in agents
                    if item.runtime_state is not None and item.runtime_state.status == status
                )
                for status in sorted({item.runtime_state.status for item in agents if item.runtime_state is not None})
            },
            "agents": [agent.model_dump(mode="json") for agent in agents],
        }
