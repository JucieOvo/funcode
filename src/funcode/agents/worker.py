"""
模块名称：agents.worker
功能描述：
    提供 agent run 后台执行入口，负责在独立进程中调用 AgentLifecycleService.wait，
    并把执行结果真实写回 run/session/swarm 持久化文件。
主要组件：
    - run_worker: 执行单个 run 的后台处理。
    - main: 命令行入口。
依赖说明：
    - argparse: 参数解析。
    - pathlib: 工作区路径解析。
    - funcode.agents.lifecycle: 生命周期服务。
作者：JucieOvo
创建日期：2026-04-02
修改记录：
    - 2026-04-02 JucieOvo: 新增后台执行 worker 入口。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from funcode.agents.lifecycle import AgentLifecycleService


def _resolve_worker_execution_cwd(*, service: AgentLifecycleService, run_id: str, workspace_dir: Path) -> Path:
    """
    从 run metadata 中恢复 worker 需要切换到的执行目录。
    :param service: 生命周期服务。
    :param run_id: run 标识。
    :param workspace_dir: 默认工作区目录。
    :return: 解析后的执行目录。
    :raises FileNotFoundError: 当声明的 worktree_path 不存在时触发。
    """

    record = service.get_run(run_id=run_id)
    run_context = record.metadata.get("run_context")
    if not isinstance(run_context, dict):
        return workspace_dir.resolve()
    raw_worktree_path = run_context.get("worktree_path", run_context.get("worktreePath"))
    if raw_worktree_path is None:
        return workspace_dir.resolve()
    candidate = Path(str(raw_worktree_path)).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise FileNotFoundError(f"worktree_path 不存在或不可访问：{candidate}")
    return candidate


def run_worker(
    *,
    workspace_dir: Path,
    run_id: str,
    max_turns: int,
    system_prompt: str | None,
    graph_name: str,
    output_format: str,
) -> None:
    """
    在独立进程内执行单个 run 的 wait 流程。

    :param workspace_dir: 工作区目录。
    :param run_id: run 标识。
    :param max_turns: 最大轮数。
    :param system_prompt: 系统提示词。
    :param graph_name: 图名称。
    :param output_format: 输出格式。
    """

    service = AgentLifecycleService(workspace_dir.resolve())
    execution_cwd = _resolve_worker_execution_cwd(service=service, run_id=run_id, workspace_dir=workspace_dir)
    original_cwd = Path.cwd()
    try:
        if execution_cwd != original_cwd:
            os.chdir(execution_cwd)
        service.wait(
            run_id=run_id,
            max_turns=max_turns,
            system_prompt=system_prompt,
            graph_name=graph_name,
            output_format=output_format,
        )
    finally:
        if Path.cwd() != original_cwd:
            os.chdir(original_cwd)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="funcode.agents.worker", description="Agent 后台执行 worker")
    parser.add_argument("--workspace-dir", required=True, dest="workspace_dir", help="工作区目录")
    parser.add_argument("--run-id", required=True, dest="run_id", help="run 标识")
    parser.add_argument("--max-turns", required=False, dest="max_turns", type=int, default=32, help="最大轮数")
    parser.add_argument("--system-prompt", required=False, dest="system_prompt", default=None, help="系统提示词")
    parser.add_argument("--graph-name", required=False, dest="graph_name", default="main", help="图名称")
    parser.add_argument("--output-format", required=False, dest="output_format", default="text", choices=("text", "json"), help="输出格式")
    return parser


def main() -> int:
    parser = _build_parser()
    namespace = parser.parse_args()
    run_worker(
        workspace_dir=Path(str(namespace.workspace_dir)),
        run_id=str(namespace.run_id),
        max_turns=max(1, int(namespace.max_turns)),
        system_prompt=str(namespace.system_prompt) if namespace.system_prompt is not None else None,
        graph_name=str(namespace.graph_name),
        output_format=str(namespace.output_format),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
