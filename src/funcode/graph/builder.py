"""
模块名称：builder
功能描述：
    负责构建 Funcode Python 版本的主状态图，并将图节点、路由规则与统一的 GraphState
    模型组织为单一编译入口，供 runtime 应用层调用。

主要组件：
    - build_main_graph: 构建并编译主状态图。

依赖说明：
    - langgraph.graph: 状态图编排。
    - funcode.graph.nodes: 节点实现。
    - funcode.graph.routes: 路由逻辑。
    - funcode.graph.state: 统一图状态模型。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 切换到统一 GraphState 模型并保留主图工厂。
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from funcode.graph.nodes import GraphNodeDependencies, create_default_dependencies
from funcode.graph.routes import route_after_plan
from funcode.graph.state import GraphState


def build_main_graph(dependencies: GraphNodeDependencies | None = None):
    """
    构建主状态图。

    :param dependencies: 节点依赖集合。
    :return: 编译后的 LangGraph 对象。
    """

    resolved_dependencies = dependencies or create_default_dependencies()
    graph = StateGraph(GraphState)
    graph.add_node("prepare", resolved_dependencies.prepare_node)
    graph.add_node("plan", resolved_dependencies.plan_node)
    graph.add_node("tools", resolved_dependencies.tools_node)
    graph.add_node("llm", resolved_dependencies.llm_node)
    graph.add_node("finalize", resolved_dependencies.finalize_node)

    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "plan")
    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {
            "tools": "tools",
            "llm": "llm",
        },
    )
    graph.add_edge("tools", "llm")
    graph.add_edge("llm", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
