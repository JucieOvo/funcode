"""
模块名称：commands.registry
功能描述：
    提供命令注册表，用于在不依赖 CLI 解析器的情况下，复用命令处理逻辑。

主要组件：
    - CommandRegistry: 命令注册表

依赖说明：
    - funcode.commands.models: 命令上下文与结果对象

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化命令注册表
"""

from __future__ import annotations

from collections.abc import Callable

from funcode.commands.models import CommandContext, CommandResult


CommandHandler = Callable[[CommandContext], CommandResult]


class CommandRegistry:
    """
    命令注册表。
    """

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, command_name: str, handler: CommandHandler) -> None:
        """
        注册命令处理器。
        """

        if command_name in self._handlers:
            raise ValueError(f"命令已存在，禁止重复注册：{command_name}")
        self._handlers[command_name] = handler

    def execute(self, command_name: str, context: CommandContext) -> CommandResult:
        """
        执行已注册命令。
        """

        try:
            handler = self._handlers[command_name]
        except KeyError as exc:
            raise KeyError(f"未注册的命令：{command_name}") from exc
        return handler(context)

    def list_commands(self) -> list[str]:
        """
        列出全部命令名称。
        """

        return sorted(self._handlers.keys())
