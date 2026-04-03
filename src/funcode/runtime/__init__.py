"""
模块名称：funcode.runtime
功能描述：
    提供运行时应用层的懒加载导出，避免在包初始化阶段提前引入完整执行图，
    从而打断 tools / runtime / graph 之间的循环依赖。

主要组件：
    - FuncodeApplication: 运行时编排器。
    - run_once: 单次执行入口。
    - run_interactive: 交互式执行入口。

依赖说明：
    - funcode.runtime.application: 真实运行时实现。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 改为懒加载导出，打断运行时循环导入。
"""

from __future__ import annotations

from typing import Any

__all__ = ["FuncodeApplication", "run_interactive", "run_once"]


def __getattr__(name: str) -> Any:
    """
    按需导入运行时对象。

    该实现避免 runtime 包在导入时立刻拉起完整应用图，防止和 tools / graph
    之间形成循环导入。

    :param name: 访问的属性名。
    :return: 对应的运行时对象。
    :raises AttributeError: 当属性不存在时触发。
    """

    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from funcode.runtime.application import FuncodeApplication, run_interactive, run_once

    exports = {
        "FuncodeApplication": FuncodeApplication,
        "run_once": run_once,
        "run_interactive": run_interactive,
    }
    return exports[name]
