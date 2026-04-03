"""
模块名称：graph
功能描述：
    提供 Python 版 Funcode 的 LangGraph 主图构建能力与状态对象导出。

主要组件：
    - GraphState: 主图状态类型。
    - build_main_graph: 主图构建函数。

依赖说明：
    - funcode.graph.builder: 主图编译逻辑。
    - funcode.graph.state: 图状态定义。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 graph 模块导出。
"""

from funcode.graph.builder import build_main_graph
from funcode.graph.state import GraphState

__all__ = [
    "GraphState",
    "build_main_graph",
]
