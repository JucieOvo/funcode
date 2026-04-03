"""
模块名称：application
功能描述：
    作为运行时应用层编排入口，统一协调 execution request、session manager、graph 构建与 output 渲染。
    该模块对上承接 cli/commands，对下调用 session、graph、output，不直接耦合底层持久化细节与输出拼接细节。

主要组件：
    - FuncodeApplication: 运行时应用编排器。
    - build_execution_request: 从 AppSettings 构造运行请求。
    - run_once: 单次执行入口。
    - run_interactive: 交互式执行入口。

依赖说明：
    - funcode.config.settings: 应用配置模型。
    - funcode.graph: 主图构建入口。
    - funcode.output: 输出渲染入口。
    - funcode.schemas: 统一请求结果与状态模型。
    - funcode.session: 会话管理子系统。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化运行时编排逻辑与执行入口。
"""

from __future__ import annotations

from dataclasses import dataclass

from funcode.config.settings import AppSettings
from funcode.graph.state import GraphState as RuntimeGraphState
from funcode.output import render_execution_result
from funcode.schemas import ExecutionRequest, ExecutionResult, GraphState
from funcode.permissions.context import create_permission_context
from funcode.runtime.swarm_lifecycle import SwarmLifecycleService
from funcode.session.manager import SessionManager
from funcode.session.repository import SessionRepository


# 交互模式退出命令集合 (set[str])
INTERACTIVE_EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit"}

'''
用途：定义交互式运行中用于主动结束会话的命令集合，避免退出判断逻辑分散在循环体中。
依赖关系：
    主：被 run_interactive 直接用于用户输入退出判定。
    从：交互式运行行为依赖该集合确定何时结束。
影响：修改该集合会直接改变交互模式允许的退出命令。
其他：该集合仅用于本地 CLI 交互判断，不参与图执行逻辑。
'''


@dataclass(slots=True)
class FuncodeApplication:
    """
    运行时应用编排器。

    职责：
        1. 接收 ExecutionRequest。
        2. 协调 SessionManager 读取或创建会话。
        3. 构造 GraphState 并调用主图执行。
        4. 将 GraphState 转换为 ExecutionResult。
        5. 将结果回写并持久化到会话仓储。

    属性：
        session_manager (SessionManager): 会话管理器。
    """

    session_manager: SessionManager

    @classmethod
    def from_request(cls, request: ExecutionRequest) -> "FuncodeApplication":
        """
        根据执行请求创建运行时应用实例。

        :param request: 运行时执行请求。
        :return: 应用编排器实例。
        """

        repository = SessionRepository(request.workspace_dir)
        manager = SessionManager(repository)
        return cls(session_manager=manager)

    def _compile_graph(self, graph_name: str):
        """
        根据图名称构建主图。

        :param graph_name: 目标图名称。
        :return: 已编译的图对象。
        :raises ValueError: 当图名称不受支持时触发。
        """

        if graph_name != "main":
            raise ValueError(f"当前仅支持 main 图，收到：{graph_name}")
        from funcode.graph import build_main_graph

        return build_main_graph()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """
        执行一次完整应用流程。

        :param request: 运行时执行请求。
        :return: 结构化执行结果。
        """

        session_state = self.session_manager.load_or_create(request)
        graph_state = self.session_manager.build_graph_state(session_state, request)
        graph_input = RuntimeGraphState.model_validate({
            "session_id": graph_state.session_id,
            "graph_name": graph_state.graph_name,
            "output_format": graph_state.output_format,
            "user_input": graph_state.user_input,
            "system_prompt": graph_state.system_prompt,
            "llm_response": graph_state.llm_response,
            "final_output": graph_state.final_output,
            "requires_tools": graph_state.requires_tools,
            "tool_calls": [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in graph_state.tool_calls
            ],
            "tool_results": [
                item if isinstance(item, dict) else dict(item)
                for item in graph_state.tool_results
            ],
            "messages": [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in graph_state.messages
            ],
            "plan_steps": list(graph_state.plan_steps),
            "error_message": graph_state.error_message,
        })
        compiled_graph = self._compile_graph(request.graph_name)
        raw_result_state = compiled_graph.invoke(graph_input)
        if isinstance(raw_result_state, GraphState):
            resolved_graph_state = raw_result_state
        elif isinstance(raw_result_state, RuntimeGraphState):
            resolved_graph_state = GraphState.model_validate(raw_result_state.model_dump())
        elif hasattr(raw_result_state, "model_dump"):
            resolved_graph_state = GraphState.model_validate(raw_result_state.model_dump())
        else:
            resolved_graph_state = GraphState.model_validate(raw_result_state)
        execution_result = ExecutionResult.from_graph_state(resolved_graph_state)
        updated_session_state = self.session_manager.apply_result(session_state, execution_result)
        self.session_manager.save(updated_session_state)
        return execution_result


def build_execution_request(
    settings: AppSettings,
    user_input: str | None = None,
    session_id: str | None = None,
) -> ExecutionRequest:
    """
    从应用配置构造运行时执行请求。

    :param settings: 应用配置对象。
    :param user_input: 可选用户输入；为空时回退到 CLI prompt。
    :param session_id: 可选会话标识覆盖值。
    :return: 运行时执行请求。
    :raises ValueError: 当缺少必要用户输入时触发。
    """

    resolved_user_input = user_input if user_input is not None else settings.cli.prompt
    if resolved_user_input is None or not resolved_user_input.strip():
        raise ValueError("运行请求缺少用户输入内容")

    permission_context = create_permission_context(settings)
    lifecycle_service = SwarmLifecycleService(settings.runtime.workspace_dir)
    swarm_snapshot = lifecycle_service.snapshot()

    return ExecutionRequest(
        workspace_dir=settings.runtime.workspace_dir,
        user_input=resolved_user_input.strip(),
        session_id=session_id if session_id is not None else settings.runtime.session_id,
        system_prompt=settings.cli.system_prompt,
        graph_name=settings.cli.graph_name,
        output_format=settings.cli.output_format,
        max_turns=settings.runtime.max_turns,
        stream=settings.runtime.stream,
        debug=settings.runtime.debug,
        permission_snapshot=permission_context.model_dump(mode="json"),
        agent_snapshots=list(swarm_snapshot["agent_snapshots"]),
        team_snapshots=list(swarm_snapshot["team_snapshots"]),
        mailbox_snapshot=dict(swarm_snapshot["mailbox_snapshot"]),
    )


def run_once(settings: AppSettings) -> int:
    """
    执行单次运行模式。

    :param settings: 应用配置对象。
    :return: 进程退出码。
    """

    request = build_execution_request(settings)
    application = FuncodeApplication.from_request(request)
    result = application.execute(request)
    print(render_execution_result(result))
    return 0 if result.success else 1


def run_interactive(settings: AppSettings) -> int:
    """
    执行交互式运行模式。

    :param settings: 应用配置对象。
    :return: 进程退出码。
    """

    active_session_id = settings.runtime.session_id
    turn_index = 0
    had_failure = False

    print("已进入交互模式，输入 exit 或 quit 结束。")
    while turn_index < settings.runtime.max_turns:
        user_input = input(">>> ").strip()
        if not user_input:
            continue
        if user_input in INTERACTIVE_EXIT_COMMANDS:
            break

        request = build_execution_request(
            settings=settings,
            user_input=user_input,
            session_id=active_session_id,
        )
        application = FuncodeApplication.from_request(request)
        result = application.execute(request)
        active_session_id = result.session_id
        print(render_execution_result(result))
        had_failure = had_failure or not result.success
        turn_index += 1

    return 1 if had_failure else 0
