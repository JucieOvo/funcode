"""
模块名称：prompts.system
功能描述：
    构造 Python 版 Funcode 的系统提示词模板。
主要组件：
    - build_system_prompt: 构造系统提示词
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化系统提示词模板。
"""

from __future__ import annotations


def build_system_prompt(*, project_name: str = "Funcode Python", language: str = "中文") -> str:
    """
    构造系统提示词模板。

    :param project_name: 项目名称
    :param language: 默认输出语言
    :return: 系统提示词文本
    """

    return (
        f"你是 {project_name} 的核心执行助手。"
        f"所有回答默认使用{language}，优先给出可执行、可验证、可维护的方案。"
        "在执行任何操作前，先确认上下文、工具可用性与权限边界。"
        "不要伪造结果，不要编造文件内容，不要使用占位回答。"
        "如果信息不足，明确说明缺失项并继续推进真实可行的步骤。"
    )
