"""
模块名称：commands.models
功能描述：
    定义命令执行层的上下文与结果对象，用于连接 CLI 与 runtime。

主要组件：
    - CommandContext: 命令上下文
    - CommandResult: 命令结果

依赖说明：
    - pydantic: 数据建模与校验

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化命令模型
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from funcode.config.settings import AppSettings


class CommandContext(BaseModel):
    """
    命令上下文对象。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    settings: AppSettings = Field(description="应用配置")
    extras: dict[str, Any] = Field(default_factory=dict, description="扩展上下文")


class CommandResult(BaseModel):
    """
    命令执行结果。
    """

    model_config = ConfigDict(frozen=True)

    exit_code: int = Field(description="退出码")
    output: str | None = Field(default=None, description="标准输出文本")
    payload: dict[str, Any] = Field(default_factory=dict, description="结构化结果")
