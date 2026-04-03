"""
模块名称：settings
功能描述：
    定义 Python 版本 Funcode 的运行配置对象。

主要组件：
    - ModelSettings: 模型相关配置。
    - RuntimeSettings: 运行相关配置。
    - CliSettings: CLI 输入配置。
    - AppSettings: 汇总后的应用配置。

依赖说明：
    - pydantic: 数据建模与校验

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化运行配置模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ReasoningEffort = Literal["low", "medium", "high"]


class ModelSettings(BaseModel):
    """
    模型配置。

    :param provider: 模型提供方标识。
    :param model_name: 默认主模型名称。
    :param api_key: 模型 API Key。
    :param base_url: 兼容 OpenAI 的服务基地址。
    :param reasoning_effort: 推理强度。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    provider: str = Field(description="模型提供方标识")
    model_name: str = Field(description="默认主模型名称")
    api_key: str = Field(description="模型 API Key")
    base_url: str = Field(description="兼容 OpenAI 的服务基地址")
    reasoning_effort: ReasoningEffort = Field(description="推理强度")


class RuntimeSettings(BaseModel):
    """
    运行配置。

    :param workspace_dir: 当前工作目录。
    :param session_id: 会话标识。
    :param max_turns: 最大轮次数。
    :param stream: 是否流式输出。
    :param debug: 是否启用调试模式。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    workspace_dir: Path = Field(description="当前工作目录")
    session_id: str | None = Field(default=None, description="会话标识")
    max_turns: int = Field(default=32, ge=1, description="最大轮次数")
    stream: bool = Field(default=True, description="是否启用流式输出")
    debug: bool = Field(default=False, description="是否启用调试模式")


class CliSettings(BaseModel):
    """
    CLI 输入配置。

    :param command: 命令名称。
    :param prompt: 用户输入提示词。
    :param system_prompt: 覆盖系统提示词。
    :param graph_name: 目标状态图名称。
    :param output_format: 输出格式。
    """

    model_config = ConfigDict(frozen=True)

    command: str = Field(description="命令名称")
    prompt: str | None = Field(default=None, description="用户输入提示词")
    system_prompt: str | None = Field(default=None, description="覆盖系统提示词")
    graph_name: str = Field(default="main", description="目标状态图名称")
    output_format: str = Field(default="text", description="输出格式")


class AppSettings(BaseModel):
    """
    汇总后的应用配置。

    :param model: 模型配置。
    :param runtime: 运行配置。
    :param cli: CLI 输入配置。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    model: ModelSettings
    runtime: RuntimeSettings
    cli: CliSettings
