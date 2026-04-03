"""
模块名称：routes
功能描述：
    提供主状态图在规划节点之后的条件路由逻辑，依据统一 GraphState 中的控制字段选择
    后续进入工具节点还是模型节点。

主要组件：
    - route_after_plan: 规划节点后的路由判定函数。

依赖说明：
    - funcode.graph.state: 图状态模型兼容导出。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 适配统一 GraphState 模型。
"""

from __future__ import annotations

from typing import Any

from funcode.graph.state import GraphState


def _ensure_graph_state(state: GraphState | dict[str, Any]) -> GraphState:
    """
    将路由输入标准化为 GraphState 对象。

    这里需要兼容 LangGraph 在不同阶段传入的字典状态与模型实例，
    同时避免因为相同字段但不同导入路径导致的 Pydantic 类型不匹配。
    """

    if isinstance(state, GraphState):
        return state
    if hasattr(state, "model_dump"):
        return GraphState.model_validate(state.model_dump(mode="python"))
    return GraphState.model_validate(state)


def route_after_plan(state: GraphState | dict[str, Any]) -> str:
    """
    根据规划结果决定进入工具节点还是 LLM 节点。

    :param state: 当前图状态。
    :return: 路由名称。
    """

    resolved_state = _ensure_graph_state(state)
    if resolved_state.requires_tools:
        return "tools"
    return "llm"
