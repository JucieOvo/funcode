"""
模块名称：base
功能描述：
    定义 Python 版 Funcode 的工具抽象基类与结果对象，供内置工具和未来 LangChain
    工具适配复用。

主要组件：
    - ToolResult: 工具结果模型。
    - BaseTool: 工具抽象基类。

依赖说明：
    - abc: 抽象基类。
    - pydantic: 数据模型。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化工具抽象基类。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from funcode.tools.context import ToolExecutionContext


class ToolResult(BaseModel):
    """
    工具执行结果。

    :param tool_name: 工具名称。
    :param content: 工具返回文本。
    :param metadata: 结果元数据。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tool_name: str = Field(description="工具名称")
    content: str = Field(description="工具返回文本")
    metadata: dict[str, Any] = Field(default_factory=dict, description="结果元数据")


class BaseTool(ABC):
    """
    工具抽象基类。
    """

    name: str
    description: str

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        """
        执行工具。

        :param arguments: 工具参数。
        :param context: 工具执行上下文。
        :return: 工具结果。
        """
