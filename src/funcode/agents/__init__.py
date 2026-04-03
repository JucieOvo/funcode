"""
模块名称：agents.__init__
功能描述：
    暴露 Python 版 Funcode 的代理层公共接口，包括代理定义、
    注册表、执行器与管理器。

主要组件：
    - AgentExecutionResult: 代理执行结果对象
    - AgentManager: 代理管理器
    - AgentRegistry: 代理注册表

依赖说明：
    - funcode.agents.manager: 代理管理器实现
    - funcode.agents.models: 代理数据模型
    - funcode.agents.registry: 代理注册表实现

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 agents 包导出
"""

from funcode.agents.manager import AgentManager
from funcode.agents.lifecycle import AgentLifecycleService
from funcode.agents.models import (
    AgentDefinition,
    AgentExecutionContext,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentRunMessage,
    AgentRunRecord,
    AgentRunStatus,
    AgentRuntimeState,
    AgentSource,
    AgentStatus,
    AgentTaskSpec,
)
from funcode.agents.registry import AgentRegistry

__all__ = [
    "AgentDefinition",
    "AgentExecutionContext",
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentLifecycleService",
    "AgentManager",
    "AgentRunMessage",
    "AgentRunRecord",
    "AgentRunStatus",
    "AgentRuntimeState",
    "AgentRegistry",
    "AgentSource",
    "AgentStatus",
    "AgentTaskSpec",
]
