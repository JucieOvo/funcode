"""
模块名称：prompts.planning
功能描述：
    构造任务规划提示词模板，用于引导模型先分析再执行。
主要组件：
    - build_planning_prompt: 构造规划提示词
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化规划提示词模板。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_planning_prompt(
    *,
    user_input: str,
    tool_results: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """
    构造规划提示词模板。

    :param user_input: 用户输入
    :param tool_results: 已有工具结果
    :return: 规划提示词文本
    """

    resolved_tool_results = list(tool_results or [])
    tool_count = len(resolved_tool_results)
    return (
        "请先进行任务规划，再决定是否调用工具或子代理。"
        f"当前用户输入为：{user_input.strip()}。"
        f"当前已有工具结果数量为：{tool_count}。"
        "如果需要继续执行，请明确列出下一步动作、依赖关系和预期输出。"
        "如果任务已经完成，请直接给出最终答案并说明依据。"
    )
