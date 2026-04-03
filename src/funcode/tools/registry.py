"""
模块名称：registry
功能描述：
    提供 Funcode Python 版的工具注册中心与执行入口。
    本模块改为懒导入工具实现，避免在导入 registry 模块时立刻触发整棵工具依赖树，
    从而降低主工作区的循环导入风险。

主要组件：
    - ToolRegistry: 工具注册中心。
    - create_default_tool_registry: 构建默认工具集合。

依赖说明：
    - funcode.tools.base: 工具基类与结果模型。
    - funcode.tools.context: 工具执行上下文。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 改为懒导入实现，修复主工作区可见性问题。
"""

from __future__ import annotations

from typing import Iterable

from funcode.tools.base import BaseTool, ToolResult
from funcode.tools.context import ToolExecutionContext


class ToolRegistry:
    """
    工具注册中心。
    """

    def __init__(self, tools: Iterable[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: BaseTool) -> None:
        """
        注册工具实例。

        :param tool: 工具实例。
        """

        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> BaseTool:
        """
        获取工具实例。

        :param tool_name: 工具名称。
        :return: 工具实例。
        :raises KeyError: 当工具不存在时触发。
        """

        return self._tools[tool_name]

    def list_tools(self) -> list[str]:
        """
        列出全部工具名称。

        :return: 工具名称列表。
        """

        return sorted(self._tools.keys())

    def execute(self, tool_name: str, arguments: dict[str, object], context: ToolExecutionContext) -> ToolResult:
        """
        执行指定工具。

        :param tool_name: 工具名称。
        :param arguments: 工具参数。
        :param context: 工具执行上下文。
        :return: 工具执行结果。
        """

        tool = self.get(tool_name)
        return tool.execute(arguments=arguments, context=context)


def create_default_tool_registry() -> ToolRegistry:
    """
    构建默认工具集合。

    这里使用函数内部导入，避免模块导入阶段触发不必要的依赖初始化。

    :return: 完成注册的工具注册中心。
    """

    from funcode.tools.advanced import (
        EnterPlanModeTool,
        EnterWorktreeTool,
        ExitPlanModeTool,
        ExitWorktreeTool,
        LspTool,
        REPLTool,
        ScheduleCronTool,
    )
    from funcode.tools.builtin import (
        AgentCreateTool,
        AgentDeleteTool,
        AgentGetTool,
        AgentListTool,
        AgentUpdateTool,
        AskUserQuestionTool,
        BriefTool,
        DirectoryListTool,
        FileEditTool,
        FileReadTool,
        FileWriteTool,
        GlobTool,
        GrepTool,
        ListMcpResourcesTool,
        McpResourceReadTool,
        PlanUpdateTool,
        PowerShellCommandTool,
        SendMessageTool,
        SkillTool,
        SleepTool,
        TaskCreateTool,
        TaskGetTool,
        TaskListTool,
        TaskOutputTool,
        TaskStopTool,
        TaskUpdateTool,
        TeamCreateTool,
        TeamDeleteTool,
        TeamGetTool,
        TeamListTool,
        TodoWriteTool,
        ToolSearchTool,
        WebFetchTool,
        WebSearchTool,
    )

    return ToolRegistry(
        tools=[
            BriefTool(),
            AgentListTool(),
            AgentGetTool(),
            AgentCreateTool(),
            AgentUpdateTool(),
            AgentDeleteTool(),
            AskUserQuestionTool(),
            FileReadTool(),
            DirectoryListTool(),
            GlobTool(),
            GrepTool(),
            FileWriteTool(),
            FileEditTool(),
            PowerShellCommandTool(),
            PlanUpdateTool(),
            McpResourceReadTool(),
            ListMcpResourcesTool(),
            TaskListTool(),
            TaskGetTool(),
            TaskUpdateTool(),
            TaskStopTool(),
            TaskCreateTool(),
            TaskOutputTool(),
            TeamListTool(),
            TeamGetTool(),
            TeamCreateTool(),
            TeamDeleteTool(),
            SendMessageTool(),
            LspTool(),
            EnterPlanModeTool(),
            ExitPlanModeTool(),
            EnterWorktreeTool(),
            ExitWorktreeTool(),
            ScheduleCronTool(),
            REPLTool(),
            TodoWriteTool(),
            SkillTool(),
            WebFetchTool(),
            WebSearchTool(),
            ToolSearchTool(),
            SleepTool(),
        ]
    )
