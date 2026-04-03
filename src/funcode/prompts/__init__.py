"""
模块名称：prompts
功能描述：
    汇总 Python 版 Funcode 的提示词构造函数。
主要组件：
    - build_system_prompt
    - build_planning_prompt
    - build_tools_prompt
    - build_subagents_prompt
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化提示词包导出。
"""

from .planning import build_planning_prompt
from .subagents import build_subagents_prompt
from .system import build_system_prompt
from .tools import build_tools_prompt

__all__ = [
    "build_planning_prompt",
    "build_subagents_prompt",
    "build_system_prompt",
    "build_tools_prompt",
]
