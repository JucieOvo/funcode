"""
模块名称：agents.executor
功能描述：
    提供真实的代理执行器，负责把代理任务提交到线程池，
    并将执行结果统一封装为结构化对象。

主要组件：
    - AgentExecutor: 代理执行器

依赖说明：
    - concurrent.futures: 线程池执行
    - funcode.agents.models: 代理执行模型

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化线程池代理执行器
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from funcode.agents.models import AgentExecutionRequest, AgentExecutionResult


AgentCallable = Callable[[AgentExecutionRequest], str]


class AgentExecutor:
    """
    线程池代理执行器。
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="funcode-agent")

    def submit(self, request: AgentExecutionRequest, handler: AgentCallable) -> Future[AgentExecutionResult]:
        """
        提交代理执行任务。
        """

        return self._pool.submit(self._run, request, handler)

    @staticmethod
    def _run(request: AgentExecutionRequest, handler: AgentCallable) -> AgentExecutionResult:
        """
        在线程池中执行代理任务。
        """

        started_at = datetime.now(timezone.utc)
        try:
            output = handler(request)
            if not output.strip():
                raise ValueError("代理执行结果为空，视为执行失败")
            return AgentExecutionResult.success(
                agent_name=request.definition.agent_name,
                task_id=request.task.task_id,
                output=output,
                metadata={
                    "role": request.definition.role,
                    "team_name": request.context.team_name,
                },
                started_at=started_at,
            )
        except Exception as exc:
            return AgentExecutionResult.failure(
                agent_name=request.definition.agent_name,
                task_id=request.task.task_id,
                error_message=str(exc),
                metadata={
                    "role": request.definition.role,
                    "team_name": request.context.team_name,
                },
                started_at=started_at,
            )

    def shutdown(self) -> None:
        """
        关闭执行器。
        """

        self._pool.shutdown(wait=True, cancel_futures=False)
