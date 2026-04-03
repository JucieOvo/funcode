"""
模块名称：prompts.tools
功能描述：
    构造工具使用提示词模板，帮助模型理解当前可用工具与结果约束。
主要组件：
    - build_tools_prompt: 构造工具提示词
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化工具提示词模板。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_tools_prompt(
    *,
    tool_results: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """
    构造工具提示词模板。

    :param tool_results: 已有工具结果
    :return: 工具提示词文本
    """

    resolved_tool_results = list(tool_results or [])
    if not resolved_tool_results:
        return "当前尚未执行工具。若任务需要文件、目录或命令信息，请优先使用真实工具。"

    tool_names = ", ".join(str(item.get("tool_name", "unknown")) for item in resolved_tool_results)
    return (
        "当前已经执行过以下工具："
        f"{tool_names}。"
        "在继续推理时，请优先复用已获得的真实结果，不要重复执行同一工具，除非有新的输入条件。"
    )
