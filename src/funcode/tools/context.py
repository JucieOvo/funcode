"""
模块名称：context
功能描述：
    定义工具执行期间共享的上下文对象，承载配置、权限、计划状态与 MCP 注册中心。

主要组件：
    - ToolExecutionContext: 工具执行上下文模型。

依赖说明：
    - pydantic: 数据模型。
    - funcode.config.settings: 应用配置。
    - funcode.permissions.context: 权限上下文。
    - funcode.mcp.registry: MCP 注册中心。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化工具执行上下文。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from funcode.config.settings import AppSettings
from funcode.mcp.registry import McpRegistry
from funcode.permissions.context import PermissionContext


class ToolExecutionContext(BaseModel):
    """
    工具执行上下文。

    :param settings: 应用配置。
    :param permission_context: 权限上下文。
    :param mcp_registry: MCP 注册中心。
    :param plan_steps: 当前计划步骤。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    settings: AppSettings = Field(description="应用配置")
    permission_context: PermissionContext = Field(description="权限上下文")
    mcp_registry: McpRegistry = Field(description="MCP 注册中心")
    plan_steps: list[str] = Field(default_factory=list, description="当前计划步骤")

    @property
    def workspace_dir(self) -> Path:
        """
        返回工作区目录。

        :return: 工作区目录。
        """

        return self.settings.runtime.workspace_dir.resolve()
