"""
模块名称：text
功能描述：
    负责将结构化执行结果渲染为命令行友好的纯文本输出，突出会话标识、计划步骤、工具结果与最终答复。

主要组件：
    - render_execution_result_as_text: 文本输出渲染函数。

依赖说明：
    - funcode.schemas.execution: 执行结果模型。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化文本输出渲染逻辑。
"""

from __future__ import annotations

from funcode.schemas.core import ExecutionResult


def render_execution_result_as_text(result: ExecutionResult) -> str:
    """
    将执行结果渲染为 CLI 友好的文本格式。

    :param result: 执行结果对象。
    :return: 渲染后的文本。
    """

    lines: list[str] = [
        f"session_id: {result.session_id}",
        f"graph_name: {result.graph_name}",
        f"output_format: {result.output_format}",
        f"success: {result.success}",
        f"message_count: {len(result.messages)}",
        f"tool_call_count: {len(result.tool_calls)}",
        f"tool_result_count: {len(result.tool_results)}",
        f"plan_step_count: {len(result.plan_steps)}",
    ]

    if result.error_message:
        lines.append("error_message:")
        lines.append(result.error_message)

    if result.plan_steps:
        lines.append("plan_steps:")
        lines.extend(f"- {step}" for step in result.plan_steps)

    if result.tool_results:
        lines.append("tool_results:")
        for tool_result in result.tool_results:
            tool_name = str(tool_result.get("tool_name", ""))
            content = str(tool_result.get("content", ""))
            lines.append(f"[{tool_name}]")
            lines.append(content)

    lines.append("final_output:")
    lines.append(result.final_output)
    return "\n".join(lines).strip()
