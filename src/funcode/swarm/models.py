"""
模块名称：swarm.models
功能描述：
    定义团队、任务、邮箱消息以及协作层快照的结构化数据模型。
    该模块服务于真实持久化层，所有字段都必须能够从磁盘或运行时状态中推导。

主要组件：
    - SwarmTeam: 团队定义
    - SwarmTask: 团队任务
    - SwarmTaskUpdate: 任务更新对象
    - SwarmMessage: 团队消息对象
    - SwarmTeamSummary: 团队汇总
    - SwarmMailboxSnapshot: 邮箱快照
    - SwarmWorkspaceSnapshot: 工作区 swarm 快照

依赖说明：
    - datetime: 时间戳建模
    - typing: 类型标注
    - pydantic: 数据建模

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现团队与任务模型
    - 2026-04-01 JucieOvo: 增加团队/任务/消息汇总快照字段
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SwarmTaskStatus = Literal["pending", "blocked", "in_progress", "completed", "failed", "cancelled"]
SwarmMessageType = Literal["note", "question", "answer", "update", "task"]


class SwarmTeam(BaseModel):
    """
    团队定义对象。
    """

    model_config = ConfigDict(frozen=True)

    team_name: str = Field(description="团队名称")
    description: str = Field(description="团队描述")
    workspace_dir: str = Field(description="工作区目录")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="更新时间")
    source: str = Field(default="workspace", description="来源标识")
    tags: list[str] = Field(default_factory=list, description="团队标签")
    task_count: int = Field(default=0, ge=0, description="任务总数")
    open_task_count: int = Field(default=0, ge=0, description="未完成任务数")
    blocked_task_count: int = Field(default=0, ge=0, description="被编排门控阻塞的任务数")
    completed_task_count: int = Field(default=0, ge=0, description="已完成任务数")
    failed_task_count: int = Field(default=0, ge=0, description="失败任务数")
    last_activity_at: datetime | None = Field(default=None, description="最近活动时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SwarmTask(BaseModel):
    """
    团队任务对象。
    """

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(description="任务标识")
    team_name: str = Field(description="团队名称")
    subject: str = Field(description="任务主题")
    detail: str = Field(description="任务说明")
    owner: str | None = Field(default=None, description="归属代理")
    status: SwarmTaskStatus = Field(default="pending", description="任务状态")
    dependencies: list[str] = Field(default_factory=list, description="依赖任务列表")
    labels: list[str] = Field(default_factory=list, description="任务标签")
    priority: int = Field(default=0, ge=0, description="任务优先级")
    attempt_count: int = Field(default=0, ge=0, description="尝试次数")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="更新时间")
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    source_path: str | None = Field(default=None, description="磁盘来源路径")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SwarmTaskUpdate(BaseModel):
    """
    任务更新对象。
    """

    model_config = ConfigDict(frozen=True)

    owner: str | None = Field(default=None, description="更新后的归属代理")
    status: SwarmTaskStatus | None = Field(default=None, description="更新后的任务状态")
    detail: str | None = Field(default=None, description="更新后的任务说明")
    labels: list[str] | None = Field(default=None, description="更新后的任务标签")
    priority: int | None = Field(default=None, ge=0, description="更新后的优先级")
    attempt_count: int | None = Field(default=None, ge=0, description="更新后的尝试次数")
    metadata: dict[str, Any] | None = Field(default=None, description="更新后的扩展元数据")


class SwarmMessage(BaseModel):
    """
    团队消息对象。
    """

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(description="消息标识")
    team_name: str = Field(description="团队名称")
    sender: str = Field(description="发送方")
    recipient: str = Field(description="接收方")
    subject: str = Field(description="消息主题")
    body: str = Field(description="消息正文")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="创建时间")
    read_at: datetime | None = Field(default=None, description="读取时间")
    reply_to: str | None = Field(default=None, description="回复目标消息")
    thread_id: str | None = Field(default=None, description="消息线程标识")
    message_type: SwarmMessageType = Field(default="note", description="消息类型")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class SwarmTeamSummary(BaseModel):
    """
    团队汇总视图。
    """

    model_config = ConfigDict(frozen=True)

    team: SwarmTeam = Field(description="团队定义")
    tasks: list[SwarmTask] = Field(default_factory=list, description="团队任务列表")
    message_count: int = Field(default=0, ge=0, description="团队消息数")
    open_task_count: int = Field(default=0, ge=0, description="未完成任务数")
    blocked_task_count: int = Field(default=0, ge=0, description="阻塞任务数")
    completed_task_count: int = Field(default=0, ge=0, description="已完成任务数")
    failed_task_count: int = Field(default=0, ge=0, description="失败任务数")


class SwarmMailboxSnapshot(BaseModel):
    """
    邮箱快照对象。
    """

    model_config = ConfigDict(frozen=True)

    mailbox_path: str = Field(description="邮箱文件路径")
    message_count: int = Field(default=0, ge=0, description="消息总数")
    recipient_counts: dict[str, int] = Field(default_factory=dict, description="按接收方统计")
    team_counts: dict[str, int] = Field(default_factory=dict, description="按团队统计")
    latest_message_at: datetime | None = Field(default=None, description="最近消息时间")


class SwarmWorkspaceSnapshot(BaseModel):
    """
    工作区 swarm 快照。
    """

    model_config = ConfigDict(frozen=True)

    workspace_dir: str = Field(description="工作区目录")
    team_count: int = Field(default=0, ge=0, description="团队数")
    task_count: int = Field(default=0, ge=0, description="任务数")
    message_count: int = Field(default=0, ge=0, description="消息数")
    teams: list[SwarmTeamSummary] = Field(default_factory=list, description="团队汇总列表")
    mailbox: SwarmMailboxSnapshot | None = Field(default=None, description="邮箱快照")
