"""
模块名称：agents.manager
功能描述：
    基于注册表与执行器实现代理调度管理，负责代理定义校验、任务派发、
    执行结果汇总以及最近状态快照保存。

主要组件：
    - AgentManager: 代理管理器

依赖说明：
    - funcode.agents.executor: 代理执行器
    - funcode.agents.registry: 代理注册表

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现代理管理器
    - 2026-04-01 JucieOvo: 增加状态快照与定义一致性校验
"""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any, Callable

from funcode.agents.executor import AgentCallable, AgentExecutor
from funcode.agents.models import AgentExecutionRequest, AgentExecutionResult
from funcode.agents.registry import AgentRegistry


class AgentManager:
    """
    代理管理器。

    该对象负责把代理定义、任务与执行器连接起来，并记录真实执行历史。
    """

    def __init__(self, registry: AgentRegistry, executor: AgentExecutor | None = None) -> None:
        self._registry = registry
        self._executor = executor or AgentExecutor()
        self._lock = Lock()
        self._recent_results: deque[AgentExecutionResult] = deque(maxlen=50)
        self._last_result_by_agent: dict[str, AgentExecutionResult] = {}

    @staticmethod
    def _canonical_definition_view(request_definition: Any) -> dict[str, Any]:
        """
        提取用于一致性校验的代理定义关键字段。

        :param request_definition: 代理定义对象。
        :return: 规范化字段视图。
        """

        if hasattr(request_definition, "model_dump"):
            payload = request_definition.model_dump(mode="python")
        else:
            payload = dict(request_definition)
        return {
            "agent_name": payload.get("agent_name"),
            "role": payload.get("role"),
            "description": payload.get("description"),
            "max_concurrency": payload.get("max_concurrency"),
        }

    def execute(self, request: AgentExecutionRequest, handler: AgentCallable) -> AgentExecutionResult:
        """
        同步执行单个代理任务。

        :param request: 代理执行请求。
        :param handler: 真实执行处理函数。
        :return: 执行结果。
        """

        definition = self._registry.get(request.definition.agent_name)
        if self._canonical_definition_view(definition) != self._canonical_definition_view(request.definition):
            raise ValueError("请求中的代理定义与注册表定义不一致，拒绝执行")

        result = self._executor.submit(request, handler).result()
        self._record_result(result)
        return result

    def map(
        self,
        requests: list[AgentExecutionRequest],
        handler_factory: Callable[[AgentExecutionRequest], AgentCallable],
    ) -> list[AgentExecutionResult]:
        """
        并发执行一组代理任务。

        :param requests: 代理请求列表。
        :param handler_factory: 为每个请求生成执行函数的工厂。
        :return: 执行结果列表。
        """

        futures = [self._executor.submit(request, handler_factory(request)) for request in requests]
        results = [future.result() for future in futures]
        for result in results:
            self._record_result(result)
        return results

    def _record_result(self, result: AgentExecutionResult) -> None:
        """
        记录最近一次代理执行结果。

        :param result: 代理执行结果。
        """

        with self._lock:
            self._recent_results.append(result)
            self._last_result_by_agent[result.agent_name] = result

    def snapshot(self) -> dict[str, Any]:
        """
        返回代理管理器的真实状态快照。

        :return: 状态快照。
        """

        with self._lock:
            recent_results = list(self._recent_results)
            last_result_by_agent = {
                agent_name: result.model_dump(mode="json")
                for agent_name, result in self._last_result_by_agent.items()
            }

        return {
            "agent_count": len(self._registry.list()),
            "recent_result_count": len(recent_results),
            "recent_results": [result.model_dump(mode="json") for result in recent_results],
            "last_result_by_agent": last_result_by_agent,
            "registry": self._registry.snapshot(),
        }

    def shutdown(self) -> None:
        """
        关闭执行器。
        """

        self._executor.shutdown()
