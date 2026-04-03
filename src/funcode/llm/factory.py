"""
模块名称：llm.factory
功能描述：
    负责构建 DeepSeek OpenAI 兼容聊天模型客户端，并将当前用户输入、历史消息、工具结果与
    系统提示词组装为 LangChain 可直接消费的消息序列。

主要组件：
    - build_chat_model: 构建 ChatOpenAI 实例。
    - build_messages_for_inference: 构建推理消息序列。

依赖说明：
    - langchain_openai: OpenAI 兼容聊天模型实现。
    - langchain_core.messages: 消息对象。
    - funcode.llm.models: 模型配置与工具结果格式化。
    - funcode.prompts: 系统、规划、工具与子代理提示词。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 重写模型工厂并补充历史消息支持。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from funcode.llm.models import DeepSeekModelConfig, format_tool_results
from funcode.prompts import (
    build_planning_prompt,
    build_subagents_prompt,
    build_system_prompt,
    build_tools_prompt,
)


def build_chat_model(
    *,
    model_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    reasoning_effort: str | None = None,
) -> ChatOpenAI:
    """
    构建 DeepSeek OpenAI 兼容聊天模型实例。

    :param model_name: 可选模型名称覆盖值。
    :param api_key: 可选 API Key 覆盖值。
    :param base_url: 可选服务地址覆盖值。
    :param reasoning_effort: 可选推理强度覆盖值。
    :return: ChatOpenAI 实例。
    :raises ValueError: 当模型配置缺失或非法时触发。
    """

    model_config = DeepSeekModelConfig.from_env(
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        reasoning_effort=reasoning_effort,
    )
    return ChatOpenAI(
        model=model_config.model_name,
        api_key=model_config.api_key,
        base_url=model_config.base_url,
        temperature=0,
        reasoning_effort=model_config.reasoning_effort,
    )


def build_messages_for_inference(
    *,
    user_input: str,
    tool_results: Sequence[Mapping[str, Any]] | None = None,
    system_prompt: str | None = None,
    message_history: Sequence[Mapping[str, Any]] | None = None,
) -> list[SystemMessage | HumanMessage]:
    """
    将当前轮输入转换为模型消息序列。

    该函数会组合系统提示词、历史消息摘要、规划提示词、工具提示词、子代理提示词与当前输入，
    形成可直接送入模型的消息列表。

    :param user_input: 用户输入。
    :param tool_results: 工具结果列表。
    :param system_prompt: 可选系统提示词。
    :param message_history: 可选历史消息列表。
    :return: LangChain 消息列表。
    """

    resolved_tool_results = list(tool_results or [])
    resolved_message_history = list(message_history or [])
    resolved_system_prompt = system_prompt or build_system_prompt()
    planning_prompt = build_planning_prompt(user_input=user_input, tool_results=resolved_tool_results)
    tools_prompt = build_tools_prompt(tool_results=resolved_tool_results)
    subagents_prompt = build_subagents_prompt(user_input=user_input)
    tool_results_text = format_tool_results(resolved_tool_results)
    history_text = "\n".join(
        f"{str(message.get('role', 'unknown'))}: {str(message.get('content', ''))}"
        for message in resolved_message_history
        if str(message.get("content", "")).strip()
    )

    combined_user_text = "\n\n".join(
        block
        for block in (
            f"历史消息:\n{history_text}" if history_text else "",
            f"用户输入:\n{user_input.strip()}",
            planning_prompt,
            tools_prompt,
            subagents_prompt,
            f"已执行工具结果:\n{tool_results_text}" if tool_results_text else "",
        )
        if block
    )

    return [
        SystemMessage(content=resolved_system_prompt),
        HumanMessage(content=combined_user_text),
    ]
