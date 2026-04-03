"""
模块名称：bridge.server
功能描述：
    提供基于 stdin/stdout 的真实 NDJSON 桥接服务，用于让外部 JS 交互层通过统一事件流与 Python 后端通信。
    该模块只负责协议解析、请求分发、结果封装和错误标准化，不承担业务模拟或假数据生成。

主要组件：
    - NDJSONBridgeServer: NDJSON 协议服务实现。
    - run_stdio_bridge: 标准输入输出桥接入口。
    - build_help_payload: help 请求的真实返回数据。
    - build_doctor_payload: doctor 请求的真实返回数据。
    - build_run_payload: run 请求的真实返回数据。
    - build_status_payload: status 请求的真实返回数据。
    - build_session_payload: session 请求的真实返回数据。
    - build_tools_payload: tools 请求的真实返回数据。
    - build_mcp_payload: mcp 请求的真实返回数据。

依赖说明：
    - json: NDJSON 编解码。
    - os, sys: 环境变量、进程信息和标准流。
    - pathlib: 工作区路径解析。
    - funcode.cli.parser: CLI 命令列表。
    - funcode.config.loader: 真实运行配置加载。
    - funcode.config.paths: 工作区路径解析。
    - funcode.constants.metadata: 项目信息。
    - funcode.mcp.registry: 真实 MCP 资源枚举。
    - funcode.output: 真实执行结果渲染。
    - funcode.runtime.application: 真实执行链路。
    - funcode.schemas.core: 会话状态反序列化。
    - funcode.tools.registry: 真实工具注册表。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 扩充 NDJSON bridge 支持 status/session/tools/mcp，并统一事件与错误结构。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO

from funcode.cli.parser import CLI_COMMANDS
from funcode.config.loader import load_app_settings
from funcode.config.paths import resolve_workspace_path
from funcode.constants.metadata import PROJECT_NAME, PROJECT_VERSION
from funcode.mcp.registry import McpRegistry
from funcode.output import render_execution_result
from funcode.runtime.application import FuncodeApplication, build_execution_request
from funcode.schemas.core import SessionState
from funcode.tools.advanced import enter_worktree, exit_worktree, run_repl_script, schedule_cron
from funcode.tools.registry import create_default_tool_registry

_BRIDGE_METHODS: tuple[str, ...] = (
    "help",
    "doctor",
    "run",
    "status",
    "session",
    "tools",
    "mcp",
    "worktree",
    "cron",
    "repl",
    "exit",
    "quit",
)
_SUPPORTED_METHODS: tuple[str, ...] = _BRIDGE_METHODS
_PROTOCOL_NAME = "ndjson"
_PROTOCOL_VERSION = "1.0"
_EVENT_SCHEMA_VERSION = "1.1"
_RESPONSE_SCHEMA_VERSION = "1.1"


def _preload_module(module_name: str, module_path: Path) -> None:
    """
    预加载指定模块，绕过包初始化期间可能出现的循环导入。

    :param module_name: 目标模块完整名称。
    :param module_path: 模块源文件路径。
    """

    if module_name in sys.modules:
        return

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def _preload_supporting_modules() -> None:
    """
    预加载 bridge 运行所需的少量基础模块，降低入口阶段的导入耦合。
    """

    package_root = Path(__file__).resolve().parents[1]
    preload_targets = {
        "funcode.mcp.registry": package_root / "mcp" / "registry.py",
        "funcode.schemas.core": package_root / "schemas" / "core.py",
    }
    for module_name, module_path in preload_targets.items():
        _preload_module(module_name, module_path)


_preload_supporting_modules()


def _json_line(payload: dict[str, Any]) -> str:
    """
    将对象序列化为单行 NDJSON 文本。

    :param payload: 待输出的数据对象。
    :return: 单行 JSON 文本。
    """

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _now_iso_utc() -> str:
    """
    杩斿洖 UTC ISO 鏃堕棿銆?
    :return: UTC ISO 鏃堕棿瀛楃涓层€?
    """

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _workspace_runtime_root(workspace_dir: Path) -> Path:
    """
    璁＄畻妗ユ帴杩愯鏃剁洰褰曘€?
    :param workspace_dir: 宸ヤ綔鍖虹洰褰曘€?
    :return: 杩愯鏃剁洰褰曡矾寰勩€?
    """

    return workspace_dir.resolve() / ".funcode"


def _bridge_features() -> dict[str, Any]:
    """
    杩斿洖妗ユ帴鑳藉姏璇存槑锛屼緵 Ink/TUI 鍓嶇鍋氬崗璁嚜閫傚簲銆?
    :return: 鎬ц兘涓庡崗璁兘鍔涚殑缁撴瀯鍖栨弿杩般€?
    """

    return {
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "request_lifecycle_events": ["request.started", "request.finished", "request.failed"],
        "bridge_lifecycle_events": ["bridge.ready", "bridge.closing", "bridge.stopped"],
        "response_metadata_fields": ["method", "timestamp", "seq", "summary"],
        "compatibility_mode": "backward-compatible-ndjson-v1",
    }


def _preview_lines(text: str, *, max_lines: int = 3, max_chars: int = 120) -> list[str]:
    """
    鐢熸垚绠€鐭枃鏈瑙堣銆?
    :param text: 鍘熷鏂囨湰銆?
    :param max_lines: 鏈€澶ч瑙堣鏁般€?
    :param max_chars: 鍗曡鏈€澶ч暱搴︺€?
    :return: 棰勮琛屽垪琛ㄣ€?
    """

    preview: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if len(line) > max_chars:
            line = f"{line[:max_chars].rstrip()}..."
        preview.append(line)
        if len(preview) >= max_lines:
            break
    return preview


def _write_line(stream: TextIO, payload: dict[str, Any]) -> None:
    """
    将一条 NDJSON 记录写入目标流。

    :param stream: 目标输出流。
    :param payload: 待写出的消息对象。
    """

    stream.write(_json_line(payload))
    stream.write("\n")
    stream.flush()


def _normalize_params(raw_params: Any) -> dict[str, Any]:
    """
    将桥接请求参数规范化为字典。

    :param raw_params: 原始参数对象。
    :return: 规范化后的参数字典。
    :raises TypeError: 当参数不是 JSON 对象时触发。
    """

    if raw_params is None:
        return {}
    if isinstance(raw_params, dict):
        return dict(raw_params)
    raise TypeError("bridge params 必须是 JSON 对象")


def _resolve_workspace_dir(params: dict[str, Any]) -> Path:
    """
    解析当前请求对应的工作区目录。

    :param params: 已规范化的参数字典。
    :return: 实际可用的工作区目录。
    """

    cwd_value = params.get("cwd")
    if isinstance(cwd_value, str) and cwd_value.strip():
        return resolve_workspace_path(cwd_value.strip())
    return resolve_workspace_path(None)


def _build_error_payload(
    code: str,
    message: str,
    *,
    method: str | None = None,
    request_id: Any | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    构造统一的桥接错误对象。

    :param code: 错误码。
    :param message: 错误信息。
    :param method: 关联的方法名。
    :param request_id: 请求标识。
    :param details: 附加细节。
    :return: 标准化错误对象。
    """

    payload: dict[str, Any] = {"code": code, "message": message}
    if method is not None:
        payload["method"] = method
    if request_id is not None:
        payload["request_id"] = request_id
    if details:
        payload["details"] = details
    return payload


def _summarize_result(method: str, result: Any) -> dict[str, Any]:
    """
    生成事件流中的轻量摘要，便于 JS 侧展示和日志检索。

    :param method: 请求方法名。
    :param result: 方法返回结果。
    :return: 摘要对象。
    """

    if method == "run" and isinstance(result, dict):
        execution_result = result.get("execution_result") or {}
        rendered_output = str(result.get("rendered_output") or "")
        return {
            "method": method,
            "session_id": execution_result.get("session_id"),
            "graph_name": execution_result.get("graph_name"),
            "turn_count": execution_result.get("turn_count"),
            "success": execution_result.get("success"),
            "message_count": len(execution_result.get("messages") or []),
            "tool_call_count": len(execution_result.get("tool_calls") or []),
            "output_preview": _preview_lines(rendered_output),
        }
    if method == "help" and isinstance(result, dict):
        return {
            "method": method,
            "command_count": len(result.get("cli_commands") or []),
            "supported_method_count": len(result.get("supported_methods") or []),
        }
    if method == "doctor" and isinstance(result, dict):
        return {
            "method": method,
            "workspace_dir": result.get("workspace_dir"),
            "tool_count": result.get("tool_count"),
            "bridge_method_count": result.get("bridge_method_count"),
        }
    if method == "status" and isinstance(result, dict):
        return {
            "method": method,
            "session_count": result.get("session_count"),
            "tool_count": result.get("tool_count"),
            "mcp_resource_count": result.get("mcp_resource_count"),
        }
    if method == "session" and isinstance(result, dict):
        return {
            "method": method,
            "session_count": result.get("session_count"),
            "active_session_id": result.get("active_session_id"),
        }
    if method == "tools" and isinstance(result, dict):
        return {"method": method, "tool_count": result.get("tool_count")}
    if method == "mcp" and isinstance(result, dict):
        return {"method": method, "resource_count": result.get("resource_count")}
    if method == "worktree" and isinstance(result, dict):
        return {
            "method": method,
            "status": result.get("result", {}).get("status") if isinstance(result.get("result"), dict) else None,
            "name": result.get("result", {}).get("name") if isinstance(result.get("result"), dict) else None,
        }
    if method == "cron" and isinstance(result, dict):
        return {
            "method": method,
            "status": result.get("result", {}).get("status") if isinstance(result.get("result"), dict) else None,
            "task_name": result.get("result", {}).get("task_name") if isinstance(result.get("result"), dict) else None,
        }
    if method == "repl" and isinstance(result, dict):
        return {
            "method": method,
            "status": result.get("result", {}).get("status") if isinstance(result.get("result"), dict) else None,
            "record_path": result.get("result", {}).get("record_path") if isinstance(result.get("result"), dict) else None,
        }
    if method in {"exit", "quit"} and isinstance(result, dict):
        return {
            "method": method,
            "stopped": bool(result.get("stopped")),
            "reason": result.get("reason"),
        }
    return {"method": method}


def _emit_request_started(server: "NDJSONBridgeServer", request_id: Any, method: str, params: dict[str, Any]) -> None:
    """
    发送请求开始事件。
    """
    server._mark_request_started(request_id, method)
    server._emit_event(
        request_id,
        "request.started",
        {
            "stage": "started",
            "method": method,
            "request_id": request_id,
            "request": {
                "cwd": params.get("cwd"),
                "session_id": params.get("session_id"),
                "graph_name": params.get("graph_name", "main"),
                "output_format": params.get("output_format", "text"),
            },
        },
    )


def _emit_request_finished(server: "NDJSONBridgeServer", request_id: Any, method: str, result: Any) -> None:
    """
    发送请求完成事件。
    """
    summary_payload = _summarize_result(method, result)
    summary_payload["stage"] = "finished"
    duration_ms = server._pop_request_duration_ms(request_id, method)
    if duration_ms is not None:
        summary_payload["duration_ms"] = duration_ms
    server._emit_event(request_id, "request.finished", summary_payload)


def _emit_request_failed(server: "NDJSONBridgeServer", request_id: Any, method: str, error: dict[str, Any]) -> None:
    """
    发送请求失败事件。
    """
    failure_payload: dict[str, Any] = {"stage": "failed", "method": method, "error": error}
    duration_ms = server._pop_request_duration_ms(request_id, method)
    if duration_ms is not None:
        failure_payload["duration_ms"] = duration_ms
    server._emit_event(request_id, "request.failed", failure_payload)


def build_help_payload() -> dict[str, Any]:
    """
    构造 help 请求返回内容。
    """

    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "project_name": PROJECT_NAME,
        "project_version": PROJECT_VERSION,
        "supported_methods": list(_SUPPORTED_METHODS),
        "bridge_methods": list(_BRIDGE_METHODS),
        "bridge_features": _bridge_features(),
        "cli_commands": list(CLI_COMMANDS),
        "usage": f"python -m {PROJECT_NAME}.main <command> [options]",
    }


def build_doctor_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    构造 doctor 请求返回内容。
    """

    workspace_dir = _resolve_workspace_dir(params)
    tool_registry = create_default_tool_registry()
    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "python_version": sys.version.split()[0],
        "python_implementation": sys.implementation.name,
        "cli_command_count": len(CLI_COMMANDS),
        "bridge_method_count": len(_SUPPORTED_METHODS),
        "tool_count": len(tool_registry.list_tools()),
        "has_deepseek_api_key": bool(params.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")),
        "bridge_supported_methods": list(_SUPPORTED_METHODS),
        "bridge_features": _bridge_features(),
    }


def _build_runtime_namespace(params: dict[str, Any]) -> SimpleNamespace:
    """
    将桥接参数转换为 load_app_settings 可接受的命名空间对象。
    """

    return SimpleNamespace(
        command="run",
        cwd=params.get("cwd"),
        model=params.get("model"),
        api_key=params.get("api_key"),
        base_url=params.get("base_url"),
        reasoning_effort=params.get("reasoning_effort"),
        session_id=params.get("session_id"),
        max_turns=params.get("max_turns", 32),
        stream=params.get("stream", True),
        debug=params.get("debug", False),
        graph_name=params.get("graph_name", "main"),
        output_format=params.get("output_format", "text"),
        prompt=params.get("prompt"),
        system_prompt=params.get("system_prompt"),
    )


def build_run_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    执行真实运行链路并返回渲染结果。
    """

    settings = load_app_settings(_build_runtime_namespace(params))
    request = build_execution_request(
        settings=settings,
        user_input=params.get("prompt"),
        session_id=params.get("session_id"),
    )
    application = FuncodeApplication.from_request(request)
    result = application.execute(request)
    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "request": {
            "cwd": str(settings.runtime.workspace_dir),
            "session_id": request.session_id,
            "graph_name": request.graph_name,
            "output_format": request.output_format,
            "stream": request.stream,
            "debug": request.debug,
        },
        "execution_result": result.model_dump(mode="json"),
        "rendered_output": render_execution_result(result),
    }


def _session_directory(workspace_dir: Path) -> Path:
    """
    计算会话文件夹路径。
    """

    return workspace_dir / ".funcode" / "sessions"


def _load_session_snapshots(workspace_dir: Path) -> list[dict[str, Any]]:
    """
    从真实磁盘加载会话快照。
    """

    session_dir = _session_directory(workspace_dir)
    if not session_dir.exists():
        return []

    snapshots: list[dict[str, Any]] = []
    for session_file in sorted(session_dir.glob("*.json")):
        raw_text = session_file.read_text(encoding="utf-8")
        try:
            session_state = SessionState.model_validate_json(raw_text)
        except Exception as exc:
            snapshots.append({"path": str(session_file), "error": str(exc)})
            continue
        snapshots.append({"path": str(session_file), "session": session_state.model_dump(mode="json")})
    return snapshots


def build_status_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    返回当前桥接运行概况。
    """

    workspace_dir = _resolve_workspace_dir(params)
    tool_registry = create_default_tool_registry()
    mcp_registry = McpRegistry()
    mcp_registry.discover_workspace_resources(workspace_dir)
    sessions = _load_session_snapshots(workspace_dir)
    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "python_version": sys.version.split()[0],
        "python_implementation": sys.implementation.name,
        "session_id": params.get("session_id") or os.getenv("FUNCODE_SESSION_ID"),
        "session_count": len(sessions),
        "tool_count": len(tool_registry.list_tools()),
        "mcp_resource_count": len(mcp_registry.list_resources()),
        "bridge_supported_methods": list(_SUPPORTED_METHODS),
    }


def build_session_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    返回真实会话列表和当前活动会话。
    """

    workspace_dir = _resolve_workspace_dir(params)
    sessions = _load_session_snapshots(workspace_dir)
    current_session_id = params.get("session_id") or os.getenv("FUNCODE_SESSION_ID")
    active_session = None
    for snapshot in sessions:
        session_payload = snapshot.get("session")
        if isinstance(session_payload, dict) and session_payload.get("session_id") == current_session_id:
            active_session = snapshot
            break

    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "current_session_id": current_session_id,
        "session_count": len(sessions),
        "active_session": active_session,
        "sessions": sessions,
    }


def build_tools_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    返回真实工具注册表信息。
    """

    workspace_dir = _resolve_workspace_dir(params)
    tool_registry = create_default_tool_registry()
    tool_names = tool_registry.list_tools()
    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "tool_count": len(tool_names),
        "tools": tool_names,
        "brief_tool_available": "brief" in tool_names,
    }


def build_mcp_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    返回真实 MCP 资源信息。
    """

    workspace_dir = _resolve_workspace_dir(params)
    registry = McpRegistry()
    registry.discover_workspace_resources(workspace_dir)
    resources = registry.list_resources()
    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "resource_count": len(resources),
        "resources": [resource.model_dump(mode="json") for resource in resources],
    }


def build_worktree_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    创建或移除真实 Git worktree。

    :param params: bridge 参数。
    :return: worktree 执行结果。
    """

    workspace_dir = _resolve_workspace_dir(params)
    runtime_dir = _workspace_runtime_root(workspace_dir)
    action = str(params.get("action", "enter")).strip().lower()
    name = str(params.get("name", "")).strip()
    if not name:
        raise ValueError("worktree 调用必须提供 name 参数")

    if action in {"exit", "remove", "delete"}:
        result = exit_worktree(
            workspace_dir=workspace_dir,
            runtime_dir=runtime_dir,
            name=name,
            delete_branch=bool(params.get("delete_branch", False)),
        )
        normalized_action = "exit"
    else:
        result = enter_worktree(
            workspace_dir=workspace_dir,
            runtime_dir=runtime_dir,
            name=name,
            branch=str(params.get("branch")).strip() if params.get("branch") is not None else None,
            start_point=str(params.get("start_point", "HEAD")).strip() or "HEAD",
        )
        normalized_action = "enter"

    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "action": normalized_action,
        "result": result,
    }


def build_cron_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    创建真实 Windows 计划任务。

    :param params: bridge 参数。
    :return: cron 执行结果。
    """

    workspace_dir = _resolve_workspace_dir(params)
    runtime_dir = _workspace_runtime_root(workspace_dir)
    name = str(params.get("name", "")).strip()
    command = str(params.get("command", "")).strip()
    cron_expression = str(params.get("cron", params.get("cron_expression", ""))).strip()
    if not name:
        raise ValueError("cron 调用必须提供 name 参数")
    if not command:
        raise ValueError("cron 调用必须提供 command 参数")
    if not cron_expression:
        raise ValueError("cron 调用必须提供 cron 表达式")

    working_directory_value = params.get("working_directory") or params.get("cwd") or workspace_dir
    working_directory = Path(str(working_directory_value)).resolve()
    result = schedule_cron(
        workspace_dir=workspace_dir,
        runtime_dir=runtime_dir,
        name=name,
        command=command,
        cron_expression=cron_expression,
        working_directory=working_directory,
        description=str(params.get("description")).strip() if params.get("description") is not None else None,
    )
    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "result": result,
    }


def build_repl_payload(params: dict[str, Any]) -> dict[str, Any]:
    """
    执行真实的脚本化 REPL。

    :param params: bridge 参数。
    :return: REPL 执行结果。
    """

    workspace_dir = _resolve_workspace_dir(params)
    runtime_dir = _workspace_runtime_root(workspace_dir)
    script = str(params.get("script", "")).strip()
    if not script:
        raise ValueError("repl 调用必须提供 script 参数")

    result = run_repl_script(
        workspace_dir=workspace_dir,
        runtime_dir=runtime_dir,
        script=script,
        session_id=str(params.get("session_id")).strip() if params.get("session_id") is not None else None,
        max_turns=int(params["max_turns"]) if params.get("max_turns") is not None else None,
        record_name=str(params.get("record_name")).strip() if params.get("record_name") is not None else None,
    )
    return {
        "protocol": _PROTOCOL_NAME,
        "protocol_version": _PROTOCOL_VERSION,
        "event_schema_version": _EVENT_SCHEMA_VERSION,
        "response_schema_version": _RESPONSE_SCHEMA_VERSION,
        "workspace_dir": str(workspace_dir),
        "result": result,
    }


class NDJSONBridgeServer:
    """
    基于 stdin/stdout 的真实 NDJSON 桥接服务。
    """

    def __init__(self, stdin: TextIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> None:
        """
        初始化桥接服务。
        """

        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self._event_sequence = 0
        self._response_sequence = 0
        self._request_started_at: dict[str, float] = {}

    def _request_key(self, request_id: Any, method: str) -> str:
        """
        鏋勫缓璇锋眰鍞竴閿€?
        :param request_id: 璇锋眰 ID銆?
        :param method: 妗ユ帴鏂规硶銆?
        :return: 鍐呴儴閿€笺€?
        """

        request_part = "__none__" if request_id is None else str(request_id)
        return f"{method}:{request_part}"

    def _next_event_sequence(self) -> int:
        """
        鐢熸垚浜嬩欢搴忓垪鍙枫€?
        :return: 褰撳墠浜嬩欢搴忓垪鍙枫€?
        """

        self._event_sequence += 1
        return self._event_sequence

    def _next_response_sequence(self) -> int:
        """
        鐢熸垚鍝嶅簲搴忓垪鍙枫€?
        :return: 褰撳墠鍝嶅簲搴忓垪鍙枫€?
        """

        self._response_sequence += 1
        return self._response_sequence

    def _mark_request_started(self, request_id: Any, method: str) -> None:
        """
        璁板綍璇锋眰寮€濮嬫椂闂淬€?
        :param request_id: 璇锋眰 ID銆?
        :param method: 妗ユ帴鏂规硶銆?
        """

        self._request_started_at[self._request_key(request_id, method)] = time.perf_counter()

    def _pop_request_duration_ms(self, request_id: Any, method: str) -> int | None:
        """
        鍙栧嚭璇锋眰鑰楁椂锛堟绉掞級銆?
        :param request_id: 璇锋眰 ID銆?
        :param method: 妗ユ帴鏂规硶銆?
        :return: 姣鑰楁椂锛屾棤璁板綍鏃惰繑鍥?None銆?
        """

        started_at = self._request_started_at.pop(self._request_key(request_id, method), None)
        if started_at is None:
            return None
        return int((time.perf_counter() - started_at) * 1000)

    def _emit_response(
        self,
        request_id: Any,
        ok: bool,
        result: Any = None,
        error: dict[str, Any] | None = None,
        *,
        method: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """
        输出标准响应消息。
        """

        payload: dict[str, Any] = {
            "type": "response",
            "id": request_id,
            "ok": ok,
            "protocol": _PROTOCOL_NAME,
            "protocol_version": _PROTOCOL_VERSION,
            "response_schema_version": _RESPONSE_SCHEMA_VERSION,
            "timestamp": _now_iso_utc(),
            "seq": self._next_response_sequence(),
        }
        if method is not None:
            payload["method"] = method
        if summary:
            payload["summary"] = summary
        if ok:
            payload["result"] = result
        else:
            payload["error"] = error or _build_error_payload("bridge_error", "unknown error")
        _write_line(self.stdout, payload)

    def _emit_event(self, request_id: Any, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """
        输出标准事件消息。
        """

        event_payload: dict[str, Any] = {
            "type": "event",
            "id": request_id,
            "event": event_name,
            "protocol": _PROTOCOL_NAME,
            "protocol_version": _PROTOCOL_VERSION,
            "event_schema_version": _EVENT_SCHEMA_VERSION,
            "timestamp": _now_iso_utc(),
            "seq": self._next_event_sequence(),
        }
        if payload:
            event_payload["payload"] = payload
        _write_line(self.stdout, event_payload)

    def _handle_request(self, request: dict[str, Any]) -> tuple[bool, Any, dict[str, Any] | None]:
        """
        根据请求方法执行真实分发。
        """

        method = str(request.get("method") or request.get("command") or "").strip().lower()
        params = _normalize_params(request.get("params"))
        request_id = request.get("id")

        if method in {"exit", "quit"}:
            _emit_request_started(self, request_id, method, params)
            result_payload = {"stopped": True, "reason": "client_request", "method": method}
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "help":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_help_payload()
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "doctor":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_doctor_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "run":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_run_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "status":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_status_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "session":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_session_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "tools":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_tools_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "mcp":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_mcp_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "worktree":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_worktree_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "cron":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_cron_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None
        if method == "repl":
            _emit_request_started(self, request_id, method, params)
            result_payload = build_repl_payload(params)
            _emit_request_finished(self, request_id, method, result_payload)
            return True, result_payload, None

        error_payload = _build_error_payload(
            "unsupported_method",
            f"不支持的桥接方法：{method}",
            method=method or None,
            request_id=request_id,
            details={"supported_methods": list(_SUPPORTED_METHODS)},
        )
        _emit_request_failed(self, request_id, method, error_payload)
        return False, None, error_payload

    def serve(self) -> int:
        """
        运行桥接服务主循环。
        """

        self._emit_event(
            None,
            "bridge.ready",
            {
                "protocol": _PROTOCOL_NAME,
                "protocol_version": _PROTOCOL_VERSION,
                "supported_methods": list(_SUPPORTED_METHODS),
                "project_name": PROJECT_NAME,
                "project_version": PROJECT_VERSION,
                "event_schema_version": _EVENT_SCHEMA_VERSION,
                "response_schema_version": _RESPONSE_SCHEMA_VERSION,
                "bridge_features": _bridge_features(),
            },
        )

        for raw_line in self.stdin:
            line = raw_line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                self._emit_response(
                    request_id=None,
                    ok=False,
                    error=_build_error_payload(
                        "invalid_json",
                        str(exc),
                        details={"raw_line": line},
                    ),
                    method=None,
                )
                continue

            if not isinstance(request, dict):
                self._emit_response(
                    request_id=None,
                    ok=False,
                    error=_build_error_payload(
                        "invalid_request",
                        "bridge 请求必须是 JSON 对象",
                        details={"expected_type": "object"},
                    ),
                )
                continue

            method = str(request.get("method") or request.get("command") or "").strip().lower()
            try:
                ok, result, error = self._handle_request(request)
            except Exception as exc:
                error_payload = _build_error_payload(
                    "internal_error",
                    str(exc),
                    method=method or None,
                    request_id=request.get("id"),
                    details={"exception_type": exc.__class__.__name__},
                )
                if method:
                    _emit_request_failed(self, request.get("id"), method, error_payload)
                self._emit_response(
                    request_id=request.get("id"),
                    ok=False,
                    error=error_payload,
                    method=method or None,
                    summary={"method": method or None, "stage": "failed"},
                )
                continue

            response_summary = _summarize_result(method, result) if method else None
            if method in {"exit", "quit"}:
                self._emit_event(
                    request.get("id"),
                    "bridge.closing",
                    {"reason": "client_request", "method": method, "request_id": request.get("id")},
                )
                self._emit_response(
                    request.get("id"),
                    True,
                    result,
                    method=method,
                    summary=response_summary,
                )
                return 0

            self._emit_response(
                request.get("id"),
                ok,
                result,
                error,
                method=method or None,
                summary=response_summary,
            )

        self._emit_event(None, "bridge.stopped", {"reason": "stdin_closed"})
        return 0


def run_stdio_bridge(argv: list[str] | None = None) -> int:
    """
    启动标准输入输出桥接服务。
    """

    _ = argv
    server = NDJSONBridgeServer()
    return server.serve()
