"""
模块名称：output.renderers
功能描述：
    统一调度运行结果的文本与 JSON 渲染逻辑，避免 runtime 层直接依赖具体输出格式实现。
主要组件：
    - render_execution_result: 根据输出格式渲染结果。
    - render_execution_result_as_text: 文本输出渲染。
    - render_execution_result_as_json: JSON 输出渲染。
依赖说明：
    - funcode.output.text: 文本渲染实现。
    - funcode.output.json: JSON 渲染实现。
    - funcode.schemas.core: 统一运行结果模型。
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 新增统一输出调度器。
"""

from __future__ import annotations

from funcode.output.json import render_execution_result_as_json as _render_json
from funcode.output.text import render_execution_result_as_text as _render_text
from funcode.schemas.core import ExecutionResult


def render_execution_result_as_text(result: ExecutionResult) -> str:
    """
    将运行结果渲染为文本。
    """

    return _render_text(result)


def render_execution_result_as_json(result: ExecutionResult) -> str:
    """
    将运行结果渲染为 JSON。
    """

    return _render_json(result)


def render_execution_result(result: ExecutionResult) -> str:
    """
    根据结果中的输出格式进行分发渲染。
    """

    if result.output_format == "text":
        return render_execution_result_as_text(result)
    if result.output_format == "json":
        return render_execution_result_as_json(result)
    raise ValueError(f"不支持的输出格式：{result.output_format}")


__all__ = [
    "render_execution_result",
    "render_execution_result_as_json",
    "render_execution_result_as_text",
]
