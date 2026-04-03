"""
模块名称：output
功能描述：
    统一管理运行结果输出格式，并对外导出文本、JSON 与自动分发渲染函数。
主要组件：
    - render_execution_result: 根据结果格式渲染输出文本。
    - render_execution_result_as_text: 渲染文本输出。
    - render_execution_result_as_json: 渲染 JSON 输出。
依赖说明：
    - funcode.output.renderers: 统一输出调度实现。
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 切换为统一输出调度器导出。
"""

from funcode.output.renderers import (
    render_execution_result,
    render_execution_result_as_json,
    render_execution_result_as_text,
)

__all__ = [
    "render_execution_result",
    "render_execution_result_as_json",
    "render_execution_result_as_text",
]
