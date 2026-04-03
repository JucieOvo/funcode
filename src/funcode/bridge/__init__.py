"""
模块名称：bridge
功能描述：
    汇总 Python 侧的真实桥接能力，向外提供基于 stdio NDJSON 的入口函数。

主要组件：
    - NDJSONBridgeServer: 桥接服务实现。
    - run_stdio_bridge: 桥接服务启动入口。

依赖说明：
    - funcode.bridge.server: 桥接核心实现。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化桥接包导出。
"""

from __future__ import annotations

from .server import NDJSONBridgeServer, build_doctor_payload, build_help_payload, build_run_payload, run_stdio_bridge

__all__ = [
    "NDJSONBridgeServer",
    "build_doctor_payload",
    "build_help_payload",
    "build_run_payload",
    "run_stdio_bridge",
]

