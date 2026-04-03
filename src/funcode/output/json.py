"""
模块名称：json
功能描述：
    负责将结构化执行结果稳定序列化为 JSON 文本，供外部程序、脚本或后续自动化流程消费。

主要组件：
    - render_execution_result_as_json: JSON 输出渲染函数。

依赖说明：
    - funcode.schemas.execution: 执行结果模型。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 JSON 输出渲染逻辑。
"""

from __future__ import annotations

from funcode.schemas.core import ExecutionResult


def render_execution_result_as_json(result: ExecutionResult) -> str:
    """
    将执行结果渲染为 JSON 文本。

    :param result: 执行结果对象。
    :return: JSON 字符串。
    """

    return result.model_dump_json(indent=2)
