"""
模块名称：swarm_lifecycle
功能描述：
    提供工作区内 agents / swarm 相关生命周期的真实运行时接点。
    该模块统一负责代理定义文件、团队、任务与消息的读写封装，
    供 commands、tools 与 runtime 复用，避免重复实现同一套持久化逻辑。
主要组件：
    - SwarmLifecycleService: 工作区生命周期服务。
依赖说明：
    - json: 结构化文件读写。
    - pathlib: 路径与目录处理。
    - funcode.agents: 代理定义与注册表。
    - funcode.swarm: 团队、任务、消息与持久化存储。
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 新增 agents / swarm 生命周期运行时服务。
"""

from __future__ import annotations

from collections import defaultdict
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from funcode.agents.models import AgentDefinition, AgentRunRecord, AgentRuntimeState
from funcode.agents.registry import AgentRegistry
from funcode.swarm.mailbox import FileMailbox
from funcode.swarm.models import (
    SwarmMailboxSnapshot,
    SwarmMessage,
    SwarmTask,
    SwarmTaskStatus,
    SwarmTaskUpdate,
    SwarmTeam,
    SwarmWorkspaceSnapshot,
)
from funcode.swarm.store import SwarmStore


def _normalize_name(value: Any, label: str) -> str:
    """
    将外部输入规范化为可用于文件名的实体名称。

    :param value: 原始输入值。
    :param label: 实体中文标签，便于报错说明。
    :return: 规范化后的名称。
    :raises ValueError: 当名称为空或包含非法路径片段时触发。
    """

    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} 不能为空")
    if normalized in {".", ".."}:
        raise ValueError(f"{label} 不能是保留路径片段")
    if Path(normalized).name != normalized:
        raise ValueError(f"{label} 不能包含路径分隔符")
    if ":" in normalized:
        raise ValueError(f"{label} 不能包含冒号")
    return normalized


def _parse_list_value(raw_value: Any) -> list[str]:
    """
    将列表、JSON 字符串或逗号分隔字符串统一解析成字符串列表。

    :param raw_value: 原始输入。
    :return: 清洗后的字符串列表。
    :raises ValueError: 当值无法解析成列表时触发。
    """

    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [item.strip() for item in text.split(",") if item.strip()]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        raise ValueError("列表字段如果是 JSON 字符串，必须解析为数组")
    raise ValueError("列表字段必须是列表、JSON 字符串、逗号分隔字符串或 None")


def _parse_mapping_value(raw_value: Any) -> dict[str, Any]:
    """
    将字典或 JSON 字符串统一解析为字典。

    :param raw_value: 原始输入。
    :return: 清洗后的字典。
    :raises ValueError: 当值无法解析成字典时触发。
    """

    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return dict(parsed)
        raise ValueError("映射字段如果是 JSON 字符串，必须解析为对象")
    raise ValueError("映射字段必须是字典、JSON 字符串或 None")


def _parse_runtime_state(
    raw_state: Any | None,
    *,
    team_name: str | None = None,
    status: str | None = None,
    current_task_id: str | None = None,
    last_task_id: str | None = None,
    task_count: int | None = None,
    completed_task_count: int | None = None,
    failed_task_count: int | None = None,
    last_seen_at: str | datetime | None = None,
    metadata: Any | None = None,
) -> AgentRuntimeState:
    """
    将输入值统一解析为代理运行时状态。

    :param raw_state: 原始运行时状态。
    :param team_name: 可选的团队名称。
    :param status: 可选状态。
    :param current_task_id: 可选当前任务标识。
    :param last_task_id: 可选最近任务标识。
    :param task_count: 可选任务总数。
    :param completed_task_count: 可选已完成任务数。
    :param failed_task_count: 可选失败任务数。
    :param last_seen_at: 可选最近活跃时间。
    :param metadata: 可选扩展元数据。
    :return: 真实的运行时状态对象。
    """

    if isinstance(raw_state, AgentRuntimeState):
        base_state = raw_state
    elif raw_state is None:
        base_state = AgentRuntimeState()
    elif isinstance(raw_state, str):
        parsed_state = json.loads(raw_state)
        if not isinstance(parsed_state, dict):
            raise ValueError("runtime_state 如果是 JSON 字符串，必须解析为对象")
        base_state = AgentRuntimeState.model_validate(parsed_state)
    elif hasattr(raw_state, "model_dump") and callable(getattr(raw_state, "model_dump")):
        base_state = AgentRuntimeState.model_validate(raw_state.model_dump(mode="python"))
    elif isinstance(raw_state, dict):
        base_state = AgentRuntimeState.model_validate(raw_state)
    else:
        base_state = AgentRuntimeState.model_validate(raw_state)

    update_payload: dict[str, Any] = {}
    if team_name is not None:
        update_payload["team_name"] = team_name
    if status is not None:
        update_payload["status"] = status
    if current_task_id is not None:
        update_payload["current_task_id"] = current_task_id
    if last_task_id is not None:
        update_payload["last_task_id"] = last_task_id
    if task_count is not None:
        update_payload["task_count"] = task_count
    if completed_task_count is not None:
        update_payload["completed_task_count"] = completed_task_count
    if failed_task_count is not None:
        update_payload["failed_task_count"] = failed_task_count
    if last_seen_at is not None:
        if isinstance(last_seen_at, datetime):
            update_payload["last_seen_at"] = last_seen_at
        else:
            parsed_text = str(last_seen_at).strip().replace("Z", "+00:00")
            update_payload["last_seen_at"] = datetime.fromisoformat(parsed_text)
    if metadata is not None:
        update_payload["metadata"] = _parse_mapping_value(metadata)

    if not update_payload:
        return base_state
    return base_state.model_copy(update=update_payload)


class SwarmLifecycleService:
    """
    工作区内 agents / swarm 生命周期服务。

    该服务只围绕真实文件系统进行读写，不引入任何 mock、缓存或假数据。
    """

    def __init__(self, workspace_dir: Path) -> None:
        """
        初始化生命周期服务。

        :param workspace_dir: 当前工作区目录。
        """

        self.workspace_dir = workspace_dir.resolve()
        self.runtime_dir = self.workspace_dir / ".funcode"
        self.agent_dir = self.runtime_dir / "agents"
        self.swarm_dir = self.runtime_dir / "swarm"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.swarm_dir.mkdir(parents=True, exist_ok=True)

    def _agent_file(self, agent_name: str) -> Path:
        """
        计算代理定义文件路径。

        :param agent_name: 代理名称。
        :return: 代理定义文件路径。
        """

        normalized_name = _normalize_name(agent_name, "agent_name")
        return self.agent_dir / f"{normalized_name}.json"

    def _registry(self) -> AgentRegistry:
        """
        构建当前工作区的代理注册表。

        :return: 代理注册表。
        """

        return AgentRegistry(workspace_dir=self.workspace_dir)

    def _store(self) -> SwarmStore:
        """
        构建当前工作区的 swarm 持久化存储。

        :return: swarm 存储对象。
        """

        return SwarmStore(self.swarm_dir)

    def _mailbox(self) -> FileMailbox:
        """
        构建当前工作区的共享邮箱对象。

        :return: 共享邮箱对象。
        """

        return FileMailbox(self.swarm_dir / "mailbox.jsonl")

    def _emit_runtime_message(
        self,
        *,
        team_name: str,
        subject: str,
        body: str,
        message_type: str = "update",
        sender: str = "swarm-runtime",
        recipient: str = "*",
        metadata: dict[str, Any] | None = None,
    ) -> SwarmMessage:
        """
        由运行时写入一条事件消息，用于记录任务推进或一致性同步。
        :param team_name: 团队名称。
        :param subject: 消息主题。
        :param body: 消息正文。
        :param message_type: 消息类型。
        :param sender: 发送方。
        :param recipient: 接收方。
        :param metadata: 扩展元数据。
        :return: 已写入邮箱的消息对象。
        """

        runtime_message = SwarmMessage(
            message_id=str(uuid4()),
            team_name=team_name,
            sender=sender,
            recipient=recipient,
            subject=subject,
            body=body,
            message_type=message_type,
            metadata=metadata or {},
        )
        self._mailbox().send(runtime_message)
        return runtime_message

    def _agent_run_files(self) -> list[Path]:
        """
        列举工作区中真实存在的 agent run 文件。
        :return: run 文件路径列表。
        """

        run_dir = self.runtime_dir / "agents" / "runs"
        if not run_dir.exists():
            return []
        return [path for path in sorted(run_dir.glob("*.json")) if path.is_file()]

    def _load_run_record_safely(self, run_file: Path) -> AgentRunRecord | None:
        """
        安全读取单个 run 文件。
        对空文件、半写入文件、损坏 JSON 文件执行跳过，避免影响全局快照流程。

        :param run_file: run 文件路径。
        :return: 成功解析时返回记录，否则返回 None。
        """

        try:
            payload = run_file.read_text(encoding="utf-8")
        except OSError:
            return None
        if not payload.strip():
            return None
        try:
            return AgentRunRecord.model_validate_json(payload)
        except ValueError:
            return None

    def _list_agent_runs(self, team_name: str | None = None) -> list[AgentRunRecord]:
        """
        读取并解析 agent run 记录，可按团队过滤。
        :param team_name: 可选团队名称。
        :return: 运行记录列表，按更新时间倒序。
        """

        records: list[AgentRunRecord] = []
        for run_file in self._agent_run_files():
            record = self._load_run_record_safely(run_file)
            if record is None:
                continue
            if team_name is not None and record.team_name != team_name:
                continue
            records.append(record)
        return sorted(records, key=lambda item: (item.updated_at, item.created_at, item.run_id), reverse=True)

    @staticmethod
    def _map_run_status_to_task_status(run_record: AgentRunRecord) -> SwarmTaskStatus:
        """
        将 agent run 状态映射为 swarm 任务状态。
        :param run_record: run 记录。
        :return: 对应任务状态。
        """

        if run_record.status == "running":
            return "in_progress"
        if run_record.status == "queued":
            background_payload = run_record.metadata.get("background")
            if isinstance(background_payload, dict):
                background_pid = background_payload.get("pid")
                try:
                    if int(background_pid) > 0:
                        return "in_progress"
                except (TypeError, ValueError):
                    pass
            return "pending"
        if run_record.status in {"waiting", "completed"}:
            return "completed"
        if run_record.status == "failed":
            return "failed"
        if run_record.status == "cancelled":
            return "cancelled"
        if run_record.status == "closed":
            if run_record.latest_output is not None and run_record.last_error_message is None:
                return "completed"
            if run_record.close_reason is not None:
                return "cancelled"
            return "pending"
        return "pending"

    def _build_team_task_index(self, team_name: str) -> dict[str, SwarmTask]:
        """
        构建团队任务索引，便于做依赖与编排门控计算。
        :param team_name: 团队名称。
        :return: 以 task_id 为键的任务映射。
        """

        return {task.task_id: task for task in self._store().list_tasks(team_name)}

    def _dependency_state(self, task: SwarmTask, task_index: dict[str, SwarmTask]) -> tuple[bool, list[str]]:
        """
        计算任务依赖是否满足。
        :param task: 待计算任务。
        :param task_index: 团队任务索引。
        :return: (是否满足, 未满足依赖列表)。
        """

        unsatisfied: list[str] = []
        for dependency_id in task.dependencies:
            dependency_task = task_index.get(dependency_id)
            if dependency_task is None or dependency_task.status != "completed":
                unsatisfied.append(dependency_id)
        return (len(unsatisfied) == 0, unsatisfied)

    def _build_team_capacity_state(
        self,
        *,
        team_name: str,
        current_run_id: str | None = None,
    ) -> tuple[dict[str, int], dict[str, int]]:
        """
        构建团队代理并发能力与当前活跃运行计数。
        :param team_name: 团队名称。
        :param current_run_id: 可选当前 run_id，提供时会从活跃计数中排除。
        :return: (capacity_map, active_run_map)。
        """

        capacity_map: dict[str, int] = {}
        for definition in self._registry().list():
            if definition.team_name != team_name:
                continue
            capacity_map[definition.agent_name] = max(1, int(definition.max_concurrency))

        active_run_map: dict[str, int] = defaultdict(int)
        for run_record in self._list_agent_runs(team_name=team_name):
            if current_run_id is not None and run_record.run_id == current_run_id:
                continue
            if run_record.status == "running":
                pass
            elif run_record.status == "queued":
                background_payload = run_record.metadata.get("background")
                if not isinstance(background_payload, dict):
                    continue
                background_pid = background_payload.get("pid")
                try:
                    if int(background_pid) <= 0:
                        continue
                except (TypeError, ValueError):
                    continue
            else:
                continue
            active_run_map[run_record.agent_name] += 1
            capacity_map.setdefault(run_record.agent_name, 1)
        return capacity_map, dict(active_run_map)

    def _apply_team_orchestration_rules(self, team_name: str) -> int:
        """
        基于依赖与并发约束对团队任务执行编排门控。
        :param team_name: 团队名称。
        :return: 实际写入变更的任务数量。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        store = self._store()
        tasks = store.list_tasks(normalized_team_name)
        if not tasks:
            return 0

        task_index = {task.task_id: task for task in tasks}
        capacity_map, active_run_map = self._build_team_capacity_state(team_name=normalized_team_name)
        changed_count = 0
        now = datetime.now(timezone.utc)

        for task in tasks:
            if task.status in {"completed", "failed", "cancelled"}:
                continue

            dependencies_satisfied, unsatisfied_dependencies = self._dependency_state(task, task_index)
            owner_agent = task.owner
            owner_capacity = max(1, int(capacity_map.get(owner_agent, 1))) if owner_agent is not None else 1
            owner_active_runs = int(active_run_map.get(owner_agent, 0)) if owner_agent is not None else 0
            concurrency_satisfied = owner_active_runs < owner_capacity

            blocked_reason: str | None = None
            next_status = task.status
            if task.status != "in_progress":
                if not dependencies_satisfied:
                    blocked_reason = "dependencies_unmet"
                    next_status = "blocked"
                elif owner_agent is not None and not concurrency_satisfied:
                    blocked_reason = "concurrency_limited"
                    next_status = "blocked"
                elif task.status == "blocked":
                    next_status = "pending"

            orchestration_metadata = {
                **task.metadata,
                "orchestration": {
                    "evaluated_at": now.isoformat(),
                    "dependencies_satisfied": dependencies_satisfied,
                    "unsatisfied_dependencies": unsatisfied_dependencies,
                    "owner_agent": owner_agent,
                    "owner_active_runs": owner_active_runs,
                    "owner_max_concurrency": owner_capacity,
                    "concurrency_satisfied": concurrency_satisfied,
                    "blocked_reason": blocked_reason,
                },
            }

            update_payload: dict[str, Any] = {"metadata": orchestration_metadata}
            if next_status != task.status:
                update_payload["status"] = next_status
                if next_status == "blocked":
                    update_payload["finished_at"] = None
                if next_status == "pending" and task.status == "blocked":
                    update_payload["finished_at"] = None

            updated_task = task.model_copy(update=update_payload)
            if task.model_dump(mode="json") == updated_task.model_dump(mode="json"):
                continue
            store.save_task(updated_task)
            changed_count += 1
            if task.status != updated_task.status:
                self._emit_runtime_message(
                    team_name=normalized_team_name,
                    subject=f"task orchestration updated: {task.task_id}",
                    body=f"任务编排状态已更新：{task.status} -> {updated_task.status}",
                    message_type="task",
                    metadata={
                        "task_id": task.task_id,
                        "previous_status": task.status,
                        "current_status": updated_task.status,
                        "blocked_reason": blocked_reason,
                        "unsatisfied_dependencies": unsatisfied_dependencies,
                    },
                )
        return changed_count

    def check_task_execution_gate(
        self,
        *,
        team_name: str,
        task_id: str,
        agent_name: str,
        current_run_id: str | None = None,
    ) -> dict[str, Any]:
        """
        校验指定任务是否满足可执行门控（依赖与并发）。
        :param team_name: 团队名称。
        :param task_id: 任务标识。
        :param agent_name: 当前执行代理。
        :param current_run_id: 可选当前 run_id，用于避免把当前 run 计入并发。
        :return: 可执行性检查结果。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        normalized_task_id = _normalize_name(task_id, "task_id")
        normalized_agent_name = _normalize_name(agent_name, "agent_name")
        self._reconcile_team_tasks_with_agent_runs(normalized_team_name)
        self._apply_team_orchestration_rules(normalized_team_name)

        task_index = self._build_team_task_index(normalized_team_name)
        task = task_index.get(normalized_task_id)
        if task is None:
            raise FileNotFoundError(f"任务不存在：{normalized_team_name}/{normalized_task_id}")

        dependencies_satisfied, unsatisfied_dependencies = self._dependency_state(task, task_index)
        capacity_map, active_run_map = self._build_team_capacity_state(
            team_name=normalized_team_name,
            current_run_id=current_run_id,
        )
        owner_capacity = max(1, int(capacity_map.get(normalized_agent_name, 1)))
        owner_active_runs = int(active_run_map.get(normalized_agent_name, 0))
        concurrency_satisfied = owner_active_runs < owner_capacity

        owner_matches = task.owner is None or task.owner == normalized_agent_name
        executable = (
            task.status not in {"completed", "failed", "cancelled"}
            and dependencies_satisfied
            and concurrency_satisfied
            and owner_matches
        )
        if not dependencies_satisfied:
            reason = "dependencies_unmet"
        elif not concurrency_satisfied:
            reason = "concurrency_limited"
        elif not owner_matches:
            reason = "owner_mismatch"
        elif task.status in {"completed", "failed", "cancelled"}:
            reason = "task_terminal"
        else:
            reason = "ok"

        return {
            "team_name": normalized_team_name,
            "task_id": normalized_task_id,
            "agent_name": normalized_agent_name,
            "task_status": task.status,
            "dependencies_satisfied": dependencies_satisfied,
            "unsatisfied_dependencies": unsatisfied_dependencies,
            "concurrency_satisfied": concurrency_satisfied,
            "owner_active_runs": owner_active_runs,
            "owner_max_concurrency": owner_capacity,
            "owner_matches": owner_matches,
            "executable": executable,
            "reason": reason,
        }

    def _build_task_from_run(self, task: SwarmTask, run_record: AgentRunRecord) -> SwarmTask:
        """
        按最新 run 记录推导任务字段，返回新的任务对象。
        :param task: 原任务对象。
        :param run_record: 最新 run 记录。
        :return: 更新后的任务对象。
        """

        now = datetime.now(timezone.utc)
        next_status = self._map_run_status_to_task_status(run_record)
        next_attempt_count = task.attempt_count
        next_started_at = task.started_at
        next_finished_at = task.finished_at

        if next_status == "in_progress":
            if task.status != "in_progress":
                next_attempt_count += 1
            next_started_at = task.started_at or run_record.started_at or now
            next_finished_at = None
        elif next_status in {"completed", "failed", "cancelled"}:
            next_started_at = task.started_at or run_record.started_at
            next_finished_at = (
                task.finished_at
                or run_record.finished_at
                or run_record.closed_at
                or run_record.updated_at
                or now
            )
        elif next_status == "pending" and task.status == "in_progress":
            next_finished_at = None

        next_metadata = {
            **task.metadata,
            "agent_run_id": run_record.run_id,
            "agent_run_status": run_record.status,
            "agent_name": run_record.agent_name,
            "agent_session_id": run_record.session_id,
            "agent_run_updated_at": run_record.updated_at.isoformat(),
        }
        if run_record.latest_output is not None:
            next_metadata["latest_output"] = run_record.latest_output
        if run_record.last_error_message is not None:
            next_metadata["last_error_message"] = run_record.last_error_message
        if run_record.close_reason is not None:
            next_metadata["close_reason"] = run_record.close_reason

        return task.model_copy(
            update={
                "owner": run_record.agent_name or task.owner,
                "status": next_status,
                "attempt_count": next_attempt_count,
                "started_at": next_started_at,
                "finished_at": next_finished_at,
                "metadata": next_metadata,
                "updated_at": now,
            }
        )

    def _reconcile_team_tasks_with_agent_runs(self, team_name: str) -> int:
        """
        基于真实 agent run 记录对账指定团队任务状态。
        :param team_name: 团队名称。
        :return: 实际发生变化并落盘的任务数量。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        store = self._store()
        tasks = store.list_tasks(normalized_team_name)
        if not tasks:
            return 0
        runs = self._list_agent_runs(team_name=normalized_team_name)
        if not runs:
            return self._apply_team_orchestration_rules(normalized_team_name)

        runs_by_task_id: dict[str, list[AgentRunRecord]] = defaultdict(list)
        for run_record in runs:
            runs_by_task_id[run_record.task.task_id].append(run_record)

        changed_count = 0
        for task in tasks:
            related_runs = runs_by_task_id.get(task.task_id, [])
            if not related_runs:
                continue
            latest_run = related_runs[0]
            updated_task = self._build_task_from_run(task, latest_run)
            if task.model_dump(mode="json") == updated_task.model_dump(mode="json"):
                continue
            store.save_task(updated_task)
            changed_count += 1
            if task.status != updated_task.status:
                self._emit_runtime_message(
                    team_name=normalized_team_name,
                    subject=f"task status synchronized: {task.task_id}",
                    body=f"任务状态已根据 agent run 自动同步：{task.status} -> {updated_task.status}",
                    message_type="task",
                    metadata={
                        "task_id": task.task_id,
                        "previous_status": task.status,
                        "current_status": updated_task.status,
                        "agent_run_id": latest_run.run_id,
                    },
                )
        changed_count += self._apply_team_orchestration_rules(normalized_team_name)
        return changed_count

    def _reconcile_all_teams_with_agent_runs(self) -> dict[str, int]:
        """
        对所有团队执行任务状态对账。
        :return: 每个团队的任务变更数量。
        """

        changes: dict[str, int] = {}
        for team in self._store().list_teams():
            changes[team.team_name] = self._reconcile_team_tasks_with_agent_runs(team.team_name)
        return changes

    def list_agents(self) -> list[AgentDefinition]:
        """
        列出当前工作区可见的全部代理。

        :return: 代理定义列表。
        """

        return self._registry().list()

    def get_agent(self, agent_name: str) -> AgentDefinition:
        """
        读取单个代理定义。

        :param agent_name: 代理名称。
        :return: 代理定义对象。
        """

        return self._registry().get(_normalize_name(agent_name, "agent_name"))

    def create_agent(
        self,
        agent_name: str,
        role: str,
        description: str,
        max_concurrency: int = 1,
        source: str = "manual",
        team_name: str | None = None,
        tags: Any | None = None,
        runtime_state: Any | None = None,
        metadata: Any | None = None,
    ) -> AgentDefinition:
        """
        创建并落盘一个新的代理定义。

        :param agent_name: 代理名称。
        :param role: 代理角色。
        :param description: 代理职责说明。
        :param max_concurrency: 最大并发数。
        :param source: 代理来源。
        :param team_name: 可选团队名称。
        :param tags: 可选标签。
        :param runtime_state: 可选运行时状态。
        :param metadata: 可选运行时元数据。
        :return: 新建后的代理定义。
        """

        normalized_name = _normalize_name(agent_name, "agent_name")
        normalized_role = str(role).strip()
        normalized_description = str(description).strip()
        if not normalized_role:
            raise ValueError("role 不能为空")
        if not normalized_description:
            raise ValueError("description 不能为空")
        normalized_tags = _parse_list_value(tags)
        definition = AgentDefinition(
            agent_name=normalized_name,
            role=normalized_role,
            description=normalized_description,
            max_concurrency=max(1, int(max_concurrency)),
            source=str(source).strip(),
            team_name=team_name.strip() if isinstance(team_name, str) and team_name.strip() else None,
            tags=normalized_tags,
            runtime_state=_parse_runtime_state(
                runtime_state,
                team_name=team_name.strip() if isinstance(team_name, str) and team_name.strip() else None,
                metadata=metadata,
            ),
        )
        target_path = self._agent_file(normalized_name)
        target_path.write_text(
            json.dumps(definition.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.get_agent(normalized_name)

    def update_agent(self, agent_name: str, **updates: Any) -> AgentDefinition:
        """
        更新并重新落盘已有代理定义。

        :param agent_name: 代理名称。
        :param updates: 待更新字段。
        :return: 更新后的代理定义。
        :raises FileNotFoundError: 当目标代理定义不存在时触发。
        """

        normalized_name = _normalize_name(agent_name, "agent_name")
        if not updates:
            raise ValueError("agents update 至少需要提供一个更新字段")
        target_path = self._agent_file(normalized_name)
        if not target_path.exists():
            raise FileNotFoundError(f"代理定义不存在：{normalized_name}")

        current_definition = AgentDefinition.model_validate_json(target_path.read_text(encoding="utf-8"))
        state_updates: dict[str, Any] = {}
        for key in (
            "team_name",
            "status",
            "current_task_id",
            "last_task_id",
            "task_count",
            "completed_task_count",
            "failed_task_count",
            "last_seen_at",
            "metadata",
        ):
            if key in updates and updates[key] is not None:
                state_updates[key] = updates[key]

        runtime_state = _parse_runtime_state(
            updates.get("runtime_state") if "runtime_state" in updates else current_definition.runtime_state,
            **state_updates,
        )

        update_payload: dict[str, Any] = {"agent_name": normalized_name}
        if "role" in updates and updates["role"] is not None:
            update_payload["role"] = str(updates["role"]).strip()
        if "description" in updates and updates["description"] is not None:
            update_payload["description"] = str(updates["description"]).strip()
        if "max_concurrency" in updates and updates["max_concurrency"] is not None:
            update_payload["max_concurrency"] = max(1, int(updates["max_concurrency"]))
        if "source" in updates and updates["source"] is not None:
            update_payload["source"] = str(updates["source"]).strip()
        if "team_name" in updates:
            raw_team_name = updates["team_name"]
            if raw_team_name is None or not str(raw_team_name).strip():
                update_payload["team_name"] = None
            else:
                update_payload["team_name"] = str(raw_team_name).strip()
        if "tags" in updates and updates["tags"] is not None:
            update_payload["tags"] = _parse_list_value(updates["tags"])
        update_payload["runtime_state"] = runtime_state
        updated_definition = current_definition.model_copy(update=update_payload)
        target_path.write_text(
            json.dumps(updated_definition.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.get_agent(normalized_name)

    def delete_agent(self, agent_name: str) -> AgentDefinition:
        """
        删除工作区中持久化的代理定义。

        :param agent_name: 代理名称。
        :return: 被删除的代理定义。
        :raises FileNotFoundError: 当目标代理定义不存在时触发。
        """

        normalized_name = _normalize_name(agent_name, "agent_name")
        target_path = self._agent_file(normalized_name)
        if not target_path.exists():
            raise FileNotFoundError(f"代理定义不存在：{normalized_name}")
        definition = AgentDefinition.model_validate_json(target_path.read_text(encoding="utf-8"))
        target_path.unlink()
        return definition

    def agent_snapshot(self) -> dict[str, Any]:
        """
        输出代理注册表的真实快照。

        :return: 结构化代理快照。
        """

        return self._registry().snapshot()

    def list_teams(self) -> list[SwarmTeam]:
        """
        列出当前工作区的全部团队。

        :return: 团队列表。
        """

        self._reconcile_all_teams_with_agent_runs()
        return self._store().list_teams()

    def get_team(self, team_name: str) -> SwarmTeam:
        """
        读取单个团队定义。

        :param team_name: 团队名称。
        :return: 团队定义对象。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        self._reconcile_team_tasks_with_agent_runs(normalized_team_name)
        return self._store().load_team(normalized_team_name)

    def create_team(
        self,
        team_name: str,
        description: str,
        tags: Any | None = None,
        source: str = "workspace",
        metadata: Any | None = None,
    ) -> SwarmTeam:
        """
        创建并落盘一个新的团队定义。

        :param team_name: 团队名称。
        :param description: 团队职责说明。
        :param tags: 可选团队标签。
        :param source: 团队来源。
        :param metadata: 可选团队元数据。
        :return: 新建后的团队对象。
        """

        normalized_name = _normalize_name(team_name, "team_name")
        normalized_description = str(description).strip()
        if not normalized_description:
            raise ValueError("description 不能为空")
        team = SwarmTeam(
            team_name=normalized_name,
            description=normalized_description,
            workspace_dir=str(self.workspace_dir),
            source=str(source).strip(),
            tags=_parse_list_value(tags),
            metadata=_parse_mapping_value(metadata),
        )
        self._store().save_team(team)
        self._emit_runtime_message(
            team_name=normalized_name,
            subject=f"team created: {normalized_name}",
            body=f"团队已创建：{normalized_name}",
            metadata={"team_name": normalized_name, "source": team.source},
        )
        return self.get_team(normalized_name)

    def delete_team(self, team_name: str) -> SwarmTeam:
        """
        删除团队定义以及对应的任务目录。

        :param team_name: 团队名称。
        :return: 被删除的团队定义。
        :raises FileNotFoundError: 当团队不存在时触发。
        """

        normalized_name = _normalize_name(team_name, "team_name")
        store = self._store()
        team = store.load_team(normalized_name)
        self._emit_runtime_message(
            team_name=normalized_name,
            subject=f"team deleting: {normalized_name}",
            body=f"团队即将删除：{normalized_name}",
            metadata={"team_name": normalized_name, "task_count": team.task_count},
        )
        team_file = store._teams_dir / f"{normalized_name}.json"
        if not team_file.exists():
            raise FileNotFoundError(f"团队不存在：{normalized_name}")
        team_file.unlink()
        task_dir = store._tasks_dir / normalized_name
        if task_dir.exists():
            shutil.rmtree(task_dir)
        return team

    def list_tasks(self, team_name: str) -> list[SwarmTask]:
        """
        列出指定团队下的全部任务。

        :param team_name: 团队名称。
        :return: 任务列表。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        self._reconcile_team_tasks_with_agent_runs(normalized_team_name)
        return self._store().list_tasks(normalized_team_name)

    def get_task(self, team_name: str, task_id: str) -> SwarmTask:
        """
        读取指定团队中的单个任务。

        :param team_name: 团队名称。
        :param task_id: 任务标识。
        :return: 任务对象。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        normalized_task_id = _normalize_name(task_id, "task_id")
        self._reconcile_team_tasks_with_agent_runs(normalized_team_name)
        return self._store().load_task(normalized_team_name, normalized_task_id)

    def create_task(
        self,
        team_name: str,
        subject: str,
        detail: str,
        owner: str | None = None,
        dependencies: Any | None = None,
        labels: Any | None = None,
        priority: int = 0,
        status: SwarmTaskStatus = "pending",
        task_id: str | None = None,
        metadata: Any | None = None,
    ) -> SwarmTask:
        """
        创建并落盘一个新的团队任务。

        :param team_name: 团队名称。
        :param subject: 任务主题。
        :param detail: 任务说明。
        :param owner: 可选任务归属代理。
        :param dependencies: 可选依赖任务列表。
        :param labels: 可选标签。
        :param priority: 任务优先级。
        :param status: 任务状态。
        :param task_id: 可选任务标识。
        :param metadata: 可选扩展元数据。
        :return: 新建后的任务对象。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        normalized_dependencies = _parse_list_value(dependencies)
        normalized_labels = _parse_list_value(labels)
        normalized_subject = str(subject).strip()
        normalized_detail = str(detail).strip()
        if not normalized_subject:
            raise ValueError("subject 不能为空")
        if not normalized_detail:
            raise ValueError("detail 不能为空")
        now = datetime.now(timezone.utc)
        resolved_status: SwarmTaskStatus = status
        started_at = now if resolved_status == "in_progress" else None
        finished_at = now if resolved_status in {"completed", "failed", "cancelled"} else None
        initial_attempt_count = 1 if resolved_status == "in_progress" else 0
        task = SwarmTask(
            task_id=_normalize_name(task_id, "task_id") if task_id else f"task-{uuid4().hex}",
            team_name=normalized_team_name,
            subject=normalized_subject,
            detail=normalized_detail,
            owner=str(owner).strip() if owner is not None and str(owner).strip() else None,
            status=resolved_status,
            dependencies=normalized_dependencies,
            labels=normalized_labels,
            priority=max(0, int(priority)),
            attempt_count=initial_attempt_count,
            created_at=now,
            updated_at=now,
            started_at=started_at,
            finished_at=finished_at,
            metadata=_parse_mapping_value(metadata),
        )
        self._store().save_task(task)
        self._emit_runtime_message(
            team_name=normalized_team_name,
            subject=f"task created: {task.task_id}",
            body=f"任务已创建：{task.subject}",
            message_type="task",
            metadata={
                "task_id": task.task_id,
                "status": task.status,
                "owner": task.owner,
                "priority": task.priority,
            },
        )
        return self.get_task(normalized_team_name, task.task_id)

    def update_task(self, team_name: str, task_id: str, update: SwarmTaskUpdate) -> SwarmTask:
        """
        更新指定任务并重新落盘。

        :param team_name: 团队名称。
        :param task_id: 任务标识。
        :param update: 更新对象。
        :return: 更新后的任务对象。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        normalized_task_id = _normalize_name(task_id, "task_id")
        if not update.model_dump(exclude_none=True):
            raise ValueError("tasks update 至少需要提供一个更新字段")
        store = self._store()
        task = store.load_task(normalized_team_name, normalized_task_id)
        now = datetime.now(timezone.utc)
        next_status = update.status if update.status is not None else task.status
        next_attempt_count = update.attempt_count if update.attempt_count is not None else task.attempt_count
        next_started_at = task.started_at
        next_finished_at = task.finished_at
        if next_status == "in_progress":
            if task.status != "in_progress":
                next_attempt_count += 1
            next_started_at = task.started_at or now
            next_finished_at = None
        elif next_status in {"completed", "failed", "cancelled"}:
            next_started_at = task.started_at or now
            next_finished_at = now
        elif next_status == "pending" and task.status == "in_progress":
            next_finished_at = None
        updated_task = task.model_copy(
            update={
                "owner": update.owner if update.owner is not None else task.owner,
                "status": next_status,
                "detail": update.detail if update.detail is not None else task.detail,
                "labels": update.labels if update.labels is not None else task.labels,
                "priority": update.priority if update.priority is not None else task.priority,
                "attempt_count": next_attempt_count,
                "started_at": next_started_at,
                "finished_at": next_finished_at,
                "metadata": {**task.metadata, **(update.metadata or {})},
                "updated_at": now,
            }
        )
        store.save_task(updated_task)
        self._emit_runtime_message(
            team_name=normalized_team_name,
            subject=f"task updated: {normalized_task_id}",
            body=f"任务已更新：{task.status} -> {updated_task.status}",
            message_type="task",
            metadata={
                "task_id": normalized_task_id,
                "previous_status": task.status,
                "current_status": updated_task.status,
                "owner": updated_task.owner,
            },
        )
        return self.get_task(normalized_team_name, normalized_task_id)

    def stop_task(self, team_name: str, task_id: str) -> SwarmTask:
        """
        将任务标记为已取消。

        :param team_name: 团队名称。
        :param task_id: 任务标识。
        :return: 取消后的任务对象。
        """

        update = SwarmTaskUpdate(status="cancelled")
        return self.update_task(team_name=team_name, task_id=task_id, update=update)

    def list_messages(self, recipient: str = "*") -> list[SwarmMessage]:
        """
        读取共享邮箱中的消息。

        :param recipient: 接收方标识，`*` 表示读取全部消息。
        :return: 消息列表。
        """

        return self._mailbox().read_for(recipient)

    def send_message(
        self,
        team_name: str,
        sender: str,
        recipient: str,
        subject: str,
        body: str,
        message_id: str | None = None,
        reply_to: str | None = None,
        thread_id: str | None = None,
        message_type: str = "note",
        metadata: Any | None = None,
    ) -> SwarmMessage:
        """
        向共享邮箱写入一条真实消息。

        :param team_name: 团队名称。
        :param sender: 发送方。
        :param recipient: 接收方。
        :param subject: 消息主题。
        :param body: 消息正文。
        :param message_id: 可选消息标识。
        :param reply_to: 可选回复目标。
        :param thread_id: 可选线程标识。
        :param message_type: 消息类型。
        :param metadata: 可选扩展元数据。
        :return: 新建后的消息对象。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        self.get_team(normalized_team_name)
        normalized_sender = str(sender).strip()
        normalized_recipient = str(recipient).strip()
        normalized_subject = str(subject).strip()
        normalized_body = str(body).strip()
        if not normalized_sender:
            raise ValueError("sender 不能为空")
        if not normalized_recipient:
            raise ValueError("recipient 不能为空")
        if not normalized_subject:
            raise ValueError("subject 不能为空")
        if not normalized_body:
            raise ValueError("body 不能为空")
        message = SwarmMessage(
            message_id=str(message_id).strip() if message_id is not None and str(message_id).strip() else str(uuid4()),
            team_name=normalized_team_name,
            sender=normalized_sender,
            recipient=normalized_recipient,
            subject=normalized_subject,
            body=normalized_body,
            reply_to=reply_to.strip() if isinstance(reply_to, str) and reply_to.strip() else reply_to,
            thread_id=thread_id.strip() if isinstance(thread_id, str) and thread_id.strip() else thread_id,
            message_type=message_type,
            metadata=_parse_mapping_value(metadata),
        )
        self._mailbox().send(message)
        return message

    def read_mailbox(self, team_name: str, recipient: str) -> list[SwarmMessage]:
        """
        读取团队共享邮箱中对指定接收方可见的消息。

        :param team_name: 团队名称。
        :param recipient: 接收方。
        :return: 消息列表。
        """

        normalized_team_name = _normalize_name(team_name, "team_name")
        self.get_team(normalized_team_name)
        return [
            message
            for message in self._mailbox().read_for(recipient)
            if message.team_name == normalized_team_name
        ]

    def swarm_snapshot(self) -> SwarmWorkspaceSnapshot:
        """
        输出当前工作区 swarm 层的真实快照。

        :return: swarm 工作区快照对象。
        """

        self._reconcile_all_teams_with_agent_runs()
        return self._store().snapshot()

    def snapshot(self) -> dict[str, Any]:
        """
        汇总 agents 与 swarm 的真实运行时快照。

        :return: 结构化快照字典。
        """

        agent_snapshot = self.agent_snapshot()
        reconcile_stats = self._reconcile_all_teams_with_agent_runs()
        swarm_snapshot = self._store().snapshot().model_dump(mode="json")
        mailbox_snapshot = swarm_snapshot.get("mailbox") or {}
        return {
            "workspace_dir": str(self.workspace_dir),
            "agent_snapshot": agent_snapshot,
            "swarm_snapshot": swarm_snapshot,
            "agent_count": agent_snapshot["agent_count"],
            "team_count": swarm_snapshot["team_count"],
            "task_count": swarm_snapshot["task_count"],
            "message_count": swarm_snapshot["message_count"],
            "agent_snapshots": agent_snapshot["agents"],
            "team_snapshots": swarm_snapshot["teams"],
            "mailbox_snapshot": mailbox_snapshot,
            "reconcile_stats": reconcile_stats,
        }
