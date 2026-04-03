"""
模块名称：commands.service
功能描述：
    提供默认命令服务，把注册表与处理器组装在一起，供 CLI 或其他入口复用。

主要组件：
    - create_default_registry: 创建默认命令注册表
    - execute_command: 执行命令

依赖说明：
    - funcode.commands.handlers: 默认命令处理器
    - funcode.commands.registry: 命令注册表

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化默认命令服务
"""

from __future__ import annotations

from funcode.commands.handlers import (
    handle_agents_command,
    handle_brief_command,
    handle_clear_command,
    handle_compact_command,
    handle_chat_command,
    handle_config_command,
    handle_context_command,
    handle_env_command,
    handle_files_command,
    handle_help_command,
    handle_skills_command,
    handle_messages_command,
    handle_plugin_command,
    handle_reload_plugins_command,
    handle_stats_command,
    handle_doctor_command,
    handle_memory_command,
    handle_mcp_command,
    handle_plan_command,
    handle_permissions_command,
    handle_usage_command,
    handle_review_command,
    handle_model_command,
    handle_status_command,
    handle_summary_command,
    handle_session_command,
    handle_tasks_command,
    handle_teams_command,
    handle_tools_command,
    handle_resume_command,
    handle_run_command,
)
from funcode.commands.models import CommandContext, CommandResult
from funcode.commands.registry import CommandRegistry


def create_default_registry() -> CommandRegistry:
    """
    创建默认命令注册表。
    """

    registry = CommandRegistry()
    registry.register("run", handle_run_command)
    registry.register("review", handle_review_command)
    registry.register("agents", handle_agents_command)
    registry.register("chat", handle_chat_command)
    registry.register("config", handle_config_command)
    registry.register("help", handle_help_command)
    registry.register("status", handle_status_command)
    registry.register("files", handle_files_command)
    registry.register("skills", handle_skills_command)
    registry.register("tasks", handle_tasks_command)
    registry.register("memory", handle_memory_command)
    registry.register("plan", handle_plan_command)
    registry.register("summary", handle_summary_command)
    registry.register("doctor", handle_doctor_command)
    registry.register("model", handle_model_command)
    registry.register("plugin", handle_plugin_command)
    registry.register("reload-plugins", handle_reload_plugins_command)
    registry.register("env", handle_env_command)
    registry.register("brief", handle_brief_command)
    registry.register("permissions", handle_permissions_command)
    registry.register("usage", handle_usage_command)
    registry.register("stats", handle_stats_command)
    registry.register("context", handle_context_command)
    registry.register("session", handle_session_command)
    registry.register("mcp", handle_mcp_command)
    registry.register("tools", handle_tools_command)
    registry.register("teams", handle_teams_command)
    registry.register("messages", handle_messages_command)
    registry.register("resume", handle_resume_command)
    registry.register("compact", handle_compact_command)
    registry.register("clear", handle_clear_command)
    return registry


def execute_command(command_name: str, context: CommandContext) -> CommandResult:
    """
    执行默认命令集合中的某个命令。
    """

    return create_default_registry().execute(command_name, context)
