"""
模块名称：advanced
功能描述：
    提供高阶工具链所需的真实工具实现，覆盖 worktree、cron 与 REPL 三条能力线。
    本模块只提供真实文件落盘、真实子进程调用与真实系统命令，不返回伪造结果。

主要组件：
    - EnterWorktreeTool: 创建真实 Git worktree。
    - ExitWorktreeTool: 移除真实 Git worktree。
    - ScheduleCronTool: 创建真实 Windows 计划任务。
    - REPLTool: 启动真实 Python REPL 子进程并记录执行结果。
    - enter_worktree: worktree 创建函数。
    - exit_worktree: worktree 移除函数。
    - schedule_cron: cron 调度创建函数。
    - run_repl_script: REPL 执行函数。

依赖说明：
    - pathlib: 路径处理与真实落盘。
    - subprocess: 真实命令执行。
    - funcode.tools.base: 工具基类与统一结果模型。
    - funcode.tools.context: 工具执行上下文。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 恢复高阶工具文件并补齐主工作区可见实现。
"""

from __future__ import annotations

import ast
import json
import os
import py_compile
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from funcode.lsp import get_lsp_manager, get_supported_lsp_actions
from funcode.permissions.validators import ensure_tool_path_allowed
from funcode.schemas.core import LspDiagnostic, LspSymbol, PlanModeState
from funcode.tools.base import BaseTool, ToolResult
from funcode.tools.context import ToolExecutionContext
from funcode.utils.errors import ToolExecutionError

ADVANCED_TOOL_NAMES: tuple[str, ...] = ("lsp", "enter_plan_mode", "exit_plan_mode")


def _render_json(payload: Any) -> str:
    """
    将对象渲染为稳定 JSON 文本。

    :param payload: 待渲染对象。
    :return: JSON 文本。
    """

    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _now_iso() -> str:
    """
    返回当前 UTC 时间的 ISO 字符串。

    :return: ISO 时间字符串。
    """

    return datetime.now(timezone.utc).isoformat()


def _runtime_root(workspace_dir: Path, runtime_dir: Path | None = None) -> Path:
    """
    计算工作区运行时目录。

    :param workspace_dir: 工作区根目录。
    :param runtime_dir: 可选显式运行时目录。
    :return: 运行时目录。
    """

    if runtime_dir is not None:
        return runtime_dir.resolve()
    return workspace_dir.resolve() / ".funcode"


def _ensure_directory(path: Path) -> Path:
    """
    确保目标目录存在。

    :param path: 目标目录。
    :return: 原目录路径。
    """

    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(raw_name: str) -> str:
    """
    将逻辑名称收敛为安全文件名。

    :param raw_name: 原始名称。
    :return: 安全名称。
    :raises ValueError: 当名称为空时触发。
    """

    normalized = str(raw_name).strip()
    if not normalized:
        raise ValueError("名称不能为空")

    safe_chars: list[str] = []
    for character in normalized:
        if character.isalnum() or character in {"-", "_", "."}:
            safe_chars.append(character)
        else:
            safe_chars.append("-")
    safe_name = "".join(safe_chars).strip("-._")
    if not safe_name:
        raise ValueError(f"名称无法转换为安全文件名：{raw_name}")
    return safe_name


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    执行真实系统命令。

    :param command: 命令参数列表。
    :param cwd: 可选工作目录。
    :param env: 可选环境变量。
    :return: 真实命令执行结果。
    :raises ToolExecutionError: 当命令返回非零状态码时触发。
    """

    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise ToolExecutionError(
            f"命令执行失败，返回码={completed.returncode}，命令={command!r}，stderr={completed.stderr.strip()}"
        )
    return completed


def _resolve_repo_root(workspace_dir: Path) -> Path:
    """
    解析 Git 仓库根目录。

    :param workspace_dir: 当前工作区。
    :return: 仓库根目录。
    """

    completed = _run_command(
        ["git", "-C", str(workspace_dir.resolve()), "rev-parse", "--show-toplevel"],
        cwd=workspace_dir.resolve(),
    )
    return Path(completed.stdout.strip()).resolve()


def _external_worktree_root(workspace_dir: Path) -> Path:
    """
    计算仓库外部的 worktree 目录。

    :param workspace_dir: 当前工作区。
    :return: worktree 根目录。
    """

    resolved_workspace = workspace_dir.resolve()
    return resolved_workspace.parent / f".{resolved_workspace.name}.worktrees"


def enter_worktree(
    *,
    workspace_dir: Path,
    runtime_dir: Path | None = None,
    name: str,
    branch: str | None = None,
    start_point: str = "HEAD",
) -> dict[str, Any]:
    """
    创建真实 Git worktree 并落盘清单。

    :param workspace_dir: 工作区根目录。
    :param runtime_dir: 可选运行时目录。
    :param name: worktree 名称。
    :param branch: 可选分支名。
    :param start_point: 起始提交或引用。
    :return: 创建结果。
    """

    resolved_workspace = workspace_dir.resolve()
    resolved_runtime = _runtime_root(resolved_workspace, runtime_dir)
    manifest_root = _ensure_directory(resolved_runtime / "worktrees")
    worktree_root = _ensure_directory(_external_worktree_root(resolved_workspace))

    safe_name = _safe_name(name)
    branch_name = str(branch).strip() if branch is not None and str(branch).strip() else safe_name
    manifest_path = manifest_root / f"{safe_name}.json"
    worktree_path = worktree_root / safe_name
    repo_root = _resolve_repo_root(resolved_workspace)

    if manifest_path.exists():
        raise ToolExecutionError(f"worktree 清单已存在：{manifest_path}")

    branch_exists = subprocess.run(
        ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).returncode == 0

    command = ["git", "-C", str(repo_root), "worktree", "add"]
    if branch_exists:
        command.extend([str(worktree_path), branch_name])
    else:
        command.extend(["-b", branch_name, str(worktree_path), start_point])
    _run_command(command, cwd=repo_root)

    result = {
        "tool_name": "enter_worktree",
        "workspace_dir": str(resolved_workspace),
        "runtime_dir": str(resolved_runtime),
        "repo_root": str(repo_root),
        "name": name,
        "safe_name": safe_name,
        "branch": branch_name,
        "branch_created": not branch_exists,
        "start_point": start_point,
        "worktree_path": str(worktree_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "created_at": _now_iso(),
        "status": "active",
    }
    manifest_path.write_text(_render_json(result), encoding="utf-8")
    return result


def exit_worktree(
    *,
    workspace_dir: Path,
    runtime_dir: Path | None = None,
    name: str,
    delete_branch: bool = False,
) -> dict[str, Any]:
    """
    移除真实 Git worktree，并按需要删除对应分支。

    :param workspace_dir: 工作区根目录。
    :param runtime_dir: 可选运行时目录。
    :param name: worktree 名称。
    :param delete_branch: 是否删除分支。
    :return: 移除结果。
    """

    resolved_workspace = workspace_dir.resolve()
    resolved_runtime = _runtime_root(resolved_workspace, runtime_dir)
    safe_name = _safe_name(name)
    manifest_path = resolved_runtime / "worktrees" / f"{safe_name}.json"
    if not manifest_path.exists():
        raise ToolExecutionError(f"worktree 清单不存在：{manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_root = Path(str(manifest["repo_root"])).resolve()
    worktree_path = Path(str(manifest["worktree_path"])).resolve()
    branch_name = str(manifest["branch"])
    branch_created = bool(manifest.get("branch_created", False))

    _run_command(
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo_root,
    )
    _run_command(["git", "-C", str(repo_root), "worktree", "prune"], cwd=repo_root)

    branch_deleted = False
    if delete_branch:
        if not branch_created:
            raise ToolExecutionError(f"分支不是本工具创建，禁止删除：{branch_name}")
        _run_command(["git", "-C", str(repo_root), "branch", "-D", branch_name], cwd=repo_root)
        branch_deleted = True

    manifest_path.unlink(missing_ok=True)
    return {
        "tool_name": "exit_worktree",
        "workspace_dir": str(resolved_workspace),
        "runtime_dir": str(resolved_runtime),
        "repo_root": str(repo_root),
        "name": name,
        "safe_name": safe_name,
        "branch": branch_name,
        "branch_deleted": branch_deleted,
        "worktree_path": str(worktree_path),
        "removed_at": _now_iso(),
        "status": "removed",
    }


def schedule_cron(
    *,
    workspace_dir: Path,
    runtime_dir: Path | None = None,
    name: str,
    command: str,
    cron_expression: str,
    working_directory: Path | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """
    创建真实 Windows 计划任务。

    当前只支持 `*/N * * * *` 这类分钟级表达式，不支持的模式直接报错。

    :param workspace_dir: 工作区根目录。
    :param runtime_dir: 可选运行时目录。
    :param name: 计划任务名称。
    :param command: 需要执行的 PowerShell 语句。
    :param cron_expression: cron 表达式。
    :param working_directory: 任务执行目录。
    :param description: 附加说明。
    :return: 创建结果。
    """

    resolved_workspace = workspace_dir.resolve()
    resolved_runtime = _runtime_root(resolved_workspace, runtime_dir)
    cron_root = _ensure_directory(resolved_runtime / "cron")
    scripts_root = _ensure_directory(cron_root / "scripts")
    manifests_root = _ensure_directory(cron_root / "manifests")
    logs_root = _ensure_directory(cron_root / "logs")

    safe_name = _safe_name(name)
    normalized_command = str(command).strip()
    if not normalized_command:
        raise ValueError("command 不能为空")

    expression = str(cron_expression).strip()
    if not (expression.startswith("*/") and expression.endswith(" * * * *")):
        raise ValueError(f"当前仅支持分钟级 cron 表达式：{cron_expression}")

    minute_token = expression.split()[0]
    interval = int(minute_token[2:])
    if interval < 1:
        raise ValueError(f"cron 间隔必须大于 0：{cron_expression}")

    script_path = scripts_root / f"{safe_name}.ps1"
    manifest_path = manifests_root / f"{safe_name}.json"
    log_path = logs_root / f"{safe_name}.log"
    task_name = f"FuncodePy-{safe_name}"
    effective_workdir = (working_directory or resolved_workspace).resolve()
    escaped_workdir = str(effective_workdir).replace("'", "''")
    escaped_log_path = str(log_path.resolve()).replace("'", "''")

    script_lines = [
        "$ErrorActionPreference = 'Stop'",
        "Set-StrictMode -Version Latest",
        f"Set-Location -LiteralPath '{escaped_workdir}'",
        f"$logPath = '{escaped_log_path}'",
        "$logParent = Split-Path -Parent $logPath",
        "New-Item -ItemType Directory -Force -Path $logParent | Out-Null",
        normalized_command,
    ]
    script_path.write_text("\n".join(script_lines), encoding="utf-8")

    _run_command(
        [
            "schtasks.exe",
            "/Create",
            "/TN",
            task_name,
            "/TR",
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{script_path}"',
            "/SC",
            "MINUTE",
            "/MO",
            str(interval),
            "/F",
        ],
        cwd=resolved_workspace,
    )

    result = {
        "tool_name": "schedule_cron",
        "workspace_dir": str(resolved_workspace),
        "runtime_dir": str(resolved_runtime),
        "name": name,
        "safe_name": safe_name,
        "task_name": task_name,
        "cron_expression": expression,
        "schedule_kind": "minute",
        "interval_minutes": interval,
        "working_directory": str(effective_workdir),
        "script_path": str(script_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "log_path": str(log_path.resolve()),
        "description": "" if description is None else str(description),
        "created_at": _now_iso(),
        "status": "scheduled",
    }
    manifest_path.write_text(_render_json(result), encoding="utf-8")
    return result


def run_repl_script(
    *,
    workspace_dir: Path,
    runtime_dir: Path | None = None,
    script: str,
    session_id: str | None = None,
    max_turns: int | None = None,
    record_name: str | None = None,
) -> dict[str, Any]:
    """
    启动真实 Python 子进程执行脚本化 REPL。

    这里不依赖仓库内其他入口，直接使用 `python -i` 保证主工作区可见且可运行。

    :param workspace_dir: 工作区根目录。
    :param runtime_dir: 可选运行时目录。
    :param script: 需要执行的脚本文本。
    :param session_id: 预留会话参数。
    :param max_turns: 预留轮次参数。
    :param record_name: 记录名。
    :return: 执行结果。
    """

    resolved_workspace = workspace_dir.resolve()
    resolved_runtime = _runtime_root(resolved_workspace, runtime_dir)
    records_root = _ensure_directory(resolved_runtime / "repl" / "records")
    normalized_script = str(script).strip()
    if not normalized_script:
        raise ValueError("script 不能为空")

    safe_record_name = _safe_name(record_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    record_path = records_root / f"{safe_record_name}.json"

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "").strip()
    package_root = resolved_workspace / "JS2PY" / "src"
    env["PYTHONPATH"] = str(package_root) if not existing_pythonpath else f"{package_root}{os.pathsep}{existing_pythonpath}"

    stdin_payload = normalized_script
    if not stdin_payload.endswith("\n"):
        stdin_payload += "\n"

    completed = subprocess.run(
        [sys.executable, "-i", "-q"],
        cwd=str(resolved_workspace),
        env=env,
        input=stdin_payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    result = {
        "tool_name": "repl",
        "workspace_dir": str(resolved_workspace),
        "runtime_dir": str(resolved_runtime),
        "record_name": safe_record_name,
        "record_path": str(record_path.resolve()),
        "session_id": session_id,
        "max_turns": max_turns,
        "script": normalized_script,
        "return_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "created_at": _now_iso(),
        "status": "completed" if completed.returncode == 0 else "failed",
    }
    record_path.write_text(_render_json(result), encoding="utf-8")
    if completed.returncode != 0:
        raise ToolExecutionError(f"REPL 子进程执行失败，返回码={completed.returncode}，stderr={completed.stderr.strip()}")
    return result


class EnterWorktreeTool(BaseTool):
    """
    真实创建 Git worktree 的工具。
    """

    name = "enter_worktree"
    description = "真实创建 Git worktree，并将结果清单落盘到运行时目录。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        """
        执行 worktree 创建。

        :param arguments: 工具参数。
        :param context: 工具执行上下文。
        :return: 工具执行结果。
        """

        result = enter_worktree(
            workspace_dir=context.workspace_dir,
            runtime_dir=context.permission_context.runtime_dir,
            name=str(arguments["name"]),
            branch=str(arguments["branch"]) if arguments.get("branch") is not None else None,
            start_point=str(arguments.get("start_point", "HEAD")),
        )
        return ToolResult(tool_name=self.name, content=_render_json(result), metadata=result)


class ExitWorktreeTool(BaseTool):
    """
    真实移除 Git worktree 的工具。
    """

    name = "exit_worktree"
    description = "真实移除 Git worktree，并清理对应清单。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        """
        执行 worktree 移除。

        :param arguments: 工具参数。
        :param context: 工具执行上下文。
        :return: 工具执行结果。
        """

        result = exit_worktree(
            workspace_dir=context.workspace_dir,
            runtime_dir=context.permission_context.runtime_dir,
            name=str(arguments["name"]),
            delete_branch=bool(arguments.get("delete_branch", False)),
        )
        return ToolResult(tool_name=self.name, content=_render_json(result), metadata=result)


class ScheduleCronTool(BaseTool):
    """
    真实创建 Windows 计划任务的工具。
    """

    name = "schedule_cron"
    description = "将分钟级 cron 表达式映射为真实 Windows 计划任务。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        """
        执行 cron 调度创建。

        :param arguments: 工具参数。
        :param context: 工具执行上下文。
        :return: 工具执行结果。
        """

        result = schedule_cron(
            workspace_dir=context.workspace_dir,
            runtime_dir=context.permission_context.runtime_dir,
            name=str(arguments["name"]),
            command=str(arguments["command"]),
            cron_expression=str(arguments["cron"]),
            working_directory=Path(str(arguments["working_directory"])).resolve()
            if arguments.get("working_directory") is not None
            else None,
            description=str(arguments["description"]) if arguments.get("description") is not None else None,
        )
        return ToolResult(tool_name=self.name, content=_render_json(result), metadata=result)


class REPLTool(BaseTool):
    """
    真实执行 REPL 子进程的工具。
    """

    name = "repl"
    description = "启动真实 Python 子进程执行脚本化 REPL，并记录输出。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        """
        执行 REPL 脚本。

        :param arguments: 工具参数。
        :param context: 工具执行上下文。
        :return: 工具执行结果。
        """

        result = run_repl_script(
            workspace_dir=context.workspace_dir,
            runtime_dir=context.permission_context.runtime_dir,
            script=str(arguments["script"]),
            session_id=str(arguments["session_id"]) if arguments.get("session_id") is not None else None,
            max_turns=int(arguments["max_turns"]) if arguments.get("max_turns") is not None else None,
            record_name=str(arguments["record_name"]) if arguments.get("record_name") is not None else None,
        )
        return ToolResult(tool_name=self.name, content=_render_json(result), metadata=result)


_LSP_INDEXABLE_EXTENSIONS = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_LSP_SEARCHABLE_EXTENSIONS = _LSP_INDEXABLE_EXTENSIONS | {".json", ".md", ".toml", ".yml", ".yaml"}
_LSP_IGNORED_DIRECTORY_NAMES = {".git", ".venv", "__pycache__", "node_modules", ".funcode"}
_LSP_JS_PATTERNS = (
    ("class", re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")),
    ("variable", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
)


def _lsp_allowed(context: ToolExecutionContext, path: Path) -> Path:
    """执行 LSP/plan mode 的真实权限校验。"""

    return ensure_tool_path_allowed(context.permission_context, path)


def _lsp_relative(workspace_dir: Path, target_path: Path) -> str:
    """返回相对工作区路径。"""

    try:
        return str(target_path.resolve().relative_to(workspace_dir.resolve()))
    except ValueError:
        return str(target_path.resolve())


def _lsp_iter_workspace_files(workspace_dir: Path, extensions: set[str]) -> list[Path]:
    """遍历工作区内允许分析的真实文件。"""

    matched_files: list[Path] = []
    for file_path in workspace_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in _LSP_IGNORED_DIRECTORY_NAMES for part in file_path.parts):
            continue
        if file_path.suffix.lower() not in extensions:
            continue
        matched_files.append(file_path)
    return matched_files


def _plan_state_path(context: ToolExecutionContext) -> Path:
    """返回 plan mode 状态文件路径。"""

    return context.permission_context.plan_mode_state_path


def _plan_file_path(context: ToolExecutionContext) -> Path:
    """返回 plan mode 计划文件路径。"""

    return context.permission_context.plan_mode_plan_path


def _default_plan_mode_state(context: ToolExecutionContext) -> PlanModeState:
    """构造默认的 plan mode 状态。"""

    return PlanModeState(
        active=False,
        status="inactive",
        workspace_dir=str(context.workspace_dir.resolve()),
        plan_dir=str(context.permission_context.plan_dir.resolve()),
        state_file_path=str(_plan_state_path(context).resolve()),
        plan_file_path=str(_plan_file_path(context).resolve()),
        entered_at=None,
        exited_at=None,
        goal=None,
        steps=[],
        notes=None,
        last_actor=None,
        metadata={},
    )


def load_plan_mode_state(context: ToolExecutionContext) -> PlanModeState:
    """读取真实 plan mode 状态文件。"""

    state_path = _lsp_allowed(context, _plan_state_path(context))
    if not state_path.exists():
        return _default_plan_mode_state(context)
    return PlanModeState.model_validate_json(state_path.read_text(encoding="utf-8"))


def _write_plan_mode_state(context: ToolExecutionContext, state: PlanModeState) -> None:
    """写入真实 plan mode 状态文件。"""

    state_path = _lsp_allowed(context, _plan_state_path(context))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(_render_json(state.model_dump(mode="json")), encoding="utf-8")


def _write_plan_mode_plan(context: ToolExecutionContext, *, goal: str | None, steps: list[str], notes: str | None) -> Path:
    """写入真实 plan mode 计划文件。"""

    plan_path = _lsp_allowed(context, _plan_file_path(context))
    lines = ["# Plan Mode"]
    if goal:
        lines.extend(["", "## 目标", goal])
    if steps:
        lines.extend(["", "## 步骤"])
        lines.extend(f"{index + 1}. {step}" for index, step in enumerate(steps))
    if notes:
        lines.extend(["", "## 备注", notes])
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return plan_path


def enter_plan_mode(context: ToolExecutionContext, arguments: dict[str, Any]) -> PlanModeState:
    """进入真实 plan mode。"""

    current_state = load_plan_mode_state(context)
    if current_state.active:
        raise ToolExecutionError("当前已经处于 plan mode，禁止重复进入。")
    raw_steps = arguments.get("steps")
    plan_steps = [str(step).strip() for step in (raw_steps if isinstance(raw_steps, list) else context.plan_steps) if str(step).strip()]
    goal = str(arguments.get("goal") or "").strip() or None
    notes = str(arguments.get("notes") or "").strip() or None
    plan_path = _write_plan_mode_plan(context, goal=goal, steps=plan_steps, notes=notes)
    next_state = PlanModeState(
        active=True,
        status="planning",
        workspace_dir=str(context.workspace_dir.resolve()),
        plan_dir=str(context.permission_context.plan_dir.resolve()),
        state_file_path=str(_plan_state_path(context).resolve()),
        plan_file_path=str(plan_path.resolve()),
        entered_at=_now_iso(),
        exited_at=None,
        goal=goal,
        steps=plan_steps,
        notes=notes,
        last_actor=str(arguments.get("actor") or "assistant").strip(),
        metadata={"step_count": len(plan_steps), "entered_from_tool": "enter_plan_mode"},
    )
    _write_plan_mode_state(context, next_state)
    return next_state


def exit_plan_mode(context: ToolExecutionContext, arguments: dict[str, Any]) -> PlanModeState:
    """退出真实 plan mode。"""

    current_state = load_plan_mode_state(context)
    if not current_state.active:
        raise ToolExecutionError("当前不在 plan mode，无法退出。")
    raw_steps = arguments.get("steps")
    plan_steps = [str(step).strip() for step in (raw_steps if isinstance(raw_steps, list) else current_state.steps) if str(step).strip()]
    goal = str(arguments.get("goal") or "").strip() or current_state.goal
    notes = str(arguments.get("notes") or "").strip() or current_state.notes
    _write_plan_mode_plan(context, goal=goal, steps=plan_steps, notes=notes)
    next_state = PlanModeState(
        active=False,
        status="completed",
        workspace_dir=current_state.workspace_dir,
        plan_dir=current_state.plan_dir,
        state_file_path=current_state.state_file_path,
        plan_file_path=current_state.plan_file_path,
        entered_at=current_state.entered_at,
        exited_at=_now_iso(),
        goal=goal,
        steps=plan_steps,
        notes=notes,
        last_actor=str(arguments.get("actor") or "assistant").strip(),
        metadata={**current_state.metadata, "step_count": len(plan_steps), "exited_from_tool": "exit_plan_mode"},
    )
    _write_plan_mode_state(context, next_state)
    return next_state


def _python_symbols(file_path: Path, workspace_dir: Path) -> list[LspSymbol]:
    """提取 Python 文档符号。"""

    parsed_tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    collected_symbols: list[LspSymbol] = []

    def walk(node: ast.AST, container_name: str | None = None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                collected_symbols.append(LspSymbol(name=child.name, kind="class", path=_lsp_relative(workspace_dir, file_path), line=child.lineno, column=child.col_offset + 1, language="python", container_name=container_name, signature=f"class {child.name}"))
                walk(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments_text = ", ".join(argument.arg for argument in child.args.args)
                prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                collected_symbols.append(LspSymbol(name=child.name, kind="function", path=_lsp_relative(workspace_dir, file_path), line=child.lineno, column=child.col_offset + 1, language="python", container_name=container_name, signature=f"{prefix} {child.name}({arguments_text})"))
                walk(child, child.name)
            else:
                walk(child, container_name)

    walk(parsed_tree)
    return collected_symbols


def _javascript_symbols(file_path: Path, workspace_dir: Path) -> list[LspSymbol]:
    """提取 JS/TS 文档符号。"""

    collected_symbols: list[LspSymbol] = []
    seen_names: set[tuple[str, int]] = set()
    for line_number, raw_line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
        for symbol_kind, pattern in _LSP_JS_PATTERNS:
            matched = pattern.search(raw_line)
            if matched is None:
                continue
            dedupe_key = (matched.group(1), line_number)
            if dedupe_key in seen_names:
                continue
            seen_names.add(dedupe_key)
            collected_symbols.append(LspSymbol(name=matched.group(1), kind=symbol_kind, path=_lsp_relative(workspace_dir, file_path), line=line_number, column=matched.start(1) + 1, language="javascript", container_name=None, signature=raw_line.strip()))
            break
    return collected_symbols


def _document_symbols(file_path: Path, workspace_dir: Path) -> list[LspSymbol]:
    """提取单文件真实符号。"""

    if file_path.suffix.lower() in {".py", ".pyi"}:
        return _python_symbols(file_path, workspace_dir)
    if file_path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return _javascript_symbols(file_path, workspace_dir)
    raise ToolExecutionError(f"LSP 文档符号暂不支持该文件类型：{file_path.suffix}")


def _workspace_symbols(workspace_dir: Path, query: str | None) -> list[LspSymbol]:
    """提取工作区真实符号。"""

    normalized_query = str(query or "").strip().lower()
    matched_symbols: list[LspSymbol] = []
    for file_path in _lsp_iter_workspace_files(workspace_dir, _LSP_INDEXABLE_EXTENSIONS):
        try:
            file_symbols = _document_symbols(file_path, workspace_dir)
        except (SyntaxError, UnicodeDecodeError, ToolExecutionError):
            continue
        for symbol in file_symbols:
            if normalized_query and normalized_query not in symbol.name.lower():
                continue
            matched_symbols.append(symbol)
    return sorted(matched_symbols, key=lambda symbol: (symbol.path.casefold(), symbol.line, symbol.column, symbol.name.casefold()))


def _diagnostics(file_path: Path, workspace_dir: Path) -> list[LspDiagnostic]:
    """执行真实诊断。"""

    if file_path.suffix.lower() in {".py", ".pyi"}:
        try:
            source_text = file_path.read_text(encoding="utf-8")
            ast.parse(source_text, filename=str(file_path))
            py_compile.compile(str(file_path), doraise=True)
            return []
        except SyntaxError as exc:
            return [LspDiagnostic(path=_lsp_relative(workspace_dir, file_path), line=int(exc.lineno or 1), column=int(exc.offset or 1), severity="error", message=str(exc.msg or "Python 语法错误"), source="python-ast", code="SyntaxError")]
        except py_compile.PyCompileError as exc:
            return [LspDiagnostic(path=_lsp_relative(workspace_dir, file_path), line=1, column=1, severity="error", message=str(exc), source="py_compile", code="PyCompileError")]
    if file_path.suffix.lower() in {".js", ".mjs", ".cjs"}:
        completed = subprocess.run(["node", "--check", str(file_path.resolve())], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if completed.returncode == 0:
            return []
        return [LspDiagnostic(path=_lsp_relative(workspace_dir, file_path), line=1, column=1, severity="error", message=(completed.stderr or completed.stdout or "").strip() or "JavaScript 语法检查失败", source="node --check", code="NodeSyntaxError")]
    raise ToolExecutionError(f"LSP diagnostics 暂不支持该文件类型：{file_path.suffix}")


def _search_workspace(workspace_dir: Path, query: str, *, use_regex: bool, max_results: int) -> list[dict[str, Any]]:
    """执行工作区真实文本搜索。"""

    compiled_pattern = re.compile(query) if use_regex else re.compile(re.escape(query))
    matches: list[dict[str, Any]] = []
    for file_path in _lsp_iter_workspace_files(workspace_dir, _LSP_SEARCHABLE_EXTENSIONS):
        try:
            source_lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, raw_line in enumerate(source_lines, start=1):
            for matched in compiled_pattern.finditer(raw_line):
                matches.append({"path": _lsp_relative(workspace_dir, file_path), "line": line_number, "column": matched.start() + 1, "match_text": matched.group(0), "line_text": raw_line.strip()})
                if len(matches) >= max_results:
                    return matches
    return matches


class LspTool(BaseTool):
    """本地项目的真实 LSP 风格工具。"""

    name = "lsp"
    description = "基于真实本地项目执行 diagnostics、document_symbols、workspace_symbols、definition、references、hover、service_state 与 search。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        action = str(arguments.get("action") or arguments.get("operation") or "").strip().lower()
        if not action:
            raise ToolExecutionError("lsp 工具缺少 action 参数。")
        supported_actions = set(get_supported_lsp_actions())
        if action not in supported_actions:
            raise ToolExecutionError(f"不支持的 lsp action：{action}；当前支持：{', '.join(sorted(supported_actions))}")

        workspace_dir = context.workspace_dir.resolve()
        manager = get_lsp_manager(workspace_dir)

        file_path: Path | None = None
        raw_file_path = arguments.get("file_path")
        if raw_file_path is not None and str(raw_file_path).strip():
            file_path = _lsp_allowed(context, workspace_dir / str(raw_file_path))

        symbol_name = str(arguments.get("symbol") or arguments.get("query") or "").strip() or None
        line_number = int(arguments["line"]) if arguments.get("line") is not None else None
        column_number = int(arguments["column"]) if arguments.get("column") is not None else None
        max_results = int(arguments.get("max_results", 200))

        if action == "document_symbols":
            if file_path is None:
                raise ToolExecutionError("document_symbols 操作必须提供 file_path。")
            symbols = manager.document_symbols(file_path)
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "file_path": str(file_path.resolve()),
                "result_count": len(symbols),
                "symbols": [symbol.model_dump(mode="json") for symbol in symbols],
            }
        elif action == "workspace_symbols":
            language = str(arguments.get("language") or "").strip().lower() or None
            symbols = manager.workspace_symbols(query=symbol_name, language=language, max_results=max_results)
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "query": symbol_name,
                "language": language,
                "result_count": len(symbols),
                "symbols": [symbol.model_dump(mode="json") for symbol in symbols],
            }
        elif action == "diagnostics":
            if file_path is None:
                raise ToolExecutionError("diagnostics 操作必须提供 file_path。")
            diagnostics = manager.diagnostics(file_path)
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "file_path": str(file_path.resolve()),
                "result_count": len(diagnostics),
                "diagnostics": [diagnostic.model_dump(mode="json") for diagnostic in diagnostics],
            }
        elif action == "definition":
            definitions = manager.definition(
                file_path=file_path,
                symbol=symbol_name,
                line=line_number,
                column=column_number,
                max_results=max_results,
            )
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "file_path": str(file_path.resolve()) if file_path is not None else None,
                "query": symbol_name,
                "line": line_number,
                "column": column_number,
                "result_count": len(definitions),
                "definitions": [location.model_dump(mode="json") for location in definitions],
            }
        elif action == "references":
            references = manager.references(
                file_path=file_path,
                symbol=symbol_name,
                line=line_number,
                column=column_number,
                max_results=max_results,
            )
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "file_path": str(file_path.resolve()) if file_path is not None else None,
                "query": symbol_name,
                "line": line_number,
                "column": column_number,
                "result_count": len(references),
                "references": [reference.model_dump(mode="json") for reference in references],
            }
        elif action == "hover":
            hover = manager.hover(
                file_path=file_path,
                symbol=symbol_name,
                line=line_number,
                column=column_number,
            )
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "file_path": str(file_path.resolve()) if file_path is not None else None,
                "query": symbol_name,
                "line": line_number,
                "column": column_number,
                "result_count": 0 if hover is None else 1,
                "hover": hover.model_dump(mode="json") if hover is not None else None,
            }
        elif action == "search":
            query_text = str(arguments.get("query") or "").strip()
            if not query_text:
                raise ToolExecutionError("search 操作必须提供 query。")
            use_regex = bool(arguments.get("use_regex", False))
            matches = manager.search(query=query_text, use_regex=use_regex, max_results=max_results)
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "query": query_text,
                "use_regex": use_regex,
                "result_count": len(matches),
                "matches": matches,
            }
        elif action == "service_state":
            states = manager.service_state()
            payload = {
                "action": action,
                "workspace_dir": str(workspace_dir),
                "result_count": len(states),
                "states": [state.model_dump(mode="json") for state in states],
            }
        else:
            raise ToolExecutionError(f"不支持的 lsp action：{action}")

        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={
                "action": action,
                "result_count": int(payload["result_count"]),
                "file_path": payload.get("file_path"),
            },
        )


class EnterPlanModeTool(BaseTool):
    """进入真实 plan mode。"""

    name = "enter_plan_mode"
    description = "进入真实 plan mode，并写入状态文件与计划文件。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        state = enter_plan_mode(context, arguments)
        return ToolResult(tool_name=self.name, content=_render_json(state.model_dump(mode="json")), metadata={"active": state.active, "status": state.status, "state_file_path": state.state_file_path, "plan_file_path": state.plan_file_path})


class ExitPlanModeTool(BaseTool):
    """退出真实 plan mode。"""

    name = "exit_plan_mode"
    description = "退出真实 plan mode，并更新状态文件与计划文件。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        state = exit_plan_mode(context, arguments)
        return ToolResult(tool_name=self.name, content=_render_json(state.model_dump(mode="json")), metadata={"active": state.active, "status": state.status, "state_file_path": state.state_file_path, "plan_file_path": state.plan_file_path})
