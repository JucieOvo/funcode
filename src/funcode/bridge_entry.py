"""
模块名称：bridge_entry
功能描述：
    提供独立的 Python 桥接入口，便于直接以模块方式启动 stdio NDJSON 服务。

主要组件：
    - main: 桥接入口函数。

依赖说明：
    - funcode.bridge: 桥接服务入口。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 新增独立桥接入口。
"""

from __future__ import annotations

from funcode.bridge import run_stdio_bridge


def main(argv: list[str] | None = None) -> int:
    """
    启动 stdio NDJSON 桥接服务。
    :param argv: 预留参数，当前仅保留入口兼容。
    :return: 进程退出码。
    """

    return run_stdio_bridge(argv)


if __name__ == "__main__":
    raise SystemExit(main())

