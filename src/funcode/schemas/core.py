"""
模块名称：schemas.core
功能描述：
    定义 Python 版 Funcode 的统一核心数据模型，覆盖消息、工具调用、会话状态、
    图执行状态、执行请求与执行结果，并补齐 LSP 与 plan mode 相关模型。

主要组件：
    - ToolCallRecord: 工具调用记录。
    - MessageRecord: 消息记录。
    - LspSymbol: LSP 符号结构。
    - LspDiagnostic: LSP 诊断结构。
    - PlanModeState: plan mode 状态结构。
    - SessionState: 会话持久化状态。
    - GraphState: 图执行状态。
    - ExecutionRequest: 执行请求。
    - ExecutionResult: 执行结果。

依赖说明：
    - pathlib: 工作区路径。
    - pydantic: 数据建模。
    - typing: 类型标注。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 补齐 LSP 与 plan mode 结构模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolCallRecord(BaseModel):
    """工具调用记录。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(description="工具名称")
    arguments: dict[str, Any] = Field(default_factory=dict, description="调用参数")
    call_id: str | None = Field(default=None, description="调用标识")
    status: str = Field(default="pending", description="调用状态")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    result_preview: str | None = Field(default=None, description="结果摘要")
    error_message: str | None = Field(default=None, description="错误信息")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class MessageRecord(BaseModel):
    """会话消息记录。"""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(description="消息角色")
    content: str = Field(description="消息内容")
    name: str | None = Field(default=None, description="消息名称")
    message_id: str | None = Field(default=None, description="消息标识")
    thread_id: str | None = Field(default=None, description="线程标识")
    created_at: str | None = Field(default=None, description="创建时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class LspLocation(BaseModel):
    """LSP 浣嶇疆妯″瀷銆?"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="鏂囦欢璺緞")
    line: int = Field(ge=1, description="琛屽彿")
    column: int = Field(ge=1, description="鍒楀彿")
    end_line: int | None = Field(default=None, ge=1, description="缁撴潫琛屽彿")
    end_column: int | None = Field(default=None, ge=1, description="缁撴潫鍒楀彿")
    language: str | None = Field(default=None, description="璇█绫诲瀷")


class LspSymbol(BaseModel):
    """LSP 符号模型。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="符号名称")
    kind: str = Field(description="符号类型")
    path: str = Field(description="符号所在文件路径")
    line: int = Field(ge=1, description="行号")
    column: int = Field(ge=1, description="列号")
    language: str = Field(description="语言类型")
    container_name: str | None = Field(default=None, description="容器符号名称")
    signature: str = Field(default="", description="符号签名")


class LspDiagnostic(BaseModel):
    """LSP 诊断信息模型。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="诊断文件路径")
    line: int = Field(ge=1, description="行号")
    column: int = Field(ge=1, description="列号")
    severity: str = Field(description="严重级别")
    message: str = Field(description="诊断消息")
    source: str = Field(description="诊断来源")
    code: str = Field(description="诊断编码")


class LspReference(BaseModel):
    """LSP 寮曠敤妯″瀷銆?"""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(description="寮曠敤绗﹀彿鍚嶇О")
    location: LspLocation = Field(description="寮曠敤浣嶇疆")
    is_definition: bool = Field(default=False, description="鏄惁涓哄畾涔夊湴鐐?")
    context_line: str = Field(default="", description="鍘熷鏂囨湰琛?")


class LspHover(BaseModel):
    """LSP hover 淇℃伅妯″瀷銆?"""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(description="绗﹀彿鍚嶇О")
    kind: str = Field(description="绗﹀彿绫诲瀷")
    signature: str = Field(default="", description="绗﹀彿绛惧悕")
    documentation: str | None = Field(default=None, description="鏂囨。璇存槑")
    location: LspLocation = Field(description="瀹氫箟浣嶇疆")


class LspServiceState(BaseModel):
    """LSP 璇█鏈嶅姟鐘舵€併€?"""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(description="璇█鍚嶇О")
    extensions: list[str] = Field(default_factory=list, description="鏀寔鐨勬墿灞曞悕")
    cached_document_count: int = Field(default=0, ge=0, description="缂撳瓨鏂囨。鏁伴噺")
    last_indexed_at: str | None = Field(default=None, description="鏈€杩戜竴娆＄储寮曟椂闂?")


class PlanModeState(BaseModel):
    """plan mode 状态模型。"""

    model_config = ConfigDict(extra="forbid")

    active: bool = Field(description="是否处于 plan mode")
    status: str = Field(description="当前状态")
    workspace_dir: str = Field(description="工作区目录")
    plan_dir: str = Field(description="plan 目录")
    state_file_path: str = Field(description="状态文件路径")
    plan_file_path: str = Field(description="计划文件路径")
    entered_at: str | None = Field(default=None, description="进入时间")
    exited_at: str | None = Field(default=None, description="退出时间")
    goal: str | None = Field(default=None, description="目标描述")
    steps: list[str] = Field(default_factory=list, description="步骤列表")
    notes: str | None = Field(default=None, description="备注信息")
    last_actor: str | None = Field(default=None, description="最后执行者")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SessionState(BaseModel):
    """会话持久化状态。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(description="会话唯一标识")
    graph_name: str = Field(description="绑定的图名称")
    output_format: str = Field(description="输出格式")
    system_prompt: str | None = Field(default=None, description="系统提示词")
    messages: list[MessageRecord] = Field(default_factory=list, description="消息记录")
    tool_calls: list[ToolCallRecord] = Field(default_factory=list, description="工具调用记录")
    tool_results: list[dict[str, Any]] = Field(default_factory=list, description="工具执行结果")
    plan_steps: list[str] = Field(default_factory=list, description="计划步骤")
    latest_output: str | None = Field(default=None, description="最近输出")
    turn_count: int = Field(default=0, ge=0, description="轮次计数")
    created_at: str = Field(description="创建时间")
    updated_at: str = Field(description="更新时间")
    permission_snapshot: dict[str, Any] = Field(default_factory=dict, description="权限快照")
    mcp_resources: list[dict[str, Any]] = Field(default_factory=list, description="MCP 资源快照")
    agent_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="代理快照")
    team_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="团队快照")
    mailbox_snapshot: dict[str, Any] = Field(default_factory=dict, description="邮箱快照")
    runtime_metadata: dict[str, Any] = Field(default_factory=dict, description="运行时扩展数据")


class GraphState(BaseModel):
    """图执行状态。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(description="会话标识")
    graph_name: str = Field(description="图名称")
    output_format: str = Field(description="输出格式")
    user_input: str = Field(description="本轮用户输入")
    system_prompt: str | None = Field(default=None, description="本轮系统提示词")
    llm_response: str = Field(default="", description="模型原始响应")
    final_output: str = Field(default="", description="最终输出")
    requires_tools: bool = Field(default=False, description="是否需要工具")
    tool_calls: list[ToolCallRecord] = Field(default_factory=list, description="工具调用记录")
    tool_results: list[dict[str, Any]] = Field(default_factory=list, description="工具结果")
    messages: list[MessageRecord] = Field(default_factory=list, description="消息记录")
    plan_steps: list[str] = Field(default_factory=list, description="计划步骤")
    error_message: str | None = Field(default=None, description="错误信息")
    permission_snapshot: dict[str, Any] = Field(default_factory=dict, description="权限快照")
    mcp_resources: list[dict[str, Any]] = Field(default_factory=list, description="MCP 资源快照")
    agent_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="代理快照")
    team_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="团队快照")
    mailbox_snapshot: dict[str, Any] = Field(default_factory=dict, description="邮箱快照")

    @classmethod
    def from_session_state(
        cls,
        session_state: SessionState,
        user_input: str,
        system_prompt: str | None,
    ) -> "GraphState":
        """
        由会话状态构建图执行状态。

        :param session_state: 已持久化的会话状态。
        :param user_input: 本轮用户输入。
        :param system_prompt: 本轮系统提示词。
        :return: 图执行状态。
        """

        return cls(
            session_id=session_state.session_id,
            graph_name=session_state.graph_name,
            output_format=session_state.output_format,
            user_input=user_input,
            system_prompt=system_prompt if system_prompt is not None else session_state.system_prompt,
            llm_response="",
            final_output="",
            requires_tools=bool(session_state.tool_calls),
            tool_calls=list(session_state.tool_calls),
            tool_results=list(session_state.tool_results),
            messages=list(session_state.messages),
            plan_steps=list(session_state.plan_steps),
            error_message=None,
            permission_snapshot=dict(session_state.permission_snapshot),
            mcp_resources=list(session_state.mcp_resources),
            agent_snapshots=list(session_state.agent_snapshots),
            team_snapshots=list(session_state.team_snapshots),
            mailbox_snapshot=dict(session_state.mailbox_snapshot),
        )


class ExecutionRequest(BaseModel):
    """单次运行请求。"""

    model_config = ConfigDict(extra="forbid")

    workspace_dir: Path = Field(description="工作区目录")
    user_input: str = Field(description="用户输入")
    session_id: str | None = Field(default=None, description="会话标识")
    system_prompt: str | None = Field(default=None, description="系统提示词")
    graph_name: str = Field(default="main", description="目标图名称")
    output_format: str = Field(default="text", description="输出格式")
    max_turns: int = Field(default=32, ge=1, description="最大轮次")
    stream: bool = Field(default=True, description="是否流式执行")
    debug: bool = Field(default=False, description="是否开启调试")
    permission_snapshot: dict[str, Any] = Field(default_factory=dict, description="权限快照")
    mcp_resources: list[dict[str, Any]] = Field(default_factory=list, description="MCP 资源快照")
    agent_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="代理快照")
    team_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="团队快照")
    mailbox_snapshot: dict[str, Any] = Field(default_factory=dict, description="邮箱快照")


class ExecutionResult(BaseModel):
    """单次运行结果。"""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(description="是否成功")
    session_id: str = Field(description="会话标识")
    graph_name: str = Field(description="图名称")
    output_format: str = Field(description="输出格式")
    user_input: str = Field(description="用户输入")
    final_output: str = Field(description="最终输出")
    llm_response: str = Field(default="", description="模型原始响应")
    messages: list[MessageRecord] = Field(default_factory=list, description="消息记录")
    tool_calls: list[ToolCallRecord] = Field(default_factory=list, description="工具调用记录")
    tool_results: list[dict[str, Any]] = Field(default_factory=list, description="工具结果")
    plan_steps: list[str] = Field(default_factory=list, description="计划步骤")
    error_message: str | None = Field(default=None, description="错误信息")
    permission_snapshot: dict[str, Any] = Field(default_factory=dict, description="权限快照")
    mcp_resources: list[dict[str, Any]] = Field(default_factory=list, description="MCP 资源快照")
    agent_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="代理快照")
    team_snapshots: list[dict[str, Any]] = Field(default_factory=list, description="团队快照")
    mailbox_snapshot: dict[str, Any] = Field(default_factory=dict, description="邮箱快照")

    @classmethod
    def from_graph_state(cls, state: GraphState) -> "ExecutionResult":
        """
        由图执行状态构建运行结果。

        :param state: 图执行状态。
        :return: 执行结果。
        """

        return cls(
            success=state.error_message is None,
            session_id=state.session_id,
            graph_name=state.graph_name,
            output_format=state.output_format,
            user_input=state.user_input,
            final_output=state.final_output,
            llm_response=state.llm_response,
            messages=list(state.messages),
            tool_calls=list(state.tool_calls),
            tool_results=list(state.tool_results),
            plan_steps=list(state.plan_steps),
            error_message=state.error_message,
            permission_snapshot=dict(state.permission_snapshot),
            mcp_resources=list(state.mcp_resources),
            agent_snapshots=list(state.agent_snapshots),
            team_snapshots=list(state.team_snapshots),
            mailbox_snapshot=dict(state.mailbox_snapshot),
        )
