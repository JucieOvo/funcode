"""
模块名称：permissions.context
功能描述：
    定义工具权限上下文，统一描述工作区、运行时目录以及 plan mode 相关真实路径。

主要组件：
    - PermissionContext: 权限上下文模型。
    - create_permission_context: 基于应用配置构建权限上下文。

依赖说明：
    - pathlib: 路径处理。
    - pydantic: 数据建模。
    - funcode.config.settings: 应用配置。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 补齐 plan mode 路径字段与构造逻辑。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from funcode.config.settings import AppSettings


class PermissionContext(BaseModel):
    """
    工具权限上下文。
    该对象只承载真实目录和真实文件路径，不包含任何伪造状态。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    workspace_dir: Path = Field(description="工作区目录")
    runtime_dir: Path = Field(description="运行时根目录")
    plan_dir: Path = Field(description="plan mode 目录")
    plan_mode_state_path: Path = Field(description="plan mode 状态文件路径")
    plan_mode_plan_path: Path = Field(description="plan mode 计划文件路径")
    questions_dir: Path = Field(description="提问记录目录")
    swarm_dir: Path = Field(description="协作层目录")
    mailbox_path: Path = Field(description="共享邮箱文件路径")
    session_dir: Path = Field(description="会话持久化目录")
    additional_allowed_directories: tuple[Path, ...] = Field(
        default=(),
        description="额外允许访问的目录集合",
    )
    allow_powershell: bool = Field(default=True, description="是否允许执行 PowerShell")
    workspace_exists: bool = Field(default=True, description="工作区是否存在")
    workspace_name: str = Field(default="", description="工作区名称")

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        """
        返回真实允许访问的根目录集合。

        :return: 允许访问的根目录元组。
        """

        return (self.workspace_dir, *self.additional_allowed_directories)


def create_permission_context(settings: AppSettings) -> PermissionContext:
    """
    根据应用配置生成真实权限上下文。

    :param settings: 应用配置。
    :return: 权限上下文对象。
    """

    workspace_dir = settings.runtime.workspace_dir.resolve()
    runtime_dir = workspace_dir / ".funcode"
    plan_dir = runtime_dir / "plan"
    plan_mode_state_path = plan_dir / "state.json"
    plan_mode_plan_path = plan_dir / "plan.md"
    questions_dir = runtime_dir / "questions"
    swarm_dir = runtime_dir / "swarm"
    session_dir = runtime_dir / "sessions"
    mailbox_path = swarm_dir / "mailbox.jsonl"

    extra_dirs: list[Path] = []
    for candidate in (
        runtime_dir,
        plan_dir,
        questions_dir,
        swarm_dir,
        session_dir,
        mailbox_path.parent,
    ):
        if candidate.exists() and candidate not in extra_dirs:
            extra_dirs.append(candidate)

    return PermissionContext(
        workspace_dir=workspace_dir,
        runtime_dir=runtime_dir,
        plan_dir=plan_dir,
        plan_mode_state_path=plan_mode_state_path,
        plan_mode_plan_path=plan_mode_plan_path,
        questions_dir=questions_dir,
        swarm_dir=swarm_dir,
        mailbox_path=mailbox_path,
        session_dir=session_dir,
        additional_allowed_directories=tuple(extra_dirs),
        allow_powershell=True,
        workspace_exists=workspace_dir.exists(),
        workspace_name=workspace_dir.name,
    )
