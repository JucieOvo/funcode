"""
模块名称：nodes
功能描述：
    提供主状态图节点实现，包括输入准备、工具规划、工具执行、模型调用与结果收敛。
    该模块基于统一的 GraphState、MessageRecord、ToolCallRecord 模型组织节点间状态流转。

主要组件：
    - GraphNodeDependencies: 节点依赖封装。
    - create_default_dependencies: 默认节点依赖工厂。

依赖说明：
    - dataclasses: 节点依赖封装。
    - funcode.tools.registry: 工具注册中心。
    - funcode.utils.importing: 延迟导入工具。
    - funcode.schemas: 统一状态模型。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 切换为统一 Pydantic 状态模型。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from funcode.config.settings import AppSettings, CliSettings, ModelSettings, RuntimeSettings
from funcode.constants.models import DEFAULT_CHAT_MODEL, DEFAULT_DEEPSEEK_BASE_URL
from funcode.mcp.registry import McpRegistry, McpResource
from funcode.permissions.context import create_permission_context
from funcode.schemas import GraphState, MessageRecord, ToolCallRecord
from funcode.tools.context import ToolExecutionContext
from funcode.tools.registry import create_default_tool_registry
from funcode.utils.importing import optional_import


def _ensure_graph_state(state: GraphState | dict[str, Any]) -> GraphState:
    """
    将输入状态标准化为 GraphState 对象。

    :param state: 原始状态对象或字典。
    :return: 标准化后的 GraphState 对象。
    """

    if isinstance(state, GraphState):
        return state
    if hasattr(state, "model_dump"):
        return GraphState.model_validate(state.model_dump(mode="python"))
    return GraphState.model_validate(state)


def _parse_tool_instruction(user_input: str) -> list[ToolCallRecord]:
    """
    基于命令前缀从用户输入中解析工具调用记录。

    :param user_input: 用户输入。
    :return: 工具调用记录列表。
    """

    stripped = user_input.strip()
    if stripped.startswith("/read "):
        return [ToolCallRecord(tool_name="file_read", arguments={"path": stripped[6:].strip()})]
    if stripped.startswith("/ls"):
        path_value = stripped[3:].strip() or "."
        return [ToolCallRecord(tool_name="list_directory", arguments={"path": path_value})]
    if stripped.startswith("/ps "):
        return [ToolCallRecord(tool_name="powershell", arguments={"command": stripped[4:].strip()})]
    if stripped.startswith("/plan "):
        raw_steps = [segment.strip() for segment in stripped[6:].split("|") if segment.strip()]
        return [ToolCallRecord(tool_name="update_plan", arguments={"steps": raw_steps})]
    if stripped.startswith("/mcp "):
        return [ToolCallRecord(tool_name="mcp_read", arguments={"uri": stripped[5:].strip()})]
    return []


def _build_tool_context() -> ToolExecutionContext:
    """
    构建默认工具执行上下文。

    :return: 工具执行上下文对象。
    """

    settings = AppSettings(
        model=ModelSettings(
            provider="deepseek",
            model_name=DEFAULT_CHAT_MODEL,
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            reasoning_effort="medium",
        ),
        runtime=RuntimeSettings(
            workspace_dir=Path.cwd(),
            session_id=None,
            max_turns=32,
            stream=True,
            debug=False,
        ),
        cli=CliSettings(
            command="run",
            prompt=None,
            system_prompt=None,
            graph_name="main",
            output_format="text",
        ),
    )
    permission_context = create_permission_context(settings)
    mcp_registry = McpRegistry()
    readme_path = settings.runtime.workspace_dir / "README.md"

    if readme_path.exists():
        mcp_registry.register(
            McpResource(
                uri="workspace://README.md",
                title="工作区 README",
                path=readme_path,
                description="当前工作区根目录下的 README 文件。",
            )
        )

    return ToolExecutionContext(
        settings=settings,
        permission_context=permission_context,
        mcp_registry=mcp_registry,
    )


@dataclass(slots=True)
class GraphNodeDependencies:
    """
    LangGraph 主图节点依赖封装。

    该对象用于把节点实现解耦为可注入依赖，便于未来扩展测试或替换特定节点逻辑。
    """

    prepare_node: Callable[[GraphState], GraphState]
    plan_node: Callable[[GraphState], GraphState]
    tools_node: Callable[[GraphState], GraphState]
    llm_node: Callable[[GraphState], GraphState]
    finalize_node: Callable[[GraphState], GraphState]


def create_default_dependencies() -> GraphNodeDependencies:
    """
    创建默认节点依赖集合。

    :return: 节点依赖封装对象。
    """

    tool_registry = create_default_tool_registry()
    tool_context = _build_tool_context()

    def prepare_node(state: GraphState | dict[str, Any]) -> GraphState:
        """
        准备本轮图执行的初始消息与临时字段。

        :param state: 当前图状态。
        :return: 更新后的图状态。
        """

        resolved_state = _ensure_graph_state(state)
        user_input = resolved_state.user_input.strip()
        updated_messages = list(resolved_state.messages)
        updated_messages.append(MessageRecord(role="user", content=user_input))
        return resolved_state.model_copy(
            update={
                "messages": updated_messages,
                "tool_results": [],
                "plan_steps": list(tool_context.plan_steps),
                "error_message": None,
                "llm_response": "",
                "final_output": "",
            }
        )

    def plan_node(state: GraphState | dict[str, Any]) -> GraphState:
        """
        解析工具调用计划。

        :param state: 当前图状态。
        :return: 更新后的图状态。
        """

        resolved_state = _ensure_graph_state(state)
        tool_calls = _parse_tool_instruction(resolved_state.user_input)
        if tool_calls:
            plan_steps = [f"执行工具 {item.tool_name}" for item in tool_calls]
        else:
            plan_steps = ["直接调用模型生成回复"]
        return resolved_state.model_copy(
            update={
                "tool_calls": tool_calls,
                "requires_tools": bool(tool_calls),
                "plan_steps": plan_steps,
            }
        )

    def tools_node(state: GraphState | dict[str, Any]) -> GraphState:
        """
        执行本轮计划中的真实工具调用。

        :param state: 当前图状态。
        :return: 更新后的图状态。
        """

        resolved_state = _ensure_graph_state(state)
        results: list[dict[str, Any]] = []
        for tool_call in resolved_state.tool_calls:
            tool_result = tool_registry.execute(
                tool_name=tool_call.tool_name,
                arguments=tool_call.arguments,
                context=tool_context,
            )
            results.append(tool_result.model_dump(mode="python"))

        plan_steps = list(tool_context.plan_steps) if tool_context.plan_steps else list(resolved_state.plan_steps)
        return resolved_state.model_copy(update={"tool_results": results, "plan_steps": plan_steps})

    def llm_node(state: GraphState | dict[str, Any]) -> GraphState:
        """
        调用语言模型生成文本响应。

        :param state: 当前图状态。
        :return: 更新后的图状态。
        """

        resolved_state = _ensure_graph_state(state)
        build_chat_model = optional_import("funcode.llm.factory", "build_chat_model")
        build_messages_for_inference = optional_import(
            "funcode.llm.factory",
            "build_messages_for_inference",
        )
        model = build_chat_model()
        messages = build_messages_for_inference(
            user_input=resolved_state.user_input,
            tool_results=resolved_state.tool_results,
            system_prompt=resolved_state.system_prompt,
            message_history=[message.model_dump(mode="python") for message in resolved_state.messages],
        )
        response = model.invoke(messages)
        return resolved_state.model_copy(update={"llm_response": getattr(response, "content", str(response))})

    def finalize_node(state: GraphState | dict[str, Any]) -> GraphState:
        """
        汇总工具输出与模型输出，生成最终答复并补全助手消息。

        :param state: 当前图状态。
        :return: 更新后的图状态。
        """

        resolved_state = _ensure_graph_state(state)
        if resolved_state.tool_results:
            tool_summary = "\n\n".join(
                f"[{result['tool_name']}]\n{result['content']}" for result in resolved_state.tool_results
            )
        else:
            tool_summary = ""

        llm_response = resolved_state.llm_response
        if tool_summary and llm_response:
            final_output = f"{tool_summary}\n\n{llm_response}".strip()
        else:
            final_output = tool_summary or llm_response

        updated_messages = list(resolved_state.messages)
        updated_messages.append(MessageRecord(role="assistant", content=final_output))
        return resolved_state.model_copy(update={"final_output": final_output, "messages": updated_messages})

    return GraphNodeDependencies(
        prepare_node=prepare_node,
        plan_node=plan_node,
        tools_node=tools_node,
        llm_node=llm_node,
        finalize_node=finalize_node,
    )
