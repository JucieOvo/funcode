"""
模块名称：runners
功能描述：
    负责 CLI 命令到运行时入口的分发。
    其中 run/chat/config 继续走完整运行时链路，help/status/files/tasks/memory/plan
    则在 CLI 层直接完成真实读取与输出，避免轻量命令被模型配置阻塞。
主要组件：
    - dispatch_command: 运行时命令分发。
    - dispatch_lightweight_command: 轻量命令分发。
依赖说明：
    - argparse: 命名空间类型。
    - json: 结构化输出。
    - pathlib: 工作目录与文件遍历。
    - funcode.cli.parser: 命令清单。
    - funcode.commands.models: 命令上下文。
    - funcode.commands.service: run/chat/config 运行链路。
    - funcode.memory: 会话记忆注入。
    - funcode.session: 会话持久化读取。
    - funcode.tools.registry: 工具数量统计。
    - funcode.swarm.store: 团队与任务持久化读取。
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 增加轻量命令前置分发。
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from dataclasses import asdict
from argparse import Namespace
from pathlib import Path
from typing import Any, Callable

from funcode.cli.parser import CLI_COMMANDS, LIGHTWEIGHT_COMMANDS
from funcode.agents import AgentRegistry
from funcode.config.settings import AppSettings
from funcode.compact import ContextCompressor
from funcode.commands.models import CommandContext
from funcode.commands.service import create_default_registry, execute_command
from funcode.commands.service import create_default_registry
from funcode.memory import MemoryInjector
from funcode.mcp.registry import McpRegistry, McpResource
from funcode.permissions.context import create_permission_context
from funcode.session import SessionRepository, SessionState
from funcode.session.repository import SESSION_ROOT_DIRECTORY_NAME
from funcode.tools.registry import create_default_tool_registry


def _load_runtime_callable(attribute_name: str) -> Callable[..., Any]:
    """
    寤惰繜鍔犺浇杩愯鏃跺叆鍙ｅ嚱鏁般€?
    :param attribute_name: 杩愯鏃舵ā鍧椾腑鐨勫嚱鏁板悕銆?    :return: 鍙皟鐢ㄥ璞°€?    :raises ImportError: 褰撹繍琛屾椂妯″潡鎴栧叆鍙ｇ己澶辨椂瑙﹀彂銆?    """

    try:
        runtime_module = importlib.import_module("funcode.runtime.application")
    except ModuleNotFoundError as exc:
        raise ImportError(
            "杩愯鏃舵ā鍧?funcode.runtime.application 灏氭湭鍑嗗瀹屾垚锛?"
            "璇风户缁ˉ榻?runtime 瀛愮郴缁熴€?"
        ) from exc

    try:
        callback = getattr(runtime_module, attribute_name)
    except AttributeError as exc:
        raise ImportError(f"杩愯鏃舵ā鍧楃己灏戝叆鍙ｅ嚱鏁帮細{attribute_name}") from exc
    if not callable(callback):
        raise TypeError(f"runtime entry is not callable: {attribute_name}")
    return callback


def _namespace_from_settings(settings: AppSettings) -> Namespace:
    """
    灏嗗畬鏁撮厤缃璞¤浆鎹负鍛藉悕绌洪棿锛屼緵杞婚噺鍛戒护澶嶇敤銆?
    :param settings: 搴旂敤閰嶇疆銆?    :return: argparse 鍛藉悕绌洪棿銆?    """

    return Namespace(
        command=settings.cli.command,
        cwd=str(settings.runtime.workspace_dir),
        model=settings.model.model_name,
        api_key=settings.model.api_key,
        base_url=settings.model.base_url,
        reasoning_effort=settings.model.reasoning_effort,
        session_id=settings.runtime.session_id,
        max_turns=settings.runtime.max_turns,
        stream=settings.runtime.stream,
        debug=settings.runtime.debug,
        graph_name=settings.cli.graph_name,
        output_format=settings.cli.output_format,
        prompt=settings.cli.prompt,
        system_prompt=settings.cli.system_prompt,
    )


def _resolve_workspace_dir(namespace: Namespace) -> Path:
    """
    瑙ｆ瀽宸ヤ綔鐩綍銆?
    :param namespace: 瑙ｆ瀽鍚庣殑鍛藉悕绌洪棿銆?    :return: 鐪熷疄宸ヤ綔鐩綍璺緞銆?    """

    cwd_value = getattr(namespace, "cwd", None)
    if cwd_value:
        return Path(str(cwd_value)).expanduser().resolve()
    return Path.cwd().resolve()


def _resolve_output_format(namespace: Namespace) -> str:
    """
    瑙ｆ瀽杈撳嚭鏍煎紡銆?
    :param namespace: 瑙ｆ瀽鍚庣殑鍛藉悕绌洪棿銆?    :return: 杈撳嚭鏍煎紡鏂囨湰銆?    """

    output_format = getattr(namespace, "output_format", None)
    if isinstance(output_format, str) and output_format.strip():
        return output_format.strip().lower()
    return "text"


def _workspace_runtime_root(workspace_dir: Path) -> Path:
    """
    计算工作区下的运行时根目录。
    :param workspace_dir: 工作区目录。
    :return: 运行时根目录。
    """

    return workspace_dir / ".funcode"


def _package_root() -> Path:
    """
    获取 Python 包根目录。

    :return: 包根目录路径。
    """

    return Path(__file__).resolve().parents[1]


def _candidate_skill_roots(workspace_dir: Path) -> list[Path]:
    """
    生成当前工作区与本机可见的 skills 目录候选列表。

    :param workspace_dir: 当前工作区目录。
    :return: 候选 skills 根目录列表。
    """

    candidate_roots: list[Path] = [
        workspace_dir / "skills",
        workspace_dir / "src" / "skills",
        workspace_dir / ".codex" / "skills",
        workspace_dir / ".funcode" / "skills",
    ]

    codex_home = os.getenv("CODEX_HOME")
    if codex_home:
        candidate_roots.append(Path(codex_home).expanduser() / "skills")

    home_dir = Path.home()
    candidate_roots.extend(
        [
            home_dir / ".codex" / "skills",
            home_dir / ".agents" / "skills",
            home_dir / ".funcode" / "skills",
        ]
    )

    visible_roots: list[Path] = []
    seen_roots: set[str] = set()
    for candidate_root in candidate_roots:
        if not candidate_root.exists() or not candidate_root.is_dir():
            continue
        resolved_root = str(candidate_root.resolve())
        dedupe_key = resolved_root.casefold() if os.name == "nt" else resolved_root
        if dedupe_key in seen_roots:
            continue
        seen_roots.add(dedupe_key)
        visible_roots.append(candidate_root)
    return visible_roots


def _collect_skill_overview(workspace_dir: Path) -> dict[str, Any]:
    """
    扫描当前工作区与本机可见 skills 目录，汇总真实技能概况。

    这里只读取真实目录，不推断不存在的技能，不返回任何假数据。

    :param workspace_dir: 当前工作区目录。
    :return: skills 概况载荷。
    """

    workspace_dir = workspace_dir.resolve()
    skill_roots = _candidate_skill_roots(workspace_dir)
    root_payloads: list[dict[str, Any]] = []
    skill_locations: dict[str, list[dict[str, str]]] = {}

    for skill_root in skill_roots:
        visible_entries: list[dict[str, str]] = []
        for entry in sorted(skill_root.iterdir(), key=lambda path: path.name.casefold()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            resolved_entry = entry.resolve(strict=False)
            location_payload = {
                "root": str(skill_root),
                "path": str(entry),
                "resolved_path": str(resolved_entry),
            }
            visible_entries.append(location_payload)
            skill_locations.setdefault(entry.name, []).append(location_payload)

        root_payloads.append(
            {
                "root": str(skill_root),
                "skill_count": len(visible_entries),
                "skills": visible_entries,
            }
        )

    grouped_skills: list[dict[str, Any]] = []
    for skill_name in sorted(skill_locations, key=str.casefold):
        locations = sorted(
            skill_locations[skill_name],
            key=lambda item: (item["root"].casefold(), item["path"].casefold()),
        )
        grouped_skills.append(
            {
                "skill_name": skill_name,
                "occurrence_count": len(locations),
                "locations": locations,
            }
        )

    return {
        "workspace_dir": str(workspace_dir),
        "skill_root_count": len(root_payloads),
        "skill_occurrence_count": sum(item["skill_count"] for item in root_payloads),
        "unique_skill_count": len(grouped_skills),
        "skill_roots": root_payloads,
        "skills": grouped_skills,
    }


def _collect_plugin_surface(workspace_dir: Path) -> dict[str, Any]:
    """
    汇总当前 Python 版已实现的扩展面、命令/工具/MCP 规模与预留接口。

    :param workspace_dir: 当前工作区目录。
    :return: 插件/扩展面概况载荷。
    """

    package_root = _package_root()
    command_names = create_default_registry().list_commands()
    tool_names = create_default_tool_registry().list_tools()
    mcp_registry = McpRegistry()
    readme_path = workspace_dir.resolve() / "README.md"
    if readme_path.exists():
        mcp_registry.register(
            McpResource(
                uri="workspace://README.md",
                title="工作区 README",
                path=readme_path,
                description="工作区根目录 README 文件。",
            )
        )
    mcp_resources = [
        {
            "uri": resource.uri,
            "title": resource.title,
            "path": str(resource.path),
            "description": resource.description,
        }
        for resource in mcp_registry.list_resources()
    ]

    surface_names = [
        "agents",
        "cli",
        "commands",
        "compact",
        "config",
        "constants",
        "graph",
        "llm",
        "mcp",
        "memory",
        "output",
        "permissions",
        "runtime",
        "schemas",
        "session",
        "swarm",
        "tools",
        "utils",
    ]
    implemented_surfaces: list[dict[str, str]] = []
    for surface_name in surface_names:
        surface_path = package_root / surface_name
        if surface_path.exists() and surface_path.is_dir():
            implemented_surfaces.append(
                {
                    "surface_name": surface_name,
                    "path": str(surface_path),
                }
            )

    reserved_interfaces = [
        {
            "interface": "funcode.commands.service.create_default_registry",
            "purpose": "命令注册入口，承载后续命令扩展。",
        },
        {
            "interface": "funcode.tools.create_default_tool_registry",
            "purpose": "工具注册入口，承载后续工具扩展。",
        },
        {
            "interface": "funcode.mcp.registry.McpRegistry",
            "purpose": "MCP 资源注册入口，承载后续资源扩展。",
        },
    ]

    return {
        "workspace_dir": str(workspace_dir.resolve()),
        "package_root": str(package_root),
        "command_count": len(command_names),
        "tool_count": len(tool_names),
        "mcp_resource_count": len(mcp_resources),
        "mcp_resources": mcp_resources,
        "implemented_surface_count": len(implemented_surfaces),
        "implemented_surfaces": implemented_surfaces,
        "reserved_interfaces": reserved_interfaces,
    }


def _dump_output(payload: Any, output_format: str) -> int:
    """
    杈撳嚭鍛戒护缁撴灉銆?
    :param payload: 寰呰緭鍑哄唴瀹广€?    :param output_format: 杈撳嚭鏍煎紡銆?    :return: 閫€鍑虹爜銆?    """

    if output_format == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    elif isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    try:
        print(text)
    except UnicodeEncodeError:
        stdout_encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.buffer.write(text.encode(stdout_encoding, errors="replace"))
        sys.stdout.buffer.write(b"\n")
    return 0


def _select_session_state(repository: SessionRepository, session_id: str | None) -> SessionState | None:
    """
    閫夋嫨鐢ㄤ簬鍙鍛戒护鐨勪細璇濆揩鐓с€?
    :param repository: 浼氳瘽浠撳簱銆?    :param session_id: 浼樺厛浣跨敤鐨勪細璇?ID銆?    :return: 浼氳瘽鐘舵€佹垨 None銆?    """

    if session_id and repository.exists(session_id):
        return repository.load(session_id)

    if not repository.storage_dir.exists():
        return None

    session_files = sorted(
        repository.storage_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not session_files:
        return None
    return SessionState.model_validate_json(session_files[0].read_text(encoding="utf-8"))


def _list_session_files(repository: SessionRepository) -> list[Path]:
    """
    获取当前工作区中全部会话文件。
    :param repository: 会话仓库。
    :return: 按最近修改时间排序的会话文件列表。
    """

    if not repository.storage_dir.exists():
        return []
    return sorted(
        (path for path in repository.storage_dir.glob("*.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _session_file_payloads(repository: SessionRepository) -> list[dict[str, Any]]:
    """
    将会话文件整理为可输出的结构化摘要。
    :param repository: 会话仓库。
    :return: 会话文件摘要列表。
    """

    return [
        {
            "session_id": session_file.stem,
            "path": str(session_file),
        }
        for session_file in _list_session_files(repository)
    ]


def _delete_session_files(repository: SessionRepository, session_id: str | None) -> dict[str, Any]:
    """
    按真实文件系统删除会话缓存。
    :param repository: 会话仓库。
    :param session_id: 指定会话 ID；为空时清理全部会话文件。
    :return: 删除结果摘要。
    :raises FileNotFoundError: 当指定的会话文件不存在时触发。
    """

    deleted_files: list[str] = []
    if session_id:
        session_file = repository.get_session_file_path(session_id)
        if not session_file.exists():
            raise FileNotFoundError(f"会话文件不存在：{session_file}")
        session_file.unlink()
        deleted_files.append(str(session_file))
    else:
        for session_file in _list_session_files(repository):
            session_file.unlink()
            deleted_files.append(str(session_file))

    remaining_files = _list_session_files(repository)
    return {
        "deleted_count": len(deleted_files),
        "deleted_files": deleted_files,
        "remaining_count": len(remaining_files),
        "remaining_files": [str(path) for path in remaining_files],
    }


def _load_swarm_summary(workspace_dir: Path) -> dict[str, Any]:
    """
    璇诲彇鍥㈤槦涓庝换鍔℃鍐点€?
    :param workspace_dir: 宸ヤ綔鐩綍銆?    :return: 鍥㈤槦涓庝换鍔℃憳瑕併€?    """

    swarm_root = workspace_dir / ".funcode" / "swarm"
    teams_dir = swarm_root / "teams"
    tasks_dir = swarm_root / "tasks"

    teams: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []

    if teams_dir.exists():
        for team_file in sorted(teams_dir.glob("*.json")):
            team_data = json.loads(team_file.read_text(encoding="utf-8"))
            teams.append(
                {
                    "team_name": team_data.get("team_name", team_file.stem),
                    "description": team_data.get("description", ""),
                    "workspace_dir": team_data.get("workspace_dir", ""),
                }
            )

    if tasks_dir.exists():
        for team_task_dir in sorted(tasks_dir.iterdir()):
            if not team_task_dir.is_dir():
                continue
            for task_file in sorted(team_task_dir.glob("*.json")):
                task_data = json.loads(task_file.read_text(encoding="utf-8"))
                tasks.append(
                    {
                        "team_name": task_data.get("team_name", team_task_dir.name),
                        "task_id": task_data.get("task_id", task_file.stem),
                        "subject": task_data.get("subject", ""),
                        "status": task_data.get("status", ""),
                        "owner": task_data.get("owner"),
                    }
                )

    return {
        "swarm_root": str(swarm_root),
        "team_count": len(teams),
        "task_count": len(tasks),
        "teams": teams,
        "tasks": tasks,
    }


def _load_mcp_resources(workspace_dir: Path) -> dict[str, Any]:
    """
    璇诲彇宸ヤ綔鍖哄唴鍙鐨?MCP 璧勬簮鏂囦欢銆?    杩欓噷閲囩敤鐪熷疄鏂囦欢绯荤粺鎵弿锛屼笉鏋勯€犱吉閫犺祫婧愩€?    :param workspace_dir: 宸ヤ綔鍖虹洰褰曘€?    :return: MCP 璧勬簮姒傚喌銆?    """

    mcp_root = workspace_dir / ".funcode" / "mcp"
    resources: list[dict[str, Any]] = []

    if mcp_root.exists():
        for resource_path in sorted(mcp_root.rglob("*")):
            if not resource_path.is_file():
                continue
            resources.append(
                {
                    "name": resource_path.name,
                    "path": str(resource_path),
                    "kind": resource_path.suffix.lstrip(".").lower() or "file",
                }
            )

    return {
        "mcp_root": str(mcp_root),
        "resource_count": len(resources),
        "resources": resources,
    }


def _load_mailbox_messages(workspace_dir: Path) -> dict[str, Any]:
    """
    读取工作区内共享邮箱的真实消息。
    :param workspace_dir: 工作区目录。
    :return: 邮箱消息概况。
    """

    mailbox_path = workspace_dir / ".funcode" / "swarm" / "mailbox.jsonl"
    messages: list[dict[str, Any]] = []
    if mailbox_path.exists():
        for line_number, raw_line in enumerate(mailbox_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"邮箱文件内容损坏：{mailbox_path} 第 {line_number} 行") from exc
            if isinstance(message, dict):
                messages.append(
                    {
                        "message_id": message.get("message_id"),
                        "team_name": message.get("team_name"),
                        "sender": message.get("sender"),
                        "recipient": message.get("recipient"),
                        "subject": message.get("subject"),
                        "created_at": message.get("created_at"),
                    }
                )

    return {
        "mailbox_path": str(mailbox_path),
        "message_count": len(messages),
        "messages": messages,
    }


def _render_help(namespace: Namespace) -> int:
    """
    杈撳嚭 CLI 甯姪鎽樿銆?
    :return: 閫€鍑虹爜銆?    """

    output_format = _resolve_output_format(namespace)
    if output_format == "json":
        payload = {
            "commands": list(CLI_COMMANDS),
            "usage": "python -m funcode.main <command> [options]",
        }
        return _dump_output(payload, "json")

    lines = ["鍙敤鍛戒护:"]
    for command_name in CLI_COMMANDS:
        lines.append(f"- {command_name}")
    lines.append("")
    lines.append("杩愯鏂瑰紡: python -m funcode.main <command> [options]")
    return _dump_output("\n".join(lines), "text")


def _render_env(namespace: Namespace) -> int:
    """
    杈撳嚭褰撳墠杩涚▼鍜屽伐浣滅┖闂寸殑鐜淇℃伅銆?
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    output_format = _resolve_output_format(namespace)
    selected_variables = (
        "PYTHONPATH",
        "DEEPSEEK_BASE_URL",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "PATH",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "LANG",
        "PYTHONIOENCODING",
        "CODEX_HOME",
    )
    selected_env = {
        variable_name: os.getenv(variable_name)
        for variable_name in selected_variables
        if os.getenv(variable_name) is not None
    }
    payload = {
        "workspace_dir": str(workspace_dir),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "deepseek_api_key_present": bool(os.getenv("DEEPSEEK_API_KEY")),
        "selected_environment": selected_env,
        "environment_count": len(os.environ),
    }
    if output_format == "json":
        return _dump_output(payload, "json")

    lines = [
        f"workspace_dir: {payload['workspace_dir']}",
        f"python_executable: {payload['python_executable']}",
        f"python_version: {payload['python_version']}",
        f"python_implementation: {payload['python_implementation']}",
        f"platform: {payload['platform']}",
        f"deepseek_api_key_present: {payload['deepseek_api_key_present']}",
        f"environment_count: {payload['environment_count']}",
    ]
    for variable_name, variable_value in selected_env.items():
        lines.append(f"{variable_name}: {variable_value}")
    return _dump_output("\n".join(lines), "text")


def _render_brief(namespace: Namespace) -> int:
    """
    输出工作区当前状态的简要摘要。
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    output_format = _resolve_output_format(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))
    memory_injector = MemoryInjector()
    swarm_summary = _load_swarm_summary(workspace_dir)
    mcp_summary = _load_mcp_resources(workspace_dir)
    mailbox_summary = _load_mailbox_messages(workspace_dir)
    tool_registry = create_default_tool_registry()
    session_count = len(_list_session_files(session_repo))

    if session_state is None:
        payload = {
            "workspace_dir": str(workspace_dir),
            "selected_session": None,
            "session_count": session_count,
            "turn_count": 0,
            "message_count": 0,
            "tool_call_count": 0,
            "plan_step_count": 0,
            "summary_text": "",
            "recent_messages": [],
            "latest_output": None,
            "tool_count": len(tool_registry.list_tools()),
            "team_count": swarm_summary["team_count"],
            "task_count": swarm_summary["task_count"],
            "mcp_resource_count": mcp_summary["resource_count"],
            "mailbox_message_count": mailbox_summary["message_count"],
        }
        if output_format == "json":
            return _dump_output(payload, "json")

        lines = [
            f"workspace_dir: {payload['workspace_dir']}",
            f"selected_session: {payload['selected_session']}",
            f"session_count: {payload['session_count']}",
            f"turn_count: {payload['turn_count']}",
            f"message_count: {payload['message_count']}",
            f"tool_call_count: {payload['tool_call_count']}",
            f"plan_step_count: {payload['plan_step_count']}",
            f"tool_count: {payload['tool_count']}",
            f"team_count: {payload['team_count']}",
            f"task_count: {payload['task_count']}",
            f"mcp_resource_count: {payload['mcp_resource_count']}",
            f"mailbox_message_count: {payload['mailbox_message_count']}",
        ]
        return _dump_output("\n".join(lines), "text")

    snapshot = memory_injector.build_snapshot(session_state.messages)
    payload = {
        "workspace_dir": str(workspace_dir),
        "selected_session": session_state.model_dump(mode="json"),
        "session_count": session_count,
        "turn_count": session_state.turn_count,
        "message_count": len(session_state.messages),
        "tool_call_count": len(session_state.tool_calls),
        "plan_step_count": len(session_state.plan_steps),
        "summary_text": snapshot.summary_text,
        "recent_messages": snapshot.recent_messages,
        "latest_output": session_state.latest_output,
        "tool_count": len(tool_registry.list_tools()),
        "team_count": swarm_summary["team_count"],
        "task_count": swarm_summary["task_count"],
        "mcp_resource_count": mcp_summary["resource_count"],
        "mailbox_message_count": mailbox_summary["message_count"],
    }
    if output_format == "json":
        return _dump_output(payload, "json")

    lines = [
        f"workspace_dir: {payload['workspace_dir']}",
        f"selected_session: {session_state.session_id}",
        f"session_count: {payload['session_count']}",
        f"turn_count: {payload['turn_count']}",
        f"message_count: {payload['message_count']}",
        f"tool_call_count: {payload['tool_call_count']}",
        f"plan_step_count: {payload['plan_step_count']}",
        f"tool_count: {payload['tool_count']}",
        f"team_count: {payload['team_count']}",
        f"task_count: {payload['task_count']}",
        f"mcp_resource_count: {payload['mcp_resource_count']}",
        f"mailbox_message_count: {payload['mailbox_message_count']}",
        f"summary_text: {payload['summary_text']}",
    ]
    if payload["recent_messages"]:
        lines.append("recent_messages:")
        for message in payload["recent_messages"]:
            lines.append(f"- {message}")
    if payload["latest_output"] is not None:
        lines.append(f"latest_output: {payload['latest_output']}")
    return _dump_output("\n".join(lines), "text")


def _render_status(namespace: Namespace) -> int:
    """
    杈撳嚭杩愯鐘舵€併€?
    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    tool_registry = create_default_tool_registry()
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))

    payload = {
        "workspace_dir": str(workspace_dir),
        "graph_name": getattr(namespace, "graph_name", "main"),
        "output_format": _resolve_output_format(namespace),
        "session_id": getattr(namespace, "session_id", None),
        "registered_commands": list(CLI_COMMANDS),
        "registered_tools": tool_registry.list_tools(),
        "tool_count": len(tool_registry.list_tools()),
        "session_count": len(list(session_repo.storage_dir.glob("*.json"))) if session_repo.storage_dir.exists() else 0,
        "active_session": session_state.session_id if session_state is not None else None,
        "turn_count": session_state.turn_count if session_state is not None else 0,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_files(namespace: Namespace) -> int:
    """
    鍒楀嚭宸ヤ綔鍖烘牴鐩綍鏂囦欢銆?
    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    entries: list[dict[str, Any]] = []
    for entry in sorted(workspace_dir.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        entries.append(
            {
                "name": entry.name,
                "kind": "file" if entry.is_file() else "dir",
                "path": str(entry),
            }
        )
    payload = {
        "workspace_dir": str(workspace_dir),
        "count": len(entries),
        "entries": entries,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_tasks(namespace: Namespace) -> int:
    """
    杈撳嚭浼氳瘽涓庡洟闃熶换鍔℃鍐点€?
    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))
    swarm_summary = _load_swarm_summary(workspace_dir)

    session_files: list[str] = []
    if session_repo.storage_dir.exists():
        session_files = [path.stem for path in sorted(session_repo.storage_dir.glob("*.json"))]

    payload = {
        "workspace_dir": str(workspace_dir),
        "selected_session": session_state.session_id if session_state is not None else None,
        "session_turn_count": session_state.turn_count if session_state is not None else 0,
        "session_plan_steps": list(session_state.plan_steps) if session_state is not None else [],
        "session_files": session_files,
        "swarm": swarm_summary,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_memory(namespace: Namespace) -> int:
    """
    杈撳嚭浼氳瘽璁板繂鎽樿銆?
    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))
    memory_injector = MemoryInjector()

    if session_state is None:
        payload = {
            "workspace_dir": str(workspace_dir),
            "selected_session": None,
            "summary_text": "",
            "recent_messages": [],
            "total_messages": 0,
        }
        return _dump_output(payload, _resolve_output_format(namespace))

    snapshot = memory_injector.build_snapshot(session_state.messages)
    payload = {
        "workspace_dir": str(workspace_dir),
        "selected_session": session_state.session_id,
        "summary_text": snapshot.summary_text,
        "recent_messages": snapshot.recent_messages,
        "total_messages": snapshot.total_messages,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_plan(namespace: Namespace) -> int:
    """
    杈撳嚭褰撳墠璁″垝姝ラ銆?
    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))

    payload = {
        "workspace_dir": str(workspace_dir),
        "selected_session": session_state.session_id if session_state is not None else None,
        "plan_steps": list(session_state.plan_steps) if session_state is not None else [],
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_session(namespace: Namespace) -> int:
    """
    杈撳嚭浼氳瘽瀛樺偍姒傚喌銆?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    selected_session = _select_session_state(session_repo, getattr(namespace, "session_id", None))

    session_files: list[dict[str, Any]] = []
    if session_repo.storage_dir.exists():
        for session_file in sorted(session_repo.storage_dir.glob("*.json")):
            session_files.append(
                {
                    "session_id": session_file.stem,
                    "path": str(session_file),
                }
            )

    payload = {
        "workspace_dir": str(workspace_dir),
        "session_count": len(session_files),
        "session_files": session_files,
        "selected_session": selected_session.model_dump(mode="json") if selected_session is not None else None,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_resume(namespace: Namespace) -> int:
    """
    输出最近会话的恢复概况。
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))
    memory_injector = MemoryInjector()

    if session_state is None:
        payload = {
            "workspace_dir": str(workspace_dir),
            "selected_session": None,
            "session_count": len(_list_session_files(session_repo)),
            "session_files": _session_file_payloads(session_repo),
            "summary_text": "",
            "recent_messages": [],
            "total_messages": 0,
            "plan_steps": [],
            "latest_output": None,
        }
        return _dump_output(payload, _resolve_output_format(namespace))

    snapshot = memory_injector.build_snapshot(session_state.messages)
    payload = {
        "workspace_dir": str(workspace_dir),
        "selected_session": session_state.model_dump(mode="json"),
        "session_count": len(_list_session_files(session_repo)),
        "session_files": _session_file_payloads(session_repo),
        "summary_text": snapshot.summary_text,
        "recent_messages": snapshot.recent_messages,
        "total_messages": snapshot.total_messages,
        "plan_steps": list(session_state.plan_steps),
        "latest_output": session_state.latest_output,
        "message_count": len(session_state.messages),
        "tool_call_count": len(session_state.tool_calls),
        "tool_result_count": len(session_state.tool_results),
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_compact(namespace: Namespace) -> int:
    """
    输出真实会话的压缩上下文。
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))

    if session_state is None:
        payload = {
            "workspace_dir": str(workspace_dir),
            "selected_session": None,
            "session_count": len(_list_session_files(session_repo)),
            "session_files": _session_file_payloads(session_repo),
            "original_message_count": 0,
            "compressed_message_count": 0,
            "original_character_count": 0,
            "compressed_character_count": 0,
            "strategy": "empty",
            "summary_message": None,
            "messages": [],
        }
        return _dump_output(payload, _resolve_output_format(namespace))

    compressor = ContextCompressor()
    compression_result = compressor.compress_messages(session_state.messages)
    payload = {
        "workspace_dir": str(workspace_dir),
        "selected_session": session_state.model_dump(mode="json"),
        "session_count": len(_list_session_files(session_repo)),
        "session_files": _session_file_payloads(session_repo),
        "original_message_count": compression_result.original_message_count,
        "compressed_message_count": compression_result.compressed_message_count,
        "original_character_count": compression_result.original_character_count,
        "compressed_character_count": compression_result.compressed_character_count,
        "strategy": compression_result.strategy,
        "summary_message": compression_result.summary_message,
        "messages": compression_result.messages,
        "latest_output": session_state.latest_output,
        "plan_steps": list(session_state.plan_steps),
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_clear(namespace: Namespace) -> int:
    """
    清理真实会话文件。
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_id = getattr(namespace, "session_id", None)
    delete_result = _delete_session_files(session_repo, session_id)
    payload = {
        "workspace_dir": str(workspace_dir),
        "session_id": session_id,
        "storage_dir": str(session_repo.storage_dir),
        "storage_dir_exists": session_repo.storage_dir.exists(),
        **delete_result,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_mcp(namespace: Namespace) -> int:
    """
    杈撳嚭宸ヤ綔鍖哄彲瑙佺殑 MCP 璧勬簮姒傚喌銆?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    payload = _load_mcp_resources(workspace_dir)
    payload["workspace_dir"] = str(workspace_dir)
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_tools(namespace: Namespace) -> int:
    """
    杈撳嚭榛樿宸ュ叿鍒楄〃銆?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    tool_registry = create_default_tool_registry()
    payload = {
        "workspace_dir": str(workspace_dir),
        "tool_count": len(tool_registry.list_tools()),
        "tools": tool_registry.list_tools(),
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_summary(namespace: Namespace) -> int:
    """
    杈撳嚭浼氳瘽鎽樿銆?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))
    memory_injector = MemoryInjector()

    if session_state is None:
        payload = {
            "workspace_dir": str(workspace_dir),
            "selected_session": None,
            "summary_text": "",
            "recent_messages": [],
            "total_messages": 0,
        }
        return _dump_output(payload, _resolve_output_format(namespace))

    snapshot = memory_injector.build_snapshot(session_state.messages)
    payload = {
        "workspace_dir": str(workspace_dir),
        "selected_session": session_state.session_id,
        "summary_text": snapshot.summary_text,
        "recent_messages": snapshot.recent_messages,
        "total_messages": snapshot.total_messages,
        "latest_output": session_state.latest_output,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_doctor(namespace: Namespace) -> int:
    """
    杈撳嚭杩愯鐜妫€鏌ョ粨鏋溿€?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    tool_registry = create_default_tool_registry()
    payload = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "workspace_dir": str(workspace_dir),
        "graph_name": getattr(namespace, "graph_name", "main"),
        "output_format": _resolve_output_format(namespace),
        "command_count": len(CLI_COMMANDS),
        "tool_count": len(tool_registry.list_tools()),
        "has_deepseek_api_key": bool(os.getenv("DEEPSEEK_API_KEY") or getattr(namespace, "api_key", None)),
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_model(namespace: Namespace) -> int:
    """
    杈撳嚭妯″瀷閰嶇疆銆?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    payload = {
        "model": getattr(namespace, "model", None),
        "api_key_provided": bool(getattr(namespace, "api_key", None)),
        "base_url": getattr(namespace, "base_url", None),
        "reasoning_effort": getattr(namespace, "reasoning_effort", None),
        "session_id": getattr(namespace, "session_id", None),
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_permissions(namespace: Namespace) -> int:
    """
    杈撳嚭鏉冮檺涓婁笅鏂囥€?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    settings = AppSettings.model_validate(
        {
            "model": {
                "provider": "deepseek",
                "model_name": getattr(namespace, "model", None) or "deepseek-reasoner",
                "api_key": getattr(namespace, "api_key", None) or "",
                "base_url": getattr(namespace, "base_url", None),
                "reasoning_effort": getattr(namespace, "reasoning_effort", None),
            },
            "runtime": {
                "workspace_dir": workspace_dir,
                "session_id": getattr(namespace, "session_id", None),
                "max_turns": getattr(namespace, "max_turns", 32),
                "stream": getattr(namespace, "stream", True),
                "debug": getattr(namespace, "debug", False),
            },
            "cli": {
                "command": getattr(namespace, "command", "permissions"),
                "prompt": getattr(namespace, "prompt", None),
                "system_prompt": getattr(namespace, "system_prompt", None),
                "graph_name": getattr(namespace, "graph_name", "main"),
                "output_format": getattr(namespace, "output_format", "text"),
            },
        }
    )
    permission_context = create_permission_context(settings)
    payload = {
        "workspace_dir": str(workspace_dir),
        "allow_powershell": permission_context.allow_powershell,
        "additional_allowed_directories": [
            str(path) for path in permission_context.additional_allowed_directories
        ],
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_usage(namespace: Namespace) -> int:
    """
    杈撳嚭褰撳墠浼氳瘽鍜屽懡浠?宸ュ叿鐨勪娇鐢ㄦ鍐点€?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    tool_registry = create_default_tool_registry()
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))

    session_files: list[str] = []
    if session_repo.storage_dir.exists():
        session_files = [path.stem for path in sorted(session_repo.storage_dir.glob("*.json"))]

    payload = {
        "workspace_dir": str(workspace_dir),
        "session_id": getattr(namespace, "session_id", None),
        "turn_count": session_state.turn_count if session_state is not None else 0,
        "session_count": len(session_files),
        "command_count": len(CLI_COMMANDS),
        "tool_count": len(tool_registry.list_tools()),
        "message_count": len(session_state.messages) if session_state is not None else 0,
        "tool_call_count": len(session_state.tool_calls) if session_state is not None else 0,
        "plan_step_count": len(session_state.plan_steps) if session_state is not None else 0,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_stats(namespace: Namespace) -> int:
    """
    杈撳嚭宸ヤ綔鍖虹骇缁熻淇℃伅銆?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    runtime_root = _workspace_runtime_root(workspace_dir)
    swarm_root = runtime_root / "swarm"
    session_root = workspace_dir / SESSION_ROOT_DIRECTORY_NAME / "sessions"
    session_files = sum(1 for path in session_root.glob("*.json") if path.is_file()) if session_root.exists() else 0
    team_root = swarm_root / "teams"
    team_files = sum(1 for path in team_root.glob("*.json") if path.is_file()) if team_root.exists() else 0
    task_root = swarm_root / "tasks"
    task_files = (
        sum(1 for path in task_root.rglob("*.json") if path.is_file()) if task_root.exists() else 0
    )
    file_count = sum(1 for path in workspace_dir.rglob("*") if path.is_file())
    payload = {
        "workspace_dir": str(workspace_dir),
        "runtime_root": str(runtime_root),
        "session_files": session_files,
        "team_files": team_files,
        "task_files": task_files,
        "file_count": file_count,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_context(namespace: Namespace) -> int:
    """
    杈撳嚭褰撳墠杩愯涓婁笅鏂囧拰璁板繂姒傚喌銆?    :param namespace: CLI 鍛藉悕绌洪棿銆?    :return: 閫€鍑虹爜銆?    """

    workspace_dir = _resolve_workspace_dir(namespace)
    session_repo = SessionRepository(workspace_dir)
    session_state = _select_session_state(session_repo, getattr(namespace, "session_id", None))
    memory_injector = MemoryInjector()

    if session_state is None:
        payload = {
            "workspace_dir": str(workspace_dir),
            "graph_name": getattr(namespace, "graph_name", "main"),
            "system_prompt": getattr(namespace, "system_prompt", None),
            "session_id": None,
            "message_count": 0,
            "plan_step_count": 0,
            "memory": None,
            "memory_context": [],
        }
        return _dump_output(payload, _resolve_output_format(namespace))

    snapshot = memory_injector.build_snapshot(session_state.messages)
    payload = {
        "workspace_dir": str(workspace_dir),
        "graph_name": getattr(namespace, "graph_name", "main"),
        "system_prompt": getattr(namespace, "system_prompt", None),
        "session_id": session_state.session_id,
        "message_count": len(session_state.messages),
        "plan_step_count": len(session_state.plan_steps),
        "memory": asdict(snapshot),
        "memory_context": snapshot.to_context_messages(),
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_teams(namespace: Namespace) -> int:
    """
    输出工作区内团队列表与任务数量。
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    swarm_summary = _load_swarm_summary(workspace_dir)
    payload = {
        "workspace_dir": str(workspace_dir),
        "team_count": swarm_summary["team_count"],
        "task_count": swarm_summary["task_count"],
        "teams": swarm_summary["teams"],
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_messages(namespace: Namespace) -> int:
    """
    输出共享邮箱中的消息概况。
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    payload = _load_mailbox_messages(workspace_dir)
    payload["workspace_dir"] = str(workspace_dir)
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_agents(namespace: Namespace) -> int:
    """
    输出当前工作区可见的代理定义。
    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    registry = AgentRegistry()
    agents = [definition.model_dump(mode="json") for definition in registry.list()]
    payload = {
        "workspace_dir": str(workspace_dir),
        "agent_count": len(agents),
        "agents": agents,
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_skills(namespace: Namespace) -> int:
    """
    输出当前工作区与本机可见的 skills 概况。

    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    payload = _collect_skill_overview(workspace_dir)
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_plugin(namespace: Namespace) -> int:
    """
    输出当前 Python 版已实现的扩展面与注册概况。

    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    payload = _collect_plugin_surface(workspace_dir)
    return _dump_output(payload, _resolve_output_format(namespace))


def _render_reload_plugins(namespace: Namespace) -> int:
    """
    重新扫描当前工作区的技能、插件与命令视图。

    :param namespace: CLI 命名空间。
    :return: 退出码。
    """

    workspace_dir = _resolve_workspace_dir(namespace)
    skill_payload = _collect_skill_overview(workspace_dir)
    plugin_payload = _collect_plugin_surface(workspace_dir)
    command_names = create_default_registry().list_commands()
    tool_names = create_default_tool_registry().list_tools()
    payload = {
        "workspace_dir": str(workspace_dir.resolve()),
        "reloaded_at": datetime.now(timezone.utc).isoformat(),
        "command_count": len(command_names),
        "tool_count": len(tool_names),
        "skill_root_count": skill_payload["skill_root_count"],
        "unique_skill_count": skill_payload["unique_skill_count"],
        "mcp_resource_count": plugin_payload["mcp_resource_count"],
        "implemented_surface_count": plugin_payload["implemented_surface_count"],
    }
    return _dump_output(payload, _resolve_output_format(namespace))


def dispatch_lightweight_command(namespace: Namespace) -> int:
    """
    鍒嗗彂杞婚噺鍛戒护銆?
    :param namespace: argparse 瑙ｆ瀽缁撴灉銆?    :return: 鍛戒护閫€鍑虹爜銆?    :raises ValueError: 褰撳懡浠や笉鍙楁敮鎸佹椂瑙﹀彂銆?    """

    command_name = str(getattr(namespace, "command"))
    if command_name == "help":
        return _render_help(namespace)
    if command_name == "env":
        return _render_env(namespace)
    if command_name == "brief":
        return _render_brief(namespace)
    if command_name == "status":
        return _render_status(namespace)
    if command_name == "files":
        return _render_files(namespace)
    if command_name == "tasks":
        return _render_tasks(namespace)
    if command_name == "memory":
        return _render_memory(namespace)
    if command_name == "plan":
        return _render_plan(namespace)
    if command_name == "session":
        return _render_session(namespace)
    if command_name == "resume":
        return _render_resume(namespace)
    if command_name == "compact":
        return _render_compact(namespace)
    if command_name == "clear":
        return _render_clear(namespace)
    if command_name == "mcp":
        return _render_mcp(namespace)
    if command_name == "tools":
        return _render_tools(namespace)
    if command_name == "summary":
        return _render_summary(namespace)
    if command_name == "doctor":
        return _render_doctor(namespace)
    if command_name == "model":
        return _render_model(namespace)
    if command_name == "permissions":
        return _render_permissions(namespace)
    if command_name == "usage":
        return _render_usage(namespace)
    if command_name == "stats":
        return _render_stats(namespace)
    if command_name == "context":
        return _render_context(namespace)
    if command_name == "agents":
        return _render_agents(namespace)
    if command_name == "skills":
        return _render_skills(namespace)
    if command_name == "plugin":
        return _render_plugin(namespace)
    if command_name == "reload-plugins":
        return _render_reload_plugins(namespace)
    if command_name == "teams":
        return _render_teams(namespace)
    if command_name == "messages":
        return _render_messages(namespace)
    raise ValueError(f"不支持的轻量命令：{command_name}")


def dispatch_command(settings: AppSettings) -> int:
    """
    鎸夊懡浠ゅ悕鍒嗗彂杩愯鏃堕€昏緫銆?
    :param settings: 宸茶В鏋愮殑搴旂敤閰嶇疆銆?    :return: 鍛戒护閫€鍑虹爜銆?    :raises ValueError: 褰撳懡浠や笉鍙楁敮鎸佹椂瑙﹀彂銆?    """

    command_name = settings.cli.command
    if command_name in LIGHTWEIGHT_COMMANDS:
        return dispatch_lightweight_command(_namespace_from_settings(settings))

    if command_name == "config":
        print(json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    if command_name == "run":
        callback = _load_runtime_callable("run_once")
        return int(callback(settings))

    if command_name == "review":
        command_context = CommandContext(settings=settings)
        command_result = execute_command("review", command_context)
        return int(command_result.exit_code)

    if command_name == "chat":
        callback = _load_runtime_callable("run_interactive")
        return int(callback(settings))

    raise ValueError(f"不支持的命令：{command_name}")


def dispatch_command_from_namespace(namespace: Namespace) -> int:
    """
    鐩存帴鏍规嵁鍛藉悕绌洪棿鍒嗗彂杞婚噺鍛戒护銆?
    :param namespace: argparse 瑙ｆ瀽缁撴灉銆?    :return: 鍛戒护閫€鍑虹爜銆?    """

    return dispatch_lightweight_command(namespace)
