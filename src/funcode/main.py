"""
模块名称：main
功能描述：
    Python 版本 Funcode 的进程入口模块，负责在原有 CLI 与新的 stdio 桥接入口之间分流。

主要组件：
    - main: 命令行主入口函数。

依赖说明：
    - sys: 进程参数分流。
    - funcode.bridge_entry: stdio NDJSON 桥接入口。
    - funcode.cli.app: 既有 CLI 入口。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 为 bridge/stdio 入口增加前置分流。
"""

from __future__ import annotations

import sys

from funcode.bridge_entry import main as run_bridge_entry
from funcode.cli.app import run_cli


def main(argv: list[str] | None = None) -> int:
    """
    启动命令行程序。
    :param argv: 可选参数列表；为空时使用当前进程的命令行参数。
    :return: 进程退出码。
    """

    resolved_argv = list(sys.argv[1:] if argv is None else argv)
    if resolved_argv and resolved_argv[0] in {"bridge", "stdio", "ink-bridge", "tui-bridge"}:
        return run_bridge_entry(resolved_argv[1:])
    return run_cli(resolved_argv)


if __name__ == "__main__":
    raise SystemExit(main())
