"""
模块名称：agents.models
功能描述：
    定义代理层的核心数据模型，覆盖任务描述、代理定义、运行时上下文、
    执行请求与执行结果。该模块的目标是把多代理状态做成真实、可序列化、
    可持久化的结构，而不是只保存抽象名称。

主要组件：
    - AgentTaskSpec: 代理任务描述
    - AgentRuntimeState: 代理运行状态
    - AgentDefinition: 代理定义
    - AgentExecutionContext: 代理执行上下文
    - AgentExecutionRequest: 代理执行请求
    - AgentExecutionResult: 代理执行结果

依赖说明：
    - datetime: 时间戳与状态记录
    - typing: 类型标注
    - pydantic: 数据建模

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现代理层核心模型
    - 2026-04-01 JucieOvo: 增加运行状态与多代理上下文字段
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AgentRole = Literal["leader", "worker", "planner", "tool_runner"]
AgentStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
AgentSource = Literal["manual", "workspace_file", "swarm_team", "task_owner"]
AgentRunStatus = Literal[
    "spawned",
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "interrupted",
    "closed",
    "cancelled",
]
AgentRunMessageRole = Literal["system", "user", "assistant", "event"]


class AgentTaskSpec(BaseModel):
    """
    代理任务描述对象。

    这个对象承载的是代理执行任务的真实业务语义，而不是单纯的 prompt 字符串。
    """

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(description="任务唯一标识")
    title: str = Field(description="任务标题")
    instruction: str = Field(description="分配给代理的执行指令")
    expected_output: str | None = Field(default=None, description="期望输出说明")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外元数据")
    team_name: str | None = Field(default=None, description="所属团队名称")
    owner: str | None = Field(default=None, description="当前归属代理")
    priority: int = Field(default=0, ge=0, description="任务优先级")
    status: AgentStatus = Field(default="pending", description="任务状态")


class AgentRuntimeState(BaseModel):
    """
    代理运行状态快照。

    该模型用于记录代理当前处于什么状态、正在处理什么任务，以及累计统计信息。
    """

    model_config = ConfigDict(frozen=True)

    status: AgentStatus = Field(default="pending", description="代理状态")
    team_name: str | None = Field(default=None, description="所属团队")
    current_task_id: str | None = Field(default=None, description="当前任务标识")
    last_task_id: str | None = Field(default=None, description="最近完成或处理过的任务标识")
    task_count: int = Field(default=0, ge=0, description="累计任务数量")
    completed_task_count: int = Field(default=0, ge=0, description="累计完成任务数量")
    failed_task_count: int = Field(default=0, ge=0, description="累计失败任务数量")
    last_seen_at: datetime | None = Field(default=None, description="最近活跃时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展状态元数据")


class AgentDefinition(BaseModel):
    """
    代理定义对象。

    该对象既能表示显式定义的代理，也能表示从 swarm 团队与任务中推导出的真实代理视图。
    """

    model_config = ConfigDict(frozen=True)

    agent_name: str = Field(description="代理名称")
    role: AgentRole = Field(description="代理角色")
    description: str = Field(description="代理职责描述")
    max_concurrency: int = Field(default=1, ge=1, description="最大并发数")
    source: AgentSource = Field(default="manual", description="定义来源")
    team_name: str | None = Field(default=None, description="所属团队名称")
    tags: list[str] = Field(default_factory=list, description="标签集合")
    runtime_state: AgentRuntimeState | None = Field(default=None, description="运行时状态快照")


class AgentExecutionContext(BaseModel):
    """
    代理执行上下文。

    该上下文保留真实工作区、会话、团队、权限与 MCP 快照，供代理执行时直接读取。
    """

    model_config = ConfigDict(frozen=True)

    workspace_dir: str = Field(description="工作区目录")
    session_id: str | None = Field(default=None, description="会话标识")
    parent_agent: str | None = Field(default=None, description="上级代理名称")
    team_name: str | None = Field(default=None, description="团队名称")
    permission_snapshot: dict[str, Any] = Field(default_factory=dict, description="权限上下文快照")
    mcp_resources: list[dict[str, Any]] = Field(default_factory=list, description="MCP 资源快照")
    team_snapshot: list[dict[str, Any]] = Field(default_factory=list, description="团队快照")
    runtime_metadata: dict[str, Any] = Field(default_factory=dict, description="运行时扩展数据")


class AgentExecutionRequest(BaseModel):
    """
    代理执行请求。

    该对象把定义、任务、上下文与实际 prompt 串联起来，供执行器稳定消费。
    """

    model_config = ConfigDict(frozen=True)

    definition: AgentDefinition = Field(description="代理定义")
    task: AgentTaskSpec = Field(description="任务描述")
    prompt: str = Field(description="实际执行 prompt")
    context: AgentExecutionContext = Field(description="执行上下文")


class AgentExecutionResult(BaseModel):
    """
    代理执行结果。

    这里保留成功/失败、时间戳、输出文本以及扩展元数据，便于管理器做真实状态汇总。
    """

    model_config = ConfigDict(frozen=True)

    agent_name: str = Field(description="代理名称")
    task_id: str = Field(description="任务标识")
    status: AgentStatus = Field(description="执行状态")
    output: str | None = Field(default=None, description="代理输出文本")
    error_message: str | None = Field(default=None, description="错误信息")
    started_at: datetime = Field(description="开始时间")
    finished_at: datetime = Field(description="结束时间")
    duration_ms: float | None = Field(default=None, description="执行耗时毫秒数")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

    @classmethod
    def success(
        cls,
        agent_name: str,
        task_id: str,
        output: str,
        metadata: dict[str, Any] | None = None,
        started_at: datetime | None = None,
    ) -> "AgentExecutionResult":
        """
        构建成功执行结果。
        """

        start_value = started_at or datetime.now(timezone.utc)
        finished_at = datetime.now(timezone.utc)
        duration_ms = (finished_at - start_value).total_seconds() * 1000.0
        return cls(
            agent_name=agent_name,
            task_id=task_id,
            status="completed",
            output=output,
            started_at=start_value,
            finished_at=finished_at,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    @classmethod
    def failure(
        cls,
        agent_name: str,
        task_id: str,
        error_message: str,
        metadata: dict[str, Any] | None = None,
        started_at: datetime | None = None,
    ) -> "AgentExecutionResult":
        """
        构建失败执行结果。
        """

        start_value = started_at or datetime.now(timezone.utc)
        finished_at = datetime.now(timezone.utc)
        duration_ms = (finished_at - start_value).total_seconds() * 1000.0
        return cls(
            agent_name=agent_name,
            task_id=task_id,
            status="failed",
            error_message=error_message,
            started_at=start_value,
            finished_at=finished_at,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )


class AgentRunMessage(BaseModel):
    """
    代理运行消息对象。

    该模型用于记录一次 agent run 生命周期内的真实消息轨迹，
    既保留用户追加输入，也保留系统事件与代理输出，便于后续 resume、
    审计以及和 swarm 邮箱进行对照。
    """

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(description="运行消息唯一标识")
    role: AgentRunMessageRole = Field(description="运行消息角色")
    content: str = Field(description="运行消息内容")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="消息创建时间")
    consumed_at: datetime | None = Field(default=None, description="该条用户输入被 wait 消费的时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="运行消息扩展元数据")


class AgentRunRecord(BaseModel):
    """
    代理运行记录对象。

    该模型对应单个可持久化的 agent run 实体，负责把 spawn、send、wait、
    resume、close 全链路状态落盘到真实文件系统中，而不是只保存在内存。
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(description="运行唯一标识")
    agent_name: str = Field(description="归属代理名称")
    team_name: str | None = Field(default=None, description="归属团队名称")
    task: AgentTaskSpec = Field(description="运行绑定的任务快照")
    status: AgentRunStatus = Field(description="运行状态")
    session_id: str | None = Field(default=None, description="已绑定的真实会话标识")
    parent_run_id: str | None = Field(default=None, description="父级运行标识")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="运行创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="运行更新时间")
    started_at: datetime | None = Field(default=None, description="首次进入 running 的时间")
    finished_at: datetime | None = Field(default=None, description="最后一次执行结束时间")
    closed_at: datetime | None = Field(default=None, description="运行关闭时间")
    close_reason: str | None = Field(default=None, description="关闭原因")
    latest_output: str | None = Field(default=None, description="最近一次代理输出")
    last_error_message: str | None = Field(default=None, description="最近一次错误信息")
    messages: list[AgentRunMessage] = Field(default_factory=list, description="运行消息时间线")
    metadata: dict[str, Any] = Field(default_factory=dict, description="运行扩展元数据")
