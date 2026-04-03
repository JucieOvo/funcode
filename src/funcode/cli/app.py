"""
模块名称：app
功能描述：
    负责 CLI 总入口的参数解析、配置加载与命令分流。
    轻量命令会在加载模型配置之前直接执行，避免被 API Key 阻塞。
主要组件：
    - run_cli: CLI 总入口。
依赖说明：
    - argparse: 命名空间对象。
    - funcode.cli.parser: 参数解析器。
    - funcode.cli.runners: 命令分发器。
    - funcode.config.loader: 配置加载器。
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 为轻量命令增加前置分流。
"""

from __future__ import annotations

from argparse import Namespace

from funcode.cli.parser import LIGHTWEIGHT_COMMANDS, build_parser
from funcode.cli.runners import dispatch_command, dispatch_command_from_namespace
from funcode.config.loader import load_app_settings


def run_cli(argv: list[str] | None = None) -> int:
    """
    运行命令行程序。

    :param argv: 可选参数列表，不传入时使用系统参数。
    :return: 进程退出码。
    """

    parser = build_parser()
    namespace: Namespace = parser.parse_args(argv)

    if getattr(namespace, "command") in LIGHTWEIGHT_COMMANDS:
        return dispatch_command_from_namespace(namespace)

    settings = load_app_settings(namespace)
    return dispatch_command(settings)
