"""
模块名称：parser
功能描述：
    定义 Funcode Python 版本的命令行参数结构。
    该模块只负责参数解析，不承担运行时加载或命令执行逻辑。
主要组件：
    - build_parser: 创建 argparse 解析器
    - CLI_COMMANDS: 支持的完整命令列表
    - LIGHTWEIGHT_COMMANDS: 可在 CLI 层直接处理的轻量命令列表
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 重建 CLI 参数解析器，修复字符串断裂问题
"""

from __future__ import annotations

import argparse

from funcode.commands.service import create_default_registry
from funcode.constants.metadata import PROJECT_NAME, PROJECT_VERSION


CLI_COMMANDS: tuple[str, ...] = tuple(create_default_registry().list_commands())

LIGHTWEIGHT_COMMANDS: tuple[str, ...] = tuple(
    command_name
    for command_name in CLI_COMMANDS
    if command_name not in {"run", "review", "chat", "config"}
)


def _add_shared_options(parser: argparse.ArgumentParser) -> None:
    """
    为命令添加通用参数。

    :param parser: 需要扩展的命令解析器。
    """

    parser.add_argument("--cwd", dest="cwd", help="工作目录，默认使用当前目录")
    parser.add_argument("--model", dest="model", help="主模型名称，默认 deepseek-reasoner")
    parser.add_argument("--api-key", dest="api_key", help="模型 API Key，优先从环境变量读取")
    parser.add_argument("--base-url", dest="base_url", help="模型服务基地址")
    parser.add_argument(
        "--reasoning-effort",
        dest="reasoning_effort",
        choices=("low", "medium", "high"),
        help="模型推理强度",
    )
    parser.add_argument("--session-id", dest="session_id", help="会话 ID")
    parser.add_argument("--max-turns", dest="max_turns", type=int, default=32, help="最大对话轮次")
    parser.add_argument("--no-stream", dest="stream", action="store_false", help="关闭流式输出")
    parser.add_argument("--debug", dest="debug", action="store_true", help="启用调试模式")


def _add_display_options(parser: argparse.ArgumentParser, default_output_format: str) -> None:
    """
    为只读命令添加展示参数。

    :param parser: 需要扩展的命令解析器。
    :param default_output_format: 默认输出格式。
    """

    parser.add_argument("--graph-name", dest="graph_name", default="main", help="目标图名称")
    parser.add_argument(
        "--output-format",
        dest="output_format",
        choices=("text", "json"),
        default=default_output_format,
        help="输出格式",
    )


def _add_prompt_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    prompt_help: str,
) -> None:
    """
    创建需要 prompt 的命令。

    :param subparsers: 子命令容器。
    :param name: 命令名。
    :param help_text: 子命令帮助文本。
    :param prompt_help: prompt 参数帮助文本。
    """

    parser = subparsers.add_parser(name, help=help_text)
    _add_shared_options(parser)
    parser.add_argument("--prompt", required=True, help=prompt_help)
    parser.add_argument("--system-prompt", dest="system_prompt", help="覆盖系统提示词")
    _add_display_options(parser, default_output_format="text")


def _add_lightweight_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    default_output_format: str = "text",
) -> None:
    """
    创建轻量命令。

    :param subparsers: 子命令容器。
    :param name: 命令名。
    :param help_text: 子命令帮助文本。
    :param default_output_format: 默认输出格式。
    """

    parser = subparsers.add_parser(name, help=help_text)
    _add_shared_options(parser)
    _add_display_options(parser, default_output_format=default_output_format)


def build_parser() -> argparse.ArgumentParser:
    """
    创建顶层命令行解析器。

    :return: 完成初始化的 argparse 解析器。
    """

    parser = argparse.ArgumentParser(
        prog=PROJECT_NAME,
        description="Funcode 的 Python + LangChain + LangGraph 实现",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {PROJECT_VERSION}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_prompt_command(subparsers, "run", "执行一次完整代理运行", "用户输入提示词")
    _add_prompt_command(subparsers, "review", "以审查视角执行一次完整代理运行", "待审查的原始提示词")
    _add_lightweight_command(subparsers, "chat", "启动交互式聊天模式", default_output_format="text")

    config_parser = subparsers.add_parser("config", help="输出解析后的配置")
    _add_shared_options(config_parser)
    _add_display_options(config_parser, default_output_format="json")

    lightweight_specs = (
        ("help", "显示可用命令", "text"),
        ("status", "输出运行状态", "json"),
        ("files", "列出工作区文件", "json"),
        ("tasks", "输出任务概况", "json"),
        ("memory", "输出会话记忆摘要", "json"),
        ("plan", "输出计划步骤", "json"),
        ("session", "输出会话仓库概况", "json"),
        ("resume", "恢复最近会话概况", "json"),
        ("compact", "压缩当前会话上下文", "json"),
        ("clear", "清理会话缓存文件", "json"),
        ("mcp", "输出 MCP 资源列表", "json"),
        ("tools", "输出工具列表", "json"),
        ("summary", "输出会话摘要", "json"),
        ("doctor", "输出运行环境检查结果", "json"),
        ("model", "输出模型配置", "json"),
        ("permissions", "输出权限上下文", "json"),
        ("usage", "输出使用概况", "json"),
        ("stats", "输出工作区统计", "json"),
        ("context", "输出运行上下文", "json"),
    )
    lightweight_specs = lightweight_specs + (
        ("teams", "输出团队列表", "json"),
        ("messages", "输出邮箱消息", "json"),
    )

    lightweight_specs = lightweight_specs + (
        ("agents", "输出可见代理列表", "json"),
        ("skills", "输出 skills 目录概况", "json"),
        ("plugin", "输出扩展面与注册概况", "json"),
        ("reload-plugins", "重新扫描技能、插件与命令视图", "json"),
    )

    lightweight_specs = lightweight_specs + (
        ("env", "输出当前进程与工作空间环境", "text"),
        ("brief", "输出当前工作区有关摘要", "text"),
    )

    for name, help_text, default_output_format in lightweight_specs:
        _add_lightweight_command(
            subparsers,
            name=name,
            help_text=help_text,
            default_output_format=default_output_format,
        )

    return parser
