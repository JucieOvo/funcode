"""
模块名称：commands.__init__
功能描述：
    暴露命令层公共接口，包括命令上下文、命令结果、命令注册表与
    默认命令执行服务。

主要组件：
    - CommandContext: 命令上下文
    - CommandResult: 命令执行结果
    - CommandRegistry: 命令注册表

依赖说明：
    - funcode.commands.models: 命令模型
    - funcode.commands.registry: 命令注册表
    - funcode.commands.service: 默认命令服务

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 commands 包导出
"""

from funcode.commands.models import CommandContext, CommandResult
from funcode.commands.registry import CommandRegistry
from funcode.commands.handlers import (
    COMMAND_SUMMARIES,
    handle_agents_command,
    handle_brief_command,
    handle_clear_command,
    handle_compact_command,
    handle_context_command,
    handle_doctor_command,
    handle_chat_command,
    handle_config_command,
    handle_env_command,
    handle_files_command,
    handle_help_command,
    handle_skills_command,
    handle_messages_command,
    handle_plugin_command,
    handle_stats_command,
    handle_memory_command,
    handle_mcp_command,
    handle_plan_command,
    handle_permissions_command,
    handle_usage_command,
    handle_review_command,
    handle_reload_plugins_command,
    handle_run_command,
    handle_model_command,
    handle_status_command,
    handle_summary_command,
    handle_session_command,
    handle_resume_command,
    handle_tasks_command,
    handle_teams_command,
    handle_tools_command,
)
from funcode.commands.service import create_default_registry, execute_command

__all__ = [
    "COMMAND_SUMMARIES",
    "CommandContext",
    "CommandRegistry",
    "CommandResult",
    "create_default_registry",
    "execute_command",
    "handle_agents_command",
    "handle_brief_command",
    "handle_clear_command",
    "handle_compact_command",
    "handle_doctor_command",
    "handle_context_command",
    "handle_chat_command",
    "handle_config_command",
    "handle_env_command",
    "handle_files_command",
    "handle_help_command",
    "handle_skills_command",
    "handle_messages_command",
    "handle_plugin_command",
    "handle_stats_command",
    "handle_memory_command",
    "handle_mcp_command",
    "handle_plan_command",
    "handle_permissions_command",
    "handle_usage_command",
    "handle_review_command",
    "handle_reload_plugins_command",
    "handle_run_command",
    "handle_model_command",
    "handle_status_command",
    "handle_summary_command",
    "handle_session_command",
    "handle_resume_command",
    "handle_tasks_command",
    "handle_teams_command",
    "handle_tools_command",
]
