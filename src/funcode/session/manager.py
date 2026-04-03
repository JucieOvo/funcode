"""
模块名称：manager
功能描述：
    提供会话生命周期管理逻辑，负责创建会话、加载会话、构造图状态以及将执行结果回写到会话仓储。
    该层是 runtime 与 repository 之间的协调层。

主要组件：
    - SessionManager: 会话管理器。

依赖说明：
    - datetime: 时间戳生成。
    - uuid: 会话标识生成。
    - funcode.schemas: 会话、图、执行数据模型。
    - funcode.session.repository: 会话仓储。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化会话管理器实现。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from funcode.schemas import (
    ExecutionRequest,
    ExecutionResult,
    GraphState,
    MessageRecord,
    SessionState,
    ToolCallRecord,
)
from funcode.session.repository import SessionRepository


def _to_message_record(value: Any) -> MessageRecord:
    """
    将输入归一化为会话消息记录。

    这样写入会话文件时可以保证消息字段严格符合 SessionState 的 schema。

    :param value: 待归一化的数据。
    :return: 消息记录对象。
    """

    if isinstance(value, MessageRecord):
        return value
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return MessageRecord.model_validate(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return MessageRecord.model_validate(value)
    return MessageRecord.model_validate(value)


def _to_tool_call_record(value: Any) -> ToolCallRecord:
    """
    将输入归一化为会话中的工具调用记录。

    :param value: 待归一化的数据。
    :return: 工具调用记录对象。
    """

    if isinstance(value, ToolCallRecord):
        return value
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return ToolCallRecord.model_validate(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return ToolCallRecord.model_validate(value)
    return ToolCallRecord.model_validate(value)


def _to_tool_result(value: Any) -> dict[str, Any]:
    """
    将工具结果归一化为普通字典，确保落盘结构可稳定序列化。

    :param value: 待归一化的数据。
    :return: 工具结果字典。
    """

    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return dict(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return dict(value)
    return dict(value)


class SessionManager:
    """
    会话生命周期管理器。

    职责：
        1. 根据请求创建新会话或加载已有会话。
        2. 将会话快照转换为图执行状态。
        3. 将执行结果回写为新的会话快照并持久化。

    属性：
        repository (SessionRepository): 会话仓储实例。
    """

    def __init__(self, repository: SessionRepository) -> None:
        """
        初始化会话管理器。

        :param repository: 会话仓储实例。
        """

        self.repository = repository

    @staticmethod
    def _build_timestamp() -> str:
        """
        生成统一格式的 UTC 时间戳。

        :return: ISO 8601 格式时间戳。
        """

        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _generate_session_id() -> str:
        """
        生成新的会话标识。

        :return: 新会话标识字符串。
        """

        return uuid4().hex

    def load_or_create(self, request: ExecutionRequest) -> SessionState:
        """
        根据请求加载已有会话或创建新会话。

        处理策略：
            - 当请求显式提供 session_id 时，必须加载真实存在的会话；若不存在则直接报错。
            - 当请求未提供 session_id 时，创建新的会话状态。

        :param request: 运行时执行请求。
        :return: 会话状态对象。
        :raises FileNotFoundError: 当显式指定的会话不存在时触发。
        """

        if request.session_id:
            return self.repository.load(request.session_id)
        return self.create_new_state(request)

    def create_new_state(self, request: ExecutionRequest) -> SessionState:
        """
        创建新的会话状态。

        :param request: 运行时执行请求。
        :return: 新创建的会话状态对象。
        """

        timestamp = self._build_timestamp()
        return SessionState(
            session_id=self._generate_session_id(),
            graph_name=request.graph_name,
            output_format=request.output_format,
            system_prompt=request.system_prompt,
            messages=[],
            tool_calls=[],
            tool_results=[],
            plan_steps=[],
            latest_output=None,
            turn_count=0,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def build_graph_state(self, session_state: SessionState, request: ExecutionRequest) -> GraphState:
        """
        基于会话状态与请求构造图执行状态。

        :param session_state: 当前会话状态。
        :param request: 当前执行请求。
        :return: 图执行状态对象。
        """

        graph_state = GraphState.from_session_state(
            session_state=session_state,
            user_input=request.user_input,
            system_prompt=request.system_prompt,
        )
        return graph_state.model_copy(
            update={
                "permission_snapshot": dict(request.permission_snapshot),
                "mcp_resources": list(request.mcp_resources),
                "agent_snapshots": list(request.agent_snapshots),
                "team_snapshots": list(request.team_snapshots),
                "mailbox_snapshot": dict(request.mailbox_snapshot),
            }
        )

    def apply_result(self, session_state: SessionState, result: ExecutionResult) -> SessionState:
        """
        将执行结果回写到会话状态。

        :param session_state: 执行前的会话状态。
        :param result: 本轮执行结果。
        :return: 更新后的会话状态对象。
        """

        return session_state.model_copy(
            update={
                "graph_name": result.graph_name,
                "output_format": result.output_format,
                "messages": [_to_message_record(item) for item in result.messages],
                "tool_calls": [_to_tool_call_record(item) for item in result.tool_calls],
                "tool_results": [_to_tool_result(item) for item in result.tool_results],
                "plan_steps": [str(step) for step in result.plan_steps],
                "latest_output": result.final_output.strip(),
                "turn_count": session_state.turn_count + 1,
                "updated_at": self._build_timestamp(),
            }
        )

    def build_statistics(self, session_state: SessionState) -> dict[str, Any]:
        """
        基于真实会话状态构建统一统计快照。

        :param session_state: 需要统计的会话状态。
        :return: 会话统计字典。
        """

        return {
            "session_id": session_state.session_id,
            "graph_name": session_state.graph_name,
            "output_format": session_state.output_format,
            "turn_count": session_state.turn_count,
            "message_count": len(session_state.messages),
            "tool_call_count": len(session_state.tool_calls),
            "tool_result_count": len(session_state.tool_results),
            "plan_step_count": len(session_state.plan_steps),
            "latest_output": session_state.latest_output,
            "created_at": session_state.created_at,
            "updated_at": session_state.updated_at,
        }

    def save(self, session_state: SessionState) -> SessionState:
        """
        持久化会话状态并返回原对象。

        :param session_state: 待持久化的会话状态。
        :return: 已保存的会话状态对象。
        """

        self.repository.save(session_state)
        return session_state
