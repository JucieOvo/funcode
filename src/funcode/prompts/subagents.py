"""
模块名称：prompts.subagents
功能描述：
    构造子代理调度提示词模板，用于指导主代理分发任务与汇总结果。
主要组件：
    - build_subagents_prompt: 构造子代理提示词
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化子代理提示词模板。
"""

from __future__ import annotations


def build_subagents_prompt(*, user_input: str) -> str:
    """
    构造子代理提示词模板。

    :param user_input: 用户输入
    :return: 子代理提示词文本
    """

    return (
        "如果当前任务涉及多个独立子问题，请拆分为可并行的小任务并委派给子代理。"
        f"本轮任务主题为：{user_input.strip()}。"
        "对子代理的要求是返回真实执行结果、关键路径与必要说明，禁止返回假数据。"
        "主代理在汇总时应合并所有真实结果，并清晰标记来源。"
    )
