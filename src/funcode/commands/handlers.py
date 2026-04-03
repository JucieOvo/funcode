"""
妯″潡鍚嶇О锛歝ommands.handlers
鍔熻兘鎻忚堪锛?    鎻愪緵榛樿鍛戒护澶勭悊鍣紝瀹炵幇 run銆乺eview銆乧hat銆乧onfig 浠ュ強
    help銆乻tatus銆乫iles銆乼asks銆乵emory銆乸lan銆乻ession銆乵cp銆乼ools銆?    summary銆乨octor銆乵odel銆乸ermissions 绛夊懡浠ょ殑鐪熷疄涓氬姟鎺ョ嚎銆?涓昏缁勪欢锛?    - 鍚勭被 handle_*_command: 鍛戒护澶勭悊鍏ュ彛
    - COMMAND_SUMMARIES: 鍛戒护璇存槑琛?渚濊禆璇存槑锛?    - funcode.memory: 浼氳瘽璁板繂蹇収
    - funcode.mcp.registry: MCP 璧勬簮娉ㄥ唽
    - funcode.permissions.context: 鏉冮檺涓婁笅鏂?    - funcode.schemas.core: 浼氳瘽鐘舵€佹ā鍨?    - funcode.session.repository: 浼氳瘽浠撳簱
    - funcode.swarm.store: 鍥㈤槦涓庝换鍔℃寔涔呭寲
    - funcode.tools: 榛樿宸ュ叿娉ㄥ唽琛?浣滆€咃細JucieOvo
鍒涘缓鏃ユ湡锛?026-04-01
淇敼璁板綍锛?    - 2026-04-01 JucieOvo: 鎵╁睍 commands 鐩綍鍛戒护鎺ョ嚎
"""

from __future__ import annotations

from dataclasses import asdict
import importlib
import json
import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from funcode.commands.models import CommandContext, CommandResult
from funcode.agents.lifecycle import AgentLifecycleService
from funcode.agents.registry import AgentRegistry
from funcode.compact.compressor import compress_messages
from funcode.memory import build_memory_snapshot
from funcode.constants.env import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_BASE_URL_ENV,
    DEFAULT_CWD_ENV,
    DEFAULT_MODEL_ENV,
    REASONING_EFFORT_ENV,
    SESSION_ID_ENV,
)
from funcode.mcp.registry import McpRegistry, McpResource
from funcode.permissions.context import create_permission_context
from funcode.schemas.core import SessionState
from funcode.runtime.swarm_lifecycle import SwarmLifecycleService
from funcode.swarm.mailbox import FileMailbox
from funcode.swarm.models import SwarmTaskUpdate
from funcode.session.repository import SESSION_ROOT_DIRECTORY_NAME, SessionRepository
from funcode.swarm.store import SwarmStore
from funcode.tools import create_default_tool_registry
from funcode.tools.context import ToolExecutionContext

COMMAND_SUMMARIES: dict[str, str] = {
    "run": "鎵ц涓€杞畬鏁村浘娴佺▼銆?",
    "review": "浠ュ鏌ヨ瑙掓墽琛屽師濮嬩换鍔°€?",
    "chat": "杩涘叆鍩虹浜や簰寮忎細璇濄€?",
    "config": "杈撳嚭褰撳墠瑙ｆ瀽鍚庣殑閰嶇疆銆?",
    "help": "鍒楀嚭褰撳墠宸叉帴鍏ュ懡浠ゃ€?",
    "status": "鏌ョ湅杩愯鐜銆佸浘涓庡伐鍏风姸鎬併€?",
    "files": "鍒楀嚭宸ヤ綔鍖烘枃浠躲€?",
    "agents": "鍒楀嚭褰撳墠鍙浠ｇ悊瀹氫箟銆?",
    "skills": "鎵弿褰撳墠宸ヤ綔鍖洪€忔槑鍙 skills 鍏ュ彛鍙婁笁鏂瑰湴鍧€銆?",
    "tasks": "鍒楀嚭褰撳墠宸ヤ綔鍖哄洟闃熶笌浠诲姟姒傚喌銆?",
    "memory": "鏌ョ湅褰撳墠浼氳瘽璁板繂蹇収銆?",
    "plan": "鏌ョ湅鎴栫敓鎴愯鍒掓楠ら瑙堛€?",
    "session": "鏌ョ湅褰撳墠浼氳瘽浠撳簱姒傚喌銆?",
    "mcp": "鏌ョ湅宸叉敞鍐?MCP 璧勬簮銆?",
    "tools": "鏌ョ湅榛樿宸ュ叿鍒楄〃銆?",
    "teams": "鏌ョ湅宸ヤ綔鍖哄唴鍥㈤槦鍒楄〃銆?",
    "messages": "鏌ョ湅鍏变韩閭娑堟伅姒傚喌銆?",
    "env": "鏌ョ湅褰撳墠杩愯鎵€渚濊禆鐨勫叧閿幆澧冨彉閲忋€?",
    "brief": "浣跨敤鐜版湁 brief 宸ュ叿鐢熸垚褰撳墠鐜鎽樿銆?",
    "summary": "鍩轰簬褰撳墠浼氳瘽涓庤蹇嗘敞鍏ョ敓鎴愭憳瑕併€?",
    "doctor": "杈撳嚭杩愯鐜涓庡仴搴蜂俊鎭€?",
    "model": "鏌ョ湅褰撳墠妯″瀷閰嶇疆銆?",
    "plugin": "杈撳嚭 Python 版鎵╁睍闈笌鍙敤鎺ュ彛鐪熷疄姒傝銆?",
    "worktree": "真实创建或移除 Git worktree。",
    "cron": "真实创建 Windows 计划任务。",
    "repl": "通过真实交互式子进程执行 REPL。",
    "reload-plugins": "重新扫描当前工作区的技能、插件与命令视图。",
    "permissions": "鏌ョ湅褰撳墠鏉冮檺涓婁笅鏂囥€?",
}

COMMAND_SUMMARIES.update(
    {
        "usage": "鏌ョ湅褰撳墠浼氳瘽鍜屽懡浠ゆ秷鑰椾俊鎭€?",
        "stats": "鏌ョ湅宸ヤ綔鍖虹骇缁熻姒傚喌銆?",
        "context": "鏌ョ湅褰撳墠杩愯涓婁笅鏂囦笌璁板繂姒傚喌銆?",
        "resume": "鎭㈠骞舵樉绀哄厛鍓嶆渶杩戜細璇濄€?",
        "compact": "鍩轰簬褰撳墠浼氳瘽鐢熸垚鐪熷疄鍘嬬缉鎽樿銆?",
        "clear": "娓呴櫎褰撳墠宸ヤ綔鍖虹殑浼氳瘽瀛樺偍銆?",
    }
)


def _render_json(payload: Any) -> str:
    """
    灏嗙粨鏋勫寲鏁版嵁娓叉煋涓?JSON 鏂囨湰銆?    :param payload: 寰呮覆鏌撳唴瀹广€?    :return: JSON 鏂囨湰銆?    """

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _get_registered_command_names() -> list[str]:
    """
    浠庨粯璁ゆ敞鍐岃〃璇诲彇褰撳墠宸叉敞鍐屽懡浠ゃ€?    :return: 鍛戒护鍚嶅垪琛ㄣ€?    """

    service_module = importlib.import_module("funcode.commands.service")
    registry = service_module.create_default_registry()
    return registry.list_commands()


def _workspace_runtime_root(workspace_dir: Path) -> Path:
    """
    璁＄畻宸ヤ綔鍖轰笅鐨勮繍琛屾椂鏍圭洰褰曘€?    :param workspace_dir: 宸ヤ綔鍖虹洰褰曘€?    :return: 杩愯鏃舵牴鐩綍銆?    """

    return workspace_dir.resolve() / SESSION_ROOT_DIRECTORY_NAME


def _build_session_repository(context: CommandContext) -> SessionRepository:
    """
    鏋勫缓褰撳墠宸ヤ綔鍖哄搴旂殑浼氳瘽浠撳簱銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 浼氳瘽浠撳簱瀵硅薄銆?    """

    return SessionRepository(context.settings.runtime.workspace_dir)


def _load_session_state_if_available(context: CommandContext) -> SessionState | None:
    """
    鍦ㄥ瓨鍦?session_id 鏃跺姞杞藉綋鍓嶄細璇濈姸鎬併€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 浼氳瘽鐘舵€佹垨 None銆?    """

    session_id = context.settings.runtime.session_id
    if not session_id:
        return None

    repository = _build_session_repository(context)
    if not repository.exists(session_id):
        return None
    return repository.load(session_id)


def _list_visible_sessions(context: CommandContext) -> list[SessionState]:
    """
    鍒楀嚭宸ヤ綔鍖轰腑鍙鐨勪細璇濇枃浠躲€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 浼氳瘽鐘舵€佸垪琛ㄣ€?    """

    repository = _build_session_repository(context)
    storage_dir = repository.storage_dir
    if not storage_dir.exists():
        return []

    sessions: list[SessionState] = []
    for session_file in sorted(storage_dir.glob("*.json")):
        sessions.append(SessionState.model_validate_json(session_file.read_text(encoding="utf-8")))
    return sessions


def _select_latest_session(context: CommandContext) -> SessionState | None:
    """
    从当前工作区的真实会话文件中挑选最近一次更新的会话。

    选择规则：
        1. 仅从可见会话文件中选择，不伪造任何结果。
        2. 按 updated_at、created_at、session_id 倒序选择最近会话。

    :param context: 命令上下文。
    :return: 最近会话或 None。
    """

    visible_sessions = _list_visible_sessions(context)
    if not visible_sessions:
        return None

    return sorted(
        visible_sessions,
        key=lambda session_state: (
            session_state.updated_at,
            session_state.created_at,
            session_state.session_id,
        ),
        reverse=True,
    )[0]


def _select_current_or_latest_session(context: CommandContext) -> SessionState | None:
    """
    优先返回当前 session_id 对应的会话；如果当前会话不存在，则返回最近会话。

    :param context: 命令上下文。
    :return: 当前会话或最近会话。
    """

    current_session = _load_session_state_if_available(context)
    if current_session is not None:
        return current_session
    return _select_latest_session(context)


def _build_session_overview_payload(
    session_state: SessionState,
    *,
    current_session_id: str | None,
) -> dict[str, Any]:
    """
    将会话状态转换为可直接输出的概况载荷。

    :param session_state: 真实会话状态。
    :param current_session_id: 当前上下文中的会话标识。
    :return: 会话概况字典。
    """

    memory_snapshot = build_memory_snapshot(session_state.messages)
    session_payload = {
        "session_id": session_state.session_id,
        "graph_name": session_state.graph_name,
        "output_format": session_state.output_format,
        "system_prompt": session_state.system_prompt,
        "turn_count": session_state.turn_count,
        "message_count": len(session_state.messages),
        "tool_call_count": len(session_state.tool_calls),
        "tool_result_count": len(session_state.tool_results),
        "plan_step_count": len(session_state.plan_steps),
        "latest_output": session_state.latest_output,
        "created_at": session_state.created_at,
        "updated_at": session_state.updated_at,
        "is_current": session_state.session_id == current_session_id,
    }
    memory_payload = asdict(memory_snapshot)
    return {
        "session": session_payload,
        "memory": memory_payload,
        "selected_as_current_view": session_state.session_id,
    }


def _build_session_overview_lines(payload: dict[str, Any]) -> list[str]:
    """
    将会话概况整理为便于终端阅读的文本。

    :param payload: `_build_session_overview_payload` 生成的概况字典。
    :return: 文本行列表。
    """

    session_payload = payload["session"]
    memory_payload = payload["memory"]
    lines = [
        f"当前会话视图: {session_payload['session_id']}",
        (
            f"graph={session_payload['graph_name']} | "
            f"format={session_payload['output_format']} | "
            f"turns={session_payload['turn_count']} | "
            f"messages={session_payload['message_count']} | "
            f"tools={session_payload['tool_call_count']} | "
            f"plans={session_payload['plan_step_count']}"
        ),
        f"更新时间: {session_payload['updated_at']} | 创建时间: {session_payload['created_at']}",
    ]
    if session_payload.get("latest_output"):
        lines.append(f"最近输出: {session_payload['latest_output']}")
    summary_text = (memory_payload.get("summary_text") or "").strip()
    if summary_text:
        lines.append("记忆摘要:")
        lines.extend(summary_text.splitlines())
    else:
        lines.append("记忆摘要: 无可用摘要文本。")
    lines.append(
        f"最近消息数: {len(memory_payload.get('recent_messages', []))} / {memory_payload.get('total_messages', 0)}"
    )
    return lines


def _ensure_path_within_workspace(candidate_path: Path, workspace_dir: Path) -> None:
    """
    校验待删除路径必须位于当前工作区内，避免误删工作区外文件。

    :param candidate_path: 待校验的真实路径。
    :param workspace_dir: 当前工作区路径。
    :raises ValueError: 当路径不在工作区内时抛出。
    """

    resolved_workspace = workspace_dir.resolve()
    resolved_candidate = candidate_path.resolve()
    try:
        resolved_candidate.relative_to(resolved_workspace)
    except ValueError as exc:
        raise ValueError(
            f"清理目标不在当前工作区内，已拒绝执行：{resolved_candidate}"
        ) from exc


def _clear_session_storage(context: CommandContext) -> dict[str, Any]:
    """
    直接清理当前工作区的会话文件或会话目录。

    清理策略：
        1. 如果当前会话文件真实存在，则优先删除当前 session 文件。
        2. 如果当前会话不存在，则删除整个 sessions 存储目录。
        3. 若两者都不存在，直接报错，不伪装成功。

    :param context: 命令上下文。
    :return: 删除结果明细。
    :raises FileNotFoundError: 当没有任何可清理目标时抛出。
    """

    repository = _build_session_repository(context)
    workspace_dir = context.settings.runtime.workspace_dir.resolve()
    current_session_id = context.settings.runtime.session_id

    if current_session_id and repository.exists(current_session_id):
        session_file_path = repository.get_session_file_path(current_session_id)
        _ensure_path_within_workspace(session_file_path, workspace_dir)
        session_file_path.unlink()
        return {
            "scope": "current_session_file",
            "deleted_count": 1,
            "deleted_paths": [str(session_file_path)],
            "workspace_dir": str(workspace_dir),
        }

    storage_dir = repository.storage_dir
    if storage_dir.exists():
        _ensure_path_within_workspace(storage_dir, workspace_dir)
        deleted_paths = [str(path) for path in storage_dir.glob("*.json") if path.is_file()]
        shutil.rmtree(storage_dir)
        return {
            "scope": "session_storage_directory",
            "deleted_count": len(deleted_paths),
            "deleted_paths": deleted_paths,
            "workspace_dir": str(workspace_dir),
        }

    raise FileNotFoundError(
        f"当前工作区没有可清理的会话文件或会话目录：{storage_dir}"
    )


def _count_files(root_dir: Path, pattern: str = "*.json", recursive: bool = False) -> int:
    """
    统计指定目录下符合模式的真实文件数量。
    :param root_dir: 目录路径。
    :param pattern: 文件匹配模式。
    :return: 文件数量。
    """

    if not root_dir.exists():
        return 0
    iterator = root_dir.rglob(pattern) if recursive else root_dir.glob(pattern)
    return sum(1 for path in iterator if path.is_file())


def _load_mcp_registry(context: CommandContext) -> McpRegistry:
    """
    鏋勫缓褰撳墠宸ヤ綔鍖虹殑 MCP 娉ㄥ唽琛ㄣ€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: MCP 娉ㄥ唽琛ㄥ璞°€?    """

    registry = McpRegistry()
    readme_path = context.settings.runtime.workspace_dir.resolve() / "README.md"
    if readme_path.exists():
        registry.register(
            McpResource(
                uri="workspace://README.md",
                title="宸ヤ綔鍖?README",
                path=readme_path,
                description="宸ヤ綔鍖烘牴鐩綍 README 鏂囦欢銆?",
            )
        )
    return registry


def _build_swarm_store(context: CommandContext) -> SwarmStore:
    """
    构建当前工作区对应的持久化 swarm 存储。
    :param context: 命令上下文。
    :return: swarm 存储对象。
    """

    runtime_root = _workspace_runtime_root(context.settings.runtime.workspace_dir)
    return SwarmStore(runtime_root / "swarm")


def _build_shared_mailbox(context: CommandContext) -> FileMailbox:
    """
    构建当前工作区对应的共享邮箱。
    :param context: 命令上下文。
    :return: 共享邮箱对象。
    """

    runtime_root = _workspace_runtime_root(context.settings.runtime.workspace_dir)
    return FileMailbox(runtime_root / "swarm" / "mailbox.jsonl")


def _build_swarm_lifecycle_service(context: CommandContext) -> SwarmLifecycleService:
    """
    为命令层构建统一的 swarm 生命周期服务。

    :param context: 命令上下文。
    :return: 生命周期服务对象。
    """

    return SwarmLifecycleService(context.settings.runtime.workspace_dir)


def _command_extra(context: CommandContext, key: str, default: Any | None = None) -> Any | None:
    """
    从命令上下文中读取扩展参数。

    :param context: 命令上下文。
    :param key: 参数名称。
    :param default: 默认值。
    :return: 参数值或默认值。
    """

    extras = context.extras if isinstance(context.extras, dict) else {}
    return extras.get(key, default)


def _command_action(context: CommandContext) -> str:
    """
    读取命令动作参数。

    :param context: 命令上下文。
    :return: 标准化后的动作名称。
    """

    action_value = _command_extra(context, "action", "list")
    return str(action_value).strip().lower()


def _build_brief_tool_context(context: CommandContext) -> ToolExecutionContext:
    """
    为 brief 工具构建真实执行上下文。

    :param context: 命令上下文。
    :return: 工具执行上下文。
    """

    session_state = _load_session_state_if_available(context)
    plan_steps = list(session_state.plan_steps) if session_state is not None else []
    return ToolExecutionContext(
        settings=context.settings,
        permission_context=create_permission_context(context.settings),
        mcp_registry=_load_mcp_registry(context),
        plan_steps=plan_steps,
    )


def _package_root() -> Path:
    """
    定位当前 Python 版实现包的根目录。

    :return: funcode 包根目录。
    """

    return Path(__file__).resolve().parents[1]


def _candidate_skill_roots(workspace_dir: Path) -> list[Path]:
    """
    生成当前工作区与本机可见的 skills 目录候选列表。

    :param workspace_dir: 当前工作区根目录。
    :return: 候选 skills 根目录列表。
    """

    candidate_roots = [
        workspace_dir / "skills",
        workspace_dir / "src" / "skills",
        workspace_dir / ".codex" / "skills",
        workspace_dir / ".funcode" / "skills",
    ]
    codex_home = os.environ.get("CODEX_HOME")
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


def _collect_skill_overview(context: CommandContext) -> dict[str, Any]:
    """
    扫描当前工作区与本机可见 skills 目录，汇总真实技能概况。

    这里只读取真实目录，不推断不存在的技能，不返回任何假数据。

    :param context: 命令上下文。
    :return: 可直接输出的 skills 概况载荷。
    """

    workspace_dir = context.settings.runtime.workspace_dir.resolve()
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


def _collect_plugin_surface(context: CommandContext) -> dict[str, Any]:
    """
    汇总当前 Python 版已实现的扩展面、命令/工具/MCP 规模与预留接口。

    这个命令只输出真实存在的模块、注册表与资源数量，不拼装示意数据。

    :param context: 命令上下文。
    :return: 插件/扩展面概况载荷。
    """

    package_root = _package_root()
    command_names = _get_registered_command_names()
    tool_names = create_default_tool_registry().list_tools()
    mcp_registry = _load_mcp_registry(context)
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
        {
            "interface": "funcode.runtime.application.run_once",
            "purpose": "单次执行入口，承载批处理类执行扩展。",
        },
        {
            "interface": "funcode.runtime.application.run_interactive",
            "purpose": "交互式执行入口，承载会话式扩展。",
        },
        {
            "interface": "funcode.agents.registry.AgentRegistry",
            "purpose": "代理发现入口，承载代理层扩展。",
        },
        {
            "interface": "funcode.session.repository.SessionRepository",
            "purpose": "会话持久化入口，承载会话数据扩展。",
        },
        {
            "interface": "funcode.swarm.store.SwarmStore",
            "purpose": "团队与任务持久化入口，承载协作层扩展。",
        },
    ]

    return {
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "package_root": str(package_root),
        "command_count": len(command_names),
        "tool_count": len(tool_names),
        "mcp_resource_count": len(mcp_resources),
        "implemented_surface_count": len(implemented_surfaces),
        "implemented_surfaces": implemented_surfaces,
        "reserved_interfaces": reserved_interfaces,
        "mcp_resources": mcp_resources,
    }


def _load_runtime_callable(attribute_name: str) -> Callable[..., Any]:
    """
    延迟加载 runtime.application 中的目标函数。

    :param attribute_name: 目标函数名。
    :return: 可调用对象。
    :raises ImportError: 当运行时模块尚未实现或目标函数不存在时触发。
    :raises TypeError: 当目标属性不是可调用对象时触发。
    """

    try:
        runtime_module = importlib.import_module("funcode.runtime.application")
    except ModuleNotFoundError as exc:
        raise ImportError(
            "运行时模块 funcode.runtime.application 尚未完成，无法执行命令。"
        ) from exc

    try:
        callback = getattr(runtime_module, attribute_name)
    except AttributeError as exc:
        raise ImportError(f"运行时模块缺少入口函数：{attribute_name}") from exc
    if not callable(callback):
        raise TypeError(f"运行时入口不是可调用对象：{attribute_name}")
    return callback


def _build_review_prompt(original_prompt: str | None) -> str:
    """
    构建审查模式提示词前缀。

    :param original_prompt: 原始用户输入。
    :return: 审查模式提示词。
    """

    review_prefix = (
        "你现在执行的是代码审查任务。\n"
        "请重点关注 bug、risk、regression、tests 四个方面。\n"
        "优先指出可验证的问题、行为变化风险和缺失测试。\n"
        "如果发现问题，请直接给出具体位置、原因和建议，不要泛泛而谈。"
    )
    stripped_prompt = (original_prompt or "").strip()
    if not stripped_prompt:
        return review_prefix
    return f"{review_prefix}\n\n待审查内容：\n{stripped_prompt}"


def handle_run_command(context: CommandContext) -> CommandResult:
    """
    鎵ц鍗曟瀹屾暣鍥炬祦绋嬨€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    callback = _load_runtime_callable("run_once")
    exit_code = int(callback(context.settings))
    return CommandResult(exit_code=exit_code)


def handle_review_command(context: CommandContext) -> CommandResult:
    """
    浠ュ鏌ユā寮忔墽琛屽師濮嬩换鍔°€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    review_prompt = _build_review_prompt(context.settings.cli.prompt)
    review_settings = context.settings.model_copy(
        update={
            "cli": context.settings.cli.model_copy(
                update={
                    "command": "review",
                    "prompt": review_prompt,
                }
            )
        }
    )
    callback = _load_runtime_callable("run_once")
    exit_code = int(callback(review_settings))
    return CommandResult(
        exit_code=exit_code,
        payload={
            "mode": "review",
            "prompt": review_prompt,
        },
    )


def handle_chat_command(context: CommandContext) -> CommandResult:
    """
    鎵ц浜や簰寮忎細璇濄€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    callback = _load_runtime_callable("run_interactive")
    exit_code = int(callback(context.settings))
    return CommandResult(exit_code=exit_code)


def handle_config_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠閰嶇疆銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    payload = context.settings.model_dump(mode="json")
    return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)


def handle_help_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠宸叉敞鍐屽懡浠ゃ€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    command_names = _get_registered_command_names()
    lines = ["鍙敤鍛戒护:"]
    for command_name in command_names:
        summary = COMMAND_SUMMARIES.get(command_name, "未提供说明。")
        lines.append(f"- {command_name}: {summary}")
    return CommandResult(
        exit_code=0,
        output="\n".join(lines),
        payload={"commands": command_names},
    )


def handle_usage_command(context: CommandContext) -> CommandResult:
    """
    输出当前会话与命令/工具的使用概况。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    session_state = _load_session_state_if_available(context)
    command_names = _get_registered_command_names()
    tool_names = create_default_tool_registry().list_tools()
    sessions = _list_visible_sessions(context)
    payload = {
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "session_id": context.settings.runtime.session_id,
        "turn_count": session_state.turn_count if session_state is not None else 0,
        "session_count": len(sessions),
        "command_count": len(command_names),
        "tool_count": len(tool_names),
        "message_count": len(session_state.messages) if session_state is not None else 0,
        "tool_call_count": len(session_state.tool_calls) if session_state is not None else 0,
        "plan_step_count": len(session_state.plan_steps) if session_state is not None else 0,
    }
    output = "\n".join(
        [
            f"workspace: {payload['workspace_dir']}",
            f"session_id: {payload['session_id']}",
            f"turn_count: {payload['turn_count']}",
            f"session_count: {payload['session_count']}",
            f"command_count: {payload['command_count']}",
            f"tool_count: {payload['tool_count']}",
            f"message_count: {payload['message_count']}",
            f"tool_call_count: {payload['tool_call_count']}",
            f"plan_step_count: {payload['plan_step_count']}",
        ]
    )
    return CommandResult(exit_code=0, output=output, payload=payload)


def handle_env_command(context: CommandContext) -> CommandResult:
    """
    输出当前运行所依赖的关键环境变量概况。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    workspace_dir = str(context.settings.runtime.workspace_dir.resolve())
    cwd_value = os.getenv(DEFAULT_CWD_ENV)
    pythonpath_value = os.getenv("PYTHONPATH")
    path_value = os.getenv("PATH", "")
    path_entries = [entry for entry in path_value.split(os.pathsep) if entry]
    payload = {
        "workspace_dir": workspace_dir,
        "cwd_env": cwd_value,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "deepseek_api_key_present": bool(os.getenv(DEEPSEEK_API_KEY_ENV)),
        "deepseek_base_url": os.getenv(DEEPSEEK_BASE_URL_ENV),
        "default_model_env": os.getenv(DEFAULT_MODEL_ENV),
        "reasoning_effort_env": os.getenv(REASONING_EFFORT_ENV),
        "session_id_env": os.getenv(SESSION_ID_ENV),
        "pythonpath": pythonpath_value,
        "path_entry_count": len(path_entries),
        "path_preview": path_entries[:8],
        "userprofile": os.getenv("USERPROFILE"),
        "home": os.getenv("HOME"),
    }
    return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)


def handle_brief_command(context: CommandContext) -> CommandResult:
    """
    复用现有 brief 工具生成当前工作区与会话摘要。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    tool_context = _build_brief_tool_context(context)
    tool_result = create_default_tool_registry().execute("brief", {}, tool_context)
    payload = {
        "tool_name": tool_result.tool_name,
        "metadata": dict(tool_result.metadata),
    }
    return CommandResult(exit_code=0, output=tool_result.content, payload=payload)


def handle_worktree_command(context: CommandContext) -> CommandResult:
    """
    使用真实工具创建或移除 Git worktree。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    tool_context = _build_brief_tool_context(context)
    action = str(context.extras.get("action", "enter")).strip().lower()
    tool_arguments = dict(context.extras.get("arguments") or {})
    if not tool_arguments:
        tool_arguments = {key: value for key, value in context.extras.items() if key != "action"}
    tool_name = "exit_worktree" if action in {"exit", "remove", "delete"} else "enter_worktree"
    tool_result = create_default_tool_registry().execute(tool_name, tool_arguments, tool_context)
    payload = {
        "tool_name": tool_result.tool_name,
        "metadata": dict(tool_result.metadata),
    }
    return CommandResult(exit_code=0, output=tool_result.content, payload=payload)


def handle_cron_command(context: CommandContext) -> CommandResult:
    """
    使用真实工具创建 Windows 计划任务。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    tool_context = _build_brief_tool_context(context)
    tool_arguments = dict(context.extras.get("arguments") or {})
    if not tool_arguments:
        tool_arguments = dict(context.extras)
    tool_result = create_default_tool_registry().execute("schedule_cron", tool_arguments, tool_context)
    payload = {
        "tool_name": tool_result.tool_name,
        "metadata": dict(tool_result.metadata),
    }
    return CommandResult(exit_code=0, output=tool_result.content, payload=payload)


def handle_repl_command(context: CommandContext) -> CommandResult:
    """
    使用真实子进程执行脚本化 REPL。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    tool_context = _build_brief_tool_context(context)
    tool_arguments = dict(context.extras.get("arguments") or {})
    if not tool_arguments:
        tool_arguments = dict(context.extras)
    tool_result = create_default_tool_registry().execute("repl", tool_arguments, tool_context)
    payload = {
        "tool_name": tool_result.tool_name,
        "metadata": dict(tool_result.metadata),
    }
    return CommandResult(exit_code=0, output=tool_result.content, payload=payload)


def handle_stats_command(context: CommandContext) -> CommandResult:
    """
    输出工作区级文件统计。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    workspace_dir = context.settings.runtime.workspace_dir.resolve()
    runtime_root = _workspace_runtime_root(workspace_dir)
    swarm_root = runtime_root / "swarm"
    session_files = _count_files(workspace_dir / SESSION_ROOT_DIRECTORY_NAME / "sessions")
    team_files = _count_files(swarm_root / "teams")
    task_files = _count_files(swarm_root / "tasks", "*.json", recursive=True)
    payload = {
        "workspace_dir": str(workspace_dir),
        "runtime_root": str(runtime_root),
        "session_files": session_files,
        "team_files": team_files,
        "task_files": task_files,
        "file_count": _count_files(workspace_dir, "*", recursive=True),
    }
    output = "\n".join(
        [
            f"workspace: {payload['workspace_dir']}",
            f"session_files: {session_files}",
            f"team_files: {team_files}",
            f"task_files: {task_files}",
            f"file_count: {payload['file_count']}",
        ]
    )
    return CommandResult(exit_code=0, output=output, payload=payload)


def handle_context_command(context: CommandContext) -> CommandResult:
    """
    输出当前运行上下文与记忆概况。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    session_state = _load_session_state_if_available(context)
    memory_payload: dict[str, Any] | None = None
    memory_context: list[dict[str, Any]] = []
    if session_state is not None:
        snapshot = build_memory_snapshot(session_state.messages)
        memory_payload = asdict(snapshot)
        memory_context = snapshot.to_context_messages()

    payload = {
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "graph_name": context.settings.cli.graph_name,
        "system_prompt": context.settings.cli.system_prompt,
        "memory": memory_payload,
        "memory_context": memory_context,
        "session_id": session_state.session_id if session_state is not None else None,
        "message_count": len(session_state.messages) if session_state is not None else 0,
        "plan_step_count": len(session_state.plan_steps) if session_state is not None else 0,
    }
    return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)


def handle_status_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭杩愯鐜銆佸浘涓庡伐鍏风姸鎬併€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    tool_registry = create_default_tool_registry()
    command_names = _get_registered_command_names()
    tool_names = tool_registry.list_tools()
    payload = {
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "model_name": context.settings.model.model_name,
        "provider": context.settings.model.provider,
        "base_url": context.settings.model.base_url,
        "reasoning_effort": context.settings.model.reasoning_effort,
        "graph_name": context.settings.cli.graph_name,
        "output_format": context.settings.cli.output_format,
        "registered_command_count": len(command_names),
        "registered_tool_count": len(tool_names),
        "commands": command_names,
        "tools": tool_names,
        "session_id": context.settings.runtime.session_id,
    }
    return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)


def handle_summary_command(context: CommandContext) -> CommandResult:
    """
    鏍规嵁褰撳墠浼氳瘽娑堟伅涓庤蹇嗘敞鍏ョ粨鏋滅敓鎴愭憳瑕併€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    session_state = _load_session_state_if_available(context)
    if session_state is None:
        output = "当前没有可加载的会话，无法生成摘要。"
        return CommandResult(exit_code=0, output=output, payload={"summary": None})

    snapshot = build_memory_snapshot(session_state.messages)
    payload = {
        "session_id": session_state.session_id,
        "message_count": len(session_state.messages),
        "summary_text": snapshot.summary_text,
        "recent_message_count": len(snapshot.recent_messages),
        "recent_messages": snapshot.recent_messages,
        "memory_context": snapshot.to_context_messages(),
        "latest_output": session_state.latest_output,
    }
    return CommandResult(exit_code=0, output=_render_json(payload), payload={"summary": payload})


def handle_doctor_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭杩愯鐜涓庡仴搴蜂俊鎭€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    command_names = _get_registered_command_names()
    tool_names = create_default_tool_registry().list_tools()
    payload = {
        "python_version": platform.python_version(),
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "registered_command_count": len(command_names),
        "registered_tool_count": len(tool_names),
        "graph_name": context.settings.cli.graph_name,
        "has_deepseek_api_key": bool(
            context.settings.model.api_key or os.getenv("DEEPSEEK_API_KEY", "")
        ),
        "commands": command_names,
        "tools": tool_names,
    }
    return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)


def handle_model_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠妯″瀷閰嶇疆銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    payload = {
        "provider": context.settings.model.provider,
        "model_name": context.settings.model.model_name,
        "base_url": context.settings.model.base_url,
        "reasoning_effort": context.settings.model.reasoning_effort,
        "has_deepseek_api_key": bool(
            context.settings.model.api_key or os.getenv("DEEPSEEK_API_KEY", "")
        ),
    }
    return CommandResult(exit_code=0, output=_render_json(payload), payload={"model": payload})


def handle_permissions_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠鏉冮檺涓婁笅鏂囥€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    permission_context = create_permission_context(context.settings)
    payload = permission_context.model_dump(mode="json")
    payload["workspace_dir"] = str(context.settings.runtime.workspace_dir.resolve())
    return CommandResult(
        exit_code=0,
        output=_render_json(payload),
        payload={"permissions": payload},
    )


def handle_files_command(context: CommandContext) -> CommandResult:
    """
    鍒楀嚭宸ヤ綔鍖烘牴鐩綍鏂囦欢銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    workspace_dir = context.settings.runtime.workspace_dir.resolve()
    file_entries = [
        path.name
        for path in sorted(workspace_dir.iterdir(), key=lambda item: item.name.lower())
        if path.is_file()
    ]
    return CommandResult(
        exit_code=0,
        output="\n".join(file_entries),
        payload={"workspace_dir": str(workspace_dir), "files": file_entries},
    )


def handle_tasks_command(context: CommandContext) -> CommandResult:
    """
    鍒楀嚭褰撳墠宸ヤ綔鍖哄洟闃熶笌浠诲姟姒傚喌銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    runtime_root = _workspace_runtime_root(context.settings.runtime.workspace_dir)
    swarm_root = runtime_root / "swarm"
    store = SwarmStore(swarm_root)
    session_state = _load_session_state_if_available(context)

    payload_teams: list[dict[str, Any]] = []
    lines: list[str] = []
    for team in store.list_teams():
        tasks = store.list_tasks(team.team_name)
        payload_teams.append(
            {
                "team_name": team.team_name,
                "description": team.description,
                "workspace_dir": team.workspace_dir,
                "task_count": len(tasks),
                "tasks": [task.model_dump(mode="json") for task in tasks],
            }
        )
        lines.append(f"[{team.team_name}] {team.description} ({len(tasks)} tasks)")
        for task in tasks:
            lines.append(f"- {task.task_id} | {task.status} | {task.subject}")

    payload_session: dict[str, Any] | None = None
    if session_state is not None:
        payload_session = {
            "session_id": session_state.session_id,
            "graph_name": session_state.graph_name,
            "output_format": session_state.output_format,
            "turn_count": session_state.turn_count,
            "message_count": len(session_state.messages),
            "plan_steps": list(session_state.plan_steps),
            "latest_output": session_state.latest_output,
        }
        lines.append(
            f"[session] {session_state.session_id} | turns={session_state.turn_count} | "
            f"messages={len(session_state.messages)} | plans={len(session_state.plan_steps)}"
        )

    if not lines:
        lines.append("当前工作区没有已保存的团队或任务。")

    return CommandResult(
        exit_code=0,
        output="\n".join(lines),
        payload={"session": payload_session, "teams": payload_teams},
    )


def handle_memory_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠浼氳瘽鐨勮蹇嗗揩鐓с€?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    session_state = _load_session_state_if_available(context)
    if session_state is None:
        output = "当前没有可加载的会话，无法生成记忆快照。"
        return CommandResult(exit_code=0, output=output, payload={"memory": None})

    snapshot = build_memory_snapshot(session_state.messages)
    payload = asdict(snapshot)
    return CommandResult(exit_code=0, output=_render_json(payload), payload={"memory": payload})


def handle_plan_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠璁″垝姝ラ棰勮銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    action = _command_action(context)
    tool_context = _build_brief_tool_context(context)
    tool_arguments = dict(context.extras.get("arguments") or {})
    if not tool_arguments:
        tool_arguments = {key: value for key, value in context.extras.items() if key not in {"action", "arguments"}}

    if action in {"enter", "start", "on"}:
        from funcode.tools.advanced import EnterPlanModeTool

        tool_result = EnterPlanModeTool().execute(tool_arguments, tool_context)
        payload = {"tool_name": tool_result.tool_name, "metadata": dict(tool_result.metadata)}
        return CommandResult(exit_code=0, output=tool_result.content, payload=payload)

    if action in {"exit", "finish", "off"}:
        from funcode.tools.advanced import ExitPlanModeTool

        tool_result = ExitPlanModeTool().execute(tool_arguments, tool_context)
        payload = {"tool_name": tool_result.tool_name, "metadata": dict(tool_result.metadata)}
        return CommandResult(exit_code=0, output=tool_result.content, payload=payload)

    if action in {"status", "show"}:
        permission_context = tool_context.permission_context
        state_path = permission_context.plan_mode_state_path
        plan_path = permission_context.plan_mode_plan_path
        payload = {
            "workspace_dir": str(tool_context.workspace_dir.resolve()),
            "plan_dir": str(permission_context.plan_dir.resolve()),
            "state_file_path": str(state_path.resolve()),
            "plan_file_path": str(plan_path.resolve()),
            "state_exists": state_path.exists(),
            "plan_exists": plan_path.exists(),
            "state": None,
        }
        if state_path.exists():
            payload["state"] = json.loads(state_path.read_text(encoding="utf-8"))
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    session_state = _load_session_state_if_available(context)
    if session_state is not None and session_state.plan_steps:
        plan_steps = list(session_state.plan_steps)
    else:
        raw_prompt = (context.settings.cli.prompt or "").strip()
        plan_steps = [segment.strip() for segment in raw_prompt.split("|") if segment.strip()] if raw_prompt else []

    if not plan_steps:
        return CommandResult(exit_code=0, output="当前没有可用计划步骤。", payload={"plan_steps": []})

    rendered = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(plan_steps))
    return CommandResult(exit_code=0, output=rendered, payload={"plan_steps": plan_steps})


def handle_session_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠宸ヤ綔鍖哄彲瑙佺殑浼氳瘽姒傚喌銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    sessions = _list_visible_sessions(context)
    current_session_id = context.settings.runtime.session_id
    payload_sessions: list[dict[str, Any]] = []
    lines: list[str] = []

    for session_state in sessions:
        session_payload = {
            "session_id": session_state.session_id,
            "graph_name": session_state.graph_name,
            "output_format": session_state.output_format,
            "turn_count": session_state.turn_count,
            "message_count": len(session_state.messages),
            "tool_call_count": len(session_state.tool_calls),
            "plan_step_count": len(session_state.plan_steps),
            "latest_output": session_state.latest_output,
            "is_current": session_state.session_id == current_session_id,
            "created_at": session_state.created_at,
            "updated_at": session_state.updated_at,
        }
        payload_sessions.append(session_payload)
        marker = "*" if session_payload["is_current"] else "-"
        lines.append(
            f"{marker} {session_state.session_id} | {session_state.graph_name} | "
            f"turns={session_state.turn_count} | messages={len(session_state.messages)}"
        )

    if not lines:
        lines.append("当前工作区没有可见的会话文件。")

    payload = {
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "session_count": len(payload_sessions),
        "current_session_id": current_session_id,
        "sessions": payload_sessions,
    }
    return CommandResult(exit_code=0, output="\n".join(lines), payload=payload)


def handle_mcp_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭褰撳墠宸ヤ綔鍖哄凡娉ㄥ唽鐨?MCP 璧勬簮鍒楄〃銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    registry = _load_mcp_registry(context)
    resources = [
        {
            "uri": resource.uri,
            "title": resource.title,
            "path": str(resource.path),
            "description": resource.description,
        }
        for resource in registry.list_resources()
    ]
    return CommandResult(
        exit_code=0,
        output=_render_json(resources),
        payload={"resource_count": len(resources), "resources": resources},
    )


def handle_tools_command(context: CommandContext) -> CommandResult:
    """
    杈撳嚭榛樿宸ュ叿鍒楄〃銆?    :param context: 鍛戒护涓婁笅鏂囥€?    :return: 鍛戒护缁撴灉銆?    """

    tool_names = create_default_tool_registry().list_tools()
    for required_tool_name in ("lsp", "enter_plan_mode", "exit_plan_mode"):
        if required_tool_name not in tool_names:
            tool_names.append(required_tool_name)
    tool_names = sorted(tool_names)
    return CommandResult(
        exit_code=0,
        output=_render_json(tool_names),
        payload={"tool_count": len(tool_names), "tools": tool_names},
    )


def handle_agents_command(context: CommandContext) -> CommandResult:
    """
    输出或管理当前工作区可见的代理定义。

    默认动作是 list；如果上下文 extras 中提供了 action，则会进入真实的
    create / update / delete / get 流程，并直接读写 `.funcode/agents`。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    lifecycle = _build_swarm_lifecycle_service(context)
    agent_lifecycle = AgentLifecycleService(context.settings.runtime.workspace_dir)
    action = _command_action(context)

    if action in {"list", "snapshot"}:
        snapshot = lifecycle.agent_snapshot()
        agents = list(snapshot["agents"])
        output_lines = [
            f"workspace: {snapshot['workspace_dir']}",
            f"agent_count: {snapshot['agent_count']}",
        ]
        if not agents:
            output_lines.append("当前没有可见的代理定义。")
        else:
            for agent in agents:
                runtime_state = agent.get("runtime_state") or {}
                status = runtime_state.get("status", "pending")
                output_lines.append(
                    f"- {agent['agent_name']} [{agent['role']}] {status} | {agent['description']}"
                )
        return CommandResult(
            exit_code=0,
            output="\n".join(output_lines),
            payload=snapshot,
        )

    if action == "get":
        agent_name = _command_extra(context, "agent_name")
        if agent_name is None:
            raise ValueError("agents get 需要提供 agent_name")
        definition = lifecycle.get_agent(str(agent_name))
        payload = definition.model_dump(mode="json")
        return CommandResult(
            exit_code=0,
            output=_render_json(payload),
            payload=payload,
        )

    if action == "create":
        agent_name = _command_extra(context, "agent_name")
        role = _command_extra(context, "role")
        description = _command_extra(context, "description")
        if agent_name is None or role is None or description is None:
            raise ValueError("agents create 需要提供 agent_name、role 和 description")
        created_agent = lifecycle.create_agent(
            agent_name=str(agent_name),
            role=str(role),
            description=str(description),
            max_concurrency=int(_command_extra(context, "max_concurrency", 1)),
            source=str(_command_extra(context, "source", "manual")),
            team_name=_command_extra(context, "team_name"),
            tags=_command_extra(context, "tags"),
            runtime_state=_command_extra(context, "runtime_state"),
            metadata=_command_extra(context, "metadata"),
        )
        payload = created_agent.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "update":
        agent_name = _command_extra(context, "agent_name")
        if agent_name is None:
            raise ValueError("agents update 需要提供 agent_name")
        update_payload = {
            key: _command_extra(context, key)
            for key in (
                "role",
                "description",
                "max_concurrency",
                "source",
                "team_name",
                "tags",
                "runtime_state",
                "status",
                "current_task_id",
                "last_task_id",
                "task_count",
                "completed_task_count",
                "failed_task_count",
                "last_seen_at",
                "metadata",
            )
            if _command_extra(context, key) is not None
        }
        updated_agent = lifecycle.update_agent(str(agent_name), **update_payload)
        payload = updated_agent.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "delete":
        agent_name = _command_extra(context, "agent_name")
        if agent_name is None:
            raise ValueError("agents delete 需要提供 agent_name")
        deleted_agent = lifecycle.delete_agent(str(agent_name))
        payload = deleted_agent.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"runs", "list-runs"}:
        records = agent_lifecycle.list_runs(
            agent_name=_command_extra(context, "agent_name"),
            team_name=_command_extra(context, "team_name"),
            status=_command_extra(context, "status"),
        )
        payload = {
            "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
            "run_count": len(records),
            "runs": [record.model_dump(mode="json") for record in records],
        }
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"status", "get-run"}:
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents status/get-run 需要提供 run_id")
        record = agent_lifecycle.get_run(run_id=str(run_id))
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"start", "background", "run-background"}:
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents start/background 需要提供 run_id")
        record = agent_lifecycle.start_background(
            run_id=str(run_id),
            max_turns=int(_command_extra(context, "max_turns", context.settings.runtime.max_turns)),
            system_prompt=_command_extra(context, "system_prompt"),
            graph_name=str(_command_extra(context, "graph_name", context.settings.cli.graph_name)),
            output_format=str(_command_extra(context, "output_format", context.settings.cli.output_format)),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"interrupt", "stop"}:
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents interrupt/stop 需要提供 run_id")
        record = agent_lifecycle.interrupt(
            run_id=str(run_id),
            reason=_command_extra(context, "reason"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"status", "get-run"}:
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents status/get-run 需要提供 run_id")
        record = agent_lifecycle.get_run(run_id=str(run_id))
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"start", "background", "run-background"}:
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents start/background 需要提供 run_id")
        record = agent_lifecycle.start_background(
            run_id=str(run_id),
            max_turns=int(_command_extra(context, "max_turns", context.settings.runtime.max_turns)),
            system_prompt=_command_extra(context, "system_prompt"),
            graph_name=str(_command_extra(context, "graph_name", context.settings.cli.graph_name)),
            output_format=str(_command_extra(context, "output_format", context.settings.cli.output_format)),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"interrupt", "stop"}:
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents interrupt/stop 需要提供 run_id")
        record = agent_lifecycle.interrupt(
            run_id=str(run_id),
            reason=_command_extra(context, "reason"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "spawn":
        agent_name = _command_extra(context, "agent_name")
        instruction = (
            _command_extra(context, "instruction")
            or _command_extra(context, "prompt")
            or _command_extra(context, "content")
            or _command_extra(context, "body")
        )
        if agent_name is None or instruction is None:
            raise ValueError("agents spawn 需要提供 agent_name 和 instruction/prompt/content")
        record = agent_lifecycle.spawn(
            agent_name=str(agent_name),
            instruction=str(instruction),
            title=_command_extra(context, "title"),
            team_name=_command_extra(context, "team_name"),
            expected_output=_command_extra(context, "expected_output"),
            task_id=_command_extra(context, "task_id"),
            parent_run_id=_command_extra(context, "parent_run_id"),
            allowed_tools=_command_extra(context, "allowed_tools", _command_extra(context, "allowedTools")),
            tool_scope=_command_extra(context, "tool_scope", _command_extra(context, "toolScope")),
            worktree_path=_command_extra(context, "worktree_path", _command_extra(context, "worktreePath")),
            fork_context=_command_extra(context, "fork_context", _command_extra(context, "forkContext")),
            use_exact_tools=_command_extra(context, "use_exact_tools", _command_extra(context, "useExactTools")),
            metadata=_command_extra(context, "metadata"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"send", "send_input"}:
        run_id = _command_extra(context, "run_id")
        content = (
            _command_extra(context, "content")
            or _command_extra(context, "body")
            or _command_extra(context, "prompt")
            or _command_extra(context, "instruction")
        )
        if run_id is None or content is None:
            raise ValueError("agents send/send_input 需要提供 run_id 和 content/body/prompt")
        record = agent_lifecycle.send_input(
            run_id=str(run_id),
            content=str(content),
            metadata=_command_extra(context, "metadata"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "wait":
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents wait 需要提供 run_id")
        record = agent_lifecycle.wait(
            run_id=str(run_id),
            max_turns=int(_command_extra(context, "max_turns", context.settings.runtime.max_turns)),
            system_prompt=_command_extra(context, "system_prompt"),
            graph_name=str(_command_extra(context, "graph_name", context.settings.cli.graph_name)),
            output_format=str(_command_extra(context, "output_format", context.settings.cli.output_format)),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "resume":
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents resume 需要提供 run_id")
        record = agent_lifecycle.resume(run_id=str(run_id))
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "close":
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents close 需要提供 run_id")
        record = agent_lifecycle.close(
            run_id=str(run_id),
            reason=_command_extra(context, "reason"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    raise ValueError(f"不支持的 agents 动作：{action}")


def handle_skills_command(context: CommandContext) -> CommandResult:
    """
    扫描当前工作区与本机可见 skills 目录，输出真实技能概况。

    该命令只读取实际目录结构，不做任何 mock 或推断。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    payload = _collect_skill_overview(context)
    output_lines = [
        f"workspace: {payload['workspace_dir']}",
        f"skill_root_count: {payload['skill_root_count']}",
        f"skill_occurrence_count: {payload['skill_occurrence_count']}",
        f"unique_skill_count: {payload['unique_skill_count']}",
    ]
    if not payload["skills"]:
        output_lines.append("当前工作区与本机可见 skills 目录中没有可展示的技能。")
    else:
        for skill_group in payload["skills"]:
            output_lines.append(
                f"- {skill_group['skill_name']} ({skill_group['occurrence_count']})"
            )
            for location in skill_group["locations"]:
                output_lines.append(
                    f"  - root: {location['root']} | path: {location['path']}"
                )
    return CommandResult(exit_code=0, output="\n".join(output_lines), payload=payload)


def handle_plugin_command(context: CommandContext) -> CommandResult:
    """
    输出当前 Python 版的扩展面、注册规模与预留接口说明。

    该命令完全基于当前代码与运行时注册表的真实状态汇总，不返回示意值。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    payload = _collect_plugin_surface(context)
    output_lines = [
        f"workspace: {payload['workspace_dir']}",
        f"package_root: {payload['package_root']}",
        f"command_count: {payload['command_count']}",
        f"tool_count: {payload['tool_count']}",
        f"mcp_resource_count: {payload['mcp_resource_count']}",
        f"implemented_surface_count: {payload['implemented_surface_count']}",
    ]
    if payload["implemented_surfaces"]:
        output_lines.append("implemented_surfaces:")
        for surface in payload["implemented_surfaces"]:
            output_lines.append(
                f"- {surface['surface_name']} | {surface['path']}"
            )
    else:
        output_lines.append("implemented_surfaces: 当前未发现可识别的扩展面目录。")

    output_lines.append("reserved_interfaces:")
    for interface in payload["reserved_interfaces"]:
        output_lines.append(
            f"- {interface['interface']} | {interface['purpose']}"
        )
    return CommandResult(exit_code=0, output="\n".join(output_lines), payload=payload)


def handle_reload_plugins_command(context: CommandContext) -> CommandResult:
    """
    重新扫描当前工作区的技能、插件与命令视图。

    这个命令不修改任何缓存状态，只读取真实文件系统与注册表，
    用于在插件或技能目录发生变化后给出最新的可见面汇总。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    skill_payload = _collect_skill_overview(context)
    plugin_payload = _collect_plugin_surface(context)
    tool_names = create_default_tool_registry().list_tools()
    command_names = _get_registered_command_names()
    payload = {
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "reloaded_at": datetime.now(timezone.utc).isoformat(),
        "command_count": len(command_names),
        "tool_count": len(tool_names),
        "skill_root_count": skill_payload["skill_root_count"],
        "unique_skill_count": skill_payload["unique_skill_count"],
        "mcp_resource_count": plugin_payload["mcp_resource_count"],
        "implemented_surface_count": plugin_payload["implemented_surface_count"],
    }
    output_lines = [
        f"workspace: {payload['workspace_dir']}",
        f"reloaded_at: {payload['reloaded_at']}",
        f"command_count: {payload['command_count']}",
        f"tool_count: {payload['tool_count']}",
        f"skill_root_count: {payload['skill_root_count']}",
        f"unique_skill_count: {payload['unique_skill_count']}",
        f"mcp_resource_count: {payload['mcp_resource_count']}",
        f"implemented_surface_count: {payload['implemented_surface_count']}",
    ]
    return CommandResult(exit_code=0, output="\n".join(output_lines), payload=payload)


def handle_teams_command(context: CommandContext) -> CommandResult:
    """
    输出或管理工作区中的团队定义。

    默认动作是 list；当 extras 中提供 action 时，会执行真实的 create/get/delete。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    lifecycle = _build_swarm_lifecycle_service(context)
    agent_lifecycle = AgentLifecycleService(context.settings.runtime.workspace_dir)
    action = _command_action(context)

    if action in {"list", "snapshot"}:
        teams = lifecycle.list_teams()
        payload_teams: list[dict[str, Any]] = []
        lines: list[str] = []

        for team in teams:
            tasks = lifecycle.list_tasks(team.team_name)
            payload_teams.append(
                {
                    "team_name": team.team_name,
                    "description": team.description,
                    "workspace_dir": team.workspace_dir,
                    "task_count": len(tasks),
                }
            )
            lines.append(f"[{team.team_name}] {team.description} ({len(tasks)} tasks)")

        if not lines:
            lines.append("当前工作区没有已保存的团队。")

        payload = {
            "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
            "team_count": len(payload_teams),
            "teams": payload_teams,
        }
        return CommandResult(exit_code=0, output="\n".join(lines), payload=payload)

    if action == "get":
        team_name = _command_extra(context, "team_name")
        if team_name is None:
            raise ValueError("teams get 需要提供 team_name")
        team = lifecycle.get_team(str(team_name))
        payload = team.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "create":
        team_name = _command_extra(context, "team_name")
        description = _command_extra(context, "description")
        if team_name is None or description is None:
            raise ValueError("teams create 需要提供 team_name 和 description")
        team = lifecycle.create_team(
            team_name=str(team_name),
            description=str(description),
            tags=_command_extra(context, "tags"),
            source=str(_command_extra(context, "source", "workspace")),
            metadata=_command_extra(context, "metadata"),
        )
        payload = team.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "delete":
        team_name = _command_extra(context, "team_name")
        if team_name is None:
            raise ValueError("teams delete 需要提供 team_name")
        deleted_team = lifecycle.delete_team(str(team_name))
        payload = deleted_team.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    raise ValueError(f"不支持的 teams 动作：{action}")


def handle_messages_command(context: CommandContext) -> CommandResult:
    """
    输出共享邮箱中的消息概况。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    mailbox = _build_shared_mailbox(context)
    messages = mailbox.read_for("*")
    payload_messages: list[dict[str, Any]] = []
    lines: list[str] = []

    for message in messages:
        payload_messages.append(
            {
                "message_id": message.message_id,
                "team_name": message.team_name,
                "sender": message.sender,
                "recipient": message.recipient,
                "subject": message.subject,
                "created_at": message.created_at.isoformat(),
            }
        )
        lines.append(
            f"[{message.team_name}] {message.sender} -> {message.recipient} | {message.subject}"
        )

    if not lines:
        lines.append("当前工作区共享邮箱中没有消息。")

    payload = {
        "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
        "message_count": len(payload_messages),
        "messages": payload_messages,
    }
    return CommandResult(exit_code=0, output="\n".join(lines), payload=payload)


def handle_resume_command(context: CommandContext) -> CommandResult:
    """
    恢复最近一次会话并输出其真实概况。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    session_state = _select_latest_session(context)
    if session_state is None:
        output = "当前工作区没有可恢复的会话。"
        return CommandResult(
            exit_code=1,
            output=output,
            payload={
                "session": None,
                "memory": None,
                "selected_as_current_view": None,
            },
        )

    payload = _build_session_overview_payload(
        session_state,
        current_session_id=context.settings.runtime.session_id,
    )
    output_lines = _build_session_overview_lines(payload)
    if session_state.session_id == context.settings.runtime.session_id:
        output_lines.insert(1, "当前上下文会话已作为视图输出。")
    else:
        output_lines.insert(1, "已选择最近更新的会话作为当前视图。")
    return CommandResult(
        exit_code=0,
        output="\n".join(output_lines),
        payload=payload,
    )


def handle_compact_command(context: CommandContext) -> CommandResult:
    """
    基于当前会话生成真实压缩摘要。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    session_state = _select_current_or_latest_session(context)
    if session_state is None:
        output = "当前工作区没有可压缩的会话。"
        return CommandResult(
            exit_code=1,
            output=output,
            payload={
                "session": None,
                "memory": None,
                "compression": None,
                "summary_text": None,
            },
        )

    compression_result = compress_messages(session_state.messages)
    memory_snapshot = build_memory_snapshot(session_state.messages)
    compression_payload = asdict(compression_result)
    memory_payload = asdict(memory_snapshot)
    summary_text = ""
    if compression_result.summary_message is not None:
        summary_text = str(compression_result.summary_message.get("content") or "").strip()
    if not summary_text:
        summary_text = memory_snapshot.summary_text.strip()

    output_lines = [
        f"当前会话: {session_state.session_id}",
        f"压缩策略: {compression_result.strategy}",
        (
            f"消息数: {compression_result.original_message_count} -> "
            f"{compression_result.compressed_message_count}"
        ),
        (
            f"字符数: {compression_result.original_character_count} -> "
            f"{compression_result.compressed_character_count}"
        ),
    ]
    if summary_text:
        output_lines.append("压缩摘要:")
        output_lines.extend(summary_text.splitlines())
    else:
        output_lines.append("压缩摘要: 当前会话没有可压缩的有效摘要内容。")

    payload = {
        "session_id": session_state.session_id,
        "compression": compression_payload,
        "memory": memory_payload,
        "summary_text": summary_text,
        "selected_as_current_view": session_state.session_id,
    }
    return CommandResult(
        exit_code=0,
        output="\n".join(output_lines),
        payload=payload,
    )


def handle_clear_command(context: CommandContext) -> CommandResult:
    """
    直接清理当前工作区的会话文件或会话目录。

    :param context: 命令上下文。
    :return: 命令结果。
    """

    try:
        clear_result = _clear_session_storage(context)
    except FileNotFoundError as exc:
        return CommandResult(
            exit_code=1,
            output=str(exc),
            payload={
                "cleared": False,
                "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
                "error": str(exc),
            },
        )

    output_lines = [
        f"清理范围: {clear_result['scope']}",
        f"删除文件数: {clear_result['deleted_count']}",
    ]
    for deleted_path in clear_result["deleted_paths"]:
        output_lines.append(f"- {deleted_path}")

    return CommandResult(
        exit_code=0,
        output="\n".join(output_lines),
        payload={
            "cleared": True,
            **clear_result,
        },
    )


def handle_agents_command(context: CommandContext) -> CommandResult:
    """
    输出或管理当前工作区可见的代理定义。

    该实现覆盖前面的只读版本，支持通过 extras 传入的真实增删改查动作。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    lifecycle = _build_swarm_lifecycle_service(context)
    agent_lifecycle = AgentLifecycleService(context.settings.runtime.workspace_dir)
    action = _command_action(context)

    if action in {"list", "snapshot"}:
        snapshot = lifecycle.agent_snapshot()
        agents = list(snapshot["agents"])
        output_lines = [
            f"workspace: {snapshot['workspace_dir']}",
            f"agent_count: {snapshot['agent_count']}",
        ]
        if not agents:
            output_lines.append("当前没有可见的代理定义。")
        else:
            for agent in agents:
                runtime_state = agent.get("runtime_state") or {}
                status = runtime_state.get("status", "pending")
                output_lines.append(
                    f"- {agent['agent_name']} [{agent['role']}] {status} | {agent['description']}"
                )
        return CommandResult(exit_code=0, output="\n".join(output_lines), payload=snapshot)

    if action == "get":
        agent_name = _command_extra(context, "agent_name")
        if agent_name is None:
            raise ValueError("agents get 需要提供 agent_name")
        definition = lifecycle.get_agent(str(agent_name))
        payload = definition.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "create":
        agent_name = _command_extra(context, "agent_name")
        role = _command_extra(context, "role")
        description = _command_extra(context, "description")
        if agent_name is None or role is None or description is None:
            raise ValueError("agents create 需要提供 agent_name、role 和 description")
        created_agent = lifecycle.create_agent(
            agent_name=str(agent_name),
            role=str(role),
            description=str(description),
            max_concurrency=int(_command_extra(context, "max_concurrency", 1)),
            source=str(_command_extra(context, "source", "manual")),
            team_name=_command_extra(context, "team_name"),
            tags=_command_extra(context, "tags"),
            runtime_state=_command_extra(context, "runtime_state"),
            metadata=_command_extra(context, "metadata"),
        )
        payload = created_agent.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "update":
        agent_name = _command_extra(context, "agent_name")
        if agent_name is None:
            raise ValueError("agents update 需要提供 agent_name")
        update_payload = {
            key: _command_extra(context, key)
            for key in (
                "role",
                "description",
                "max_concurrency",
                "source",
                "team_name",
                "tags",
                "runtime_state",
                "status",
                "current_task_id",
                "last_task_id",
                "task_count",
                "completed_task_count",
                "failed_task_count",
                "last_seen_at",
                "metadata",
            )
            if _command_extra(context, key) is not None
        }
        updated_agent = lifecycle.update_agent(str(agent_name), **update_payload)
        payload = updated_agent.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "delete":
        agent_name = _command_extra(context, "agent_name")
        if agent_name is None:
            raise ValueError("agents delete 需要提供 agent_name")
        deleted_agent = lifecycle.delete_agent(str(agent_name))
        payload = deleted_agent.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"runs", "list-runs"}:
        records = agent_lifecycle.list_runs(
            agent_name=_command_extra(context, "agent_name"),
            team_name=_command_extra(context, "team_name"),
            status=_command_extra(context, "status"),
        )
        payload = {
            "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
            "run_count": len(records),
            "runs": [record.model_dump(mode="json") for record in records],
        }
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "spawn":
        agent_name = _command_extra(context, "agent_name")
        instruction = (
            _command_extra(context, "instruction")
            or _command_extra(context, "prompt")
            or _command_extra(context, "content")
            or _command_extra(context, "body")
        )
        if agent_name is None or instruction is None:
            raise ValueError("agents spawn 需要提供 agent_name 和 instruction/prompt/content")
        record = agent_lifecycle.spawn(
            agent_name=str(agent_name),
            instruction=str(instruction),
            title=_command_extra(context, "title"),
            team_name=_command_extra(context, "team_name"),
            expected_output=_command_extra(context, "expected_output"),
            task_id=_command_extra(context, "task_id"),
            parent_run_id=_command_extra(context, "parent_run_id"),
            allowed_tools=_command_extra(context, "allowed_tools", _command_extra(context, "allowedTools")),
            tool_scope=_command_extra(context, "tool_scope", _command_extra(context, "toolScope")),
            worktree_path=_command_extra(context, "worktree_path", _command_extra(context, "worktreePath")),
            fork_context=_command_extra(context, "fork_context", _command_extra(context, "forkContext")),
            use_exact_tools=_command_extra(context, "use_exact_tools", _command_extra(context, "useExactTools")),
            metadata=_command_extra(context, "metadata"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action in {"send", "send_input"}:
        run_id = _command_extra(context, "run_id")
        content = (
            _command_extra(context, "content")
            or _command_extra(context, "body")
            or _command_extra(context, "prompt")
            or _command_extra(context, "instruction")
        )
        if run_id is None or content is None:
            raise ValueError("agents send/send_input 需要提供 run_id 和 content/body/prompt")
        record = agent_lifecycle.send_input(
            run_id=str(run_id),
            content=str(content),
            metadata=_command_extra(context, "metadata"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "wait":
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents wait 需要提供 run_id")
        record = agent_lifecycle.wait(
            run_id=str(run_id),
            max_turns=int(_command_extra(context, "max_turns", context.settings.runtime.max_turns)),
            system_prompt=_command_extra(context, "system_prompt"),
            graph_name=str(_command_extra(context, "graph_name", context.settings.cli.graph_name)),
            output_format=str(_command_extra(context, "output_format", context.settings.cli.output_format)),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "resume":
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents resume 需要提供 run_id")
        record = agent_lifecycle.resume(run_id=str(run_id))
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "close":
        run_id = _command_extra(context, "run_id")
        if run_id is None:
            raise ValueError("agents close 需要提供 run_id")
        record = agent_lifecycle.close(
            run_id=str(run_id),
            reason=_command_extra(context, "reason"),
        )
        payload = record.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    raise ValueError(f"不支持的 agents 动作：{action}")


def handle_teams_command(context: CommandContext) -> CommandResult:
    """
    输出或管理工作区中的团队定义。

    该实现覆盖前面的只读版本，支持真实的 list/get/create/delete。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    lifecycle = _build_swarm_lifecycle_service(context)
    action = _command_action(context)

    if action in {"list", "snapshot"}:
        teams = lifecycle.list_teams()
        payload_teams: list[dict[str, Any]] = []
        lines: list[str] = []
        for team in teams:
            tasks = lifecycle.list_tasks(team.team_name)
            payload_teams.append(
                {
                    "team_name": team.team_name,
                    "description": team.description,
                    "workspace_dir": team.workspace_dir,
                    "task_count": len(tasks),
                }
            )
            lines.append(f"[{team.team_name}] {team.description} ({len(tasks)} tasks)")
        if not lines:
            lines.append("当前工作区没有已保存的团队。")
        payload = {
            "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
            "team_count": len(payload_teams),
            "teams": payload_teams,
        }
        return CommandResult(exit_code=0, output="\n".join(lines), payload=payload)

    if action == "get":
        team_name = _command_extra(context, "team_name")
        if team_name is None:
            raise ValueError("teams get 需要提供 team_name")
        team = lifecycle.get_team(str(team_name))
        payload = team.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "create":
        team_name = _command_extra(context, "team_name")
        description = _command_extra(context, "description")
        if team_name is None or description is None:
            raise ValueError("teams create 需要提供 team_name 和 description")
        team = lifecycle.create_team(
            team_name=str(team_name),
            description=str(description),
            tags=_command_extra(context, "tags"),
            source=str(_command_extra(context, "source", "workspace")),
            metadata=_command_extra(context, "metadata"),
        )
        payload = team.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "delete":
        team_name = _command_extra(context, "team_name")
        if team_name is None:
            raise ValueError("teams delete 需要提供 team_name")
        deleted_team = lifecycle.delete_team(str(team_name))
        payload = deleted_team.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    raise ValueError(f"不支持的 teams 动作：{action}")


def handle_tasks_command(context: CommandContext) -> CommandResult:
    """
    输出或管理工作区中的团队任务。

    该实现覆盖前面的只读版本，支持真实的 get/create/update/stop。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    lifecycle = _build_swarm_lifecycle_service(context)
    session_state = _load_session_state_if_available(context)
    action = _command_action(context)

    if action in {"list", "snapshot"}:
        payload_teams: list[dict[str, Any]] = []
        lines: list[str] = []
        for team in lifecycle.list_teams():
            tasks = lifecycle.list_tasks(team.team_name)
            payload_teams.append(
                {
                    "team_name": team.team_name,
                    "description": team.description,
                    "workspace_dir": team.workspace_dir,
                    "task_count": len(tasks),
                    "tasks": [task.model_dump(mode="json") for task in tasks],
                }
            )
            lines.append(f"[{team.team_name}] {team.description} ({len(tasks)} tasks)")
            for task in tasks:
                lines.append(f"- {task.task_id} | {task.status} | {task.subject}")

        payload_session: dict[str, Any] | None = None
        if session_state is not None:
            payload_session = {
                "session_id": session_state.session_id,
                "graph_name": session_state.graph_name,
                "output_format": session_state.output_format,
                "turn_count": session_state.turn_count,
                "message_count": len(session_state.messages),
                "plan_steps": list(session_state.plan_steps),
                "latest_output": session_state.latest_output,
            }
            lines.append(
                f"[session] {session_state.session_id} | turns={session_state.turn_count} | "
                f"messages={len(session_state.messages)} | plans={len(session_state.plan_steps)}"
            )

        if not lines:
            lines.append("当前工作区没有已保存的团队或任务。")

        return CommandResult(
            exit_code=0,
            output="\n".join(lines),
            payload={"session": payload_session, "teams": payload_teams},
        )

    if action == "get":
        team_name = _command_extra(context, "team_name")
        task_id = _command_extra(context, "task_id")
        if team_name is None or task_id is None:
            raise ValueError("tasks get 需要提供 team_name 和 task_id")
        task = lifecycle.get_task(str(team_name), str(task_id))
        payload = task.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "create":
        team_name = _command_extra(context, "team_name")
        subject = _command_extra(context, "subject")
        detail = _command_extra(context, "detail")
        if team_name is None or subject is None or detail is None:
            raise ValueError("tasks create 需要提供 team_name、subject 和 detail")
        task = lifecycle.create_task(
            team_name=str(team_name),
            subject=str(subject),
            detail=str(detail),
            owner=_command_extra(context, "owner"),
            dependencies=_command_extra(context, "dependencies"),
            labels=_command_extra(context, "labels"),
            priority=int(_command_extra(context, "priority", 0)),
            status=str(_command_extra(context, "status", "pending")),
            task_id=_command_extra(context, "task_id"),
            metadata=_command_extra(context, "metadata"),
        )
        payload = task.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "update":
        team_name = _command_extra(context, "team_name")
        task_id = _command_extra(context, "task_id")
        if team_name is None or task_id is None:
            raise ValueError("tasks update 需要提供 team_name 和 task_id")
        update_payload = {
            key: _command_extra(context, key)
            for key in ("owner", "status", "detail", "labels", "priority", "attempt_count", "metadata")
            if _command_extra(context, key) is not None
        }
        update_model = SwarmTaskUpdate.model_validate(update_payload)
        updated_task = lifecycle.update_task(str(team_name), str(task_id), update_model)
        payload = updated_task.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    if action == "stop":
        team_name = _command_extra(context, "team_name")
        task_id = _command_extra(context, "task_id")
        if team_name is None or task_id is None:
            raise ValueError("tasks stop 需要提供 team_name 和 task_id")
        stopped_task = lifecycle.stop_task(str(team_name), str(task_id))
        payload = stopped_task.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    raise ValueError(f"不支持的 tasks 动作：{action}")


def handle_messages_command(context: CommandContext) -> CommandResult:
    """
    输出或管理共享邮箱消息。

    该实现覆盖前面的只读版本，支持真实的 list/send/read。
    :param context: 命令上下文。
    :return: 命令结果。
    """

    lifecycle = _build_swarm_lifecycle_service(context)
    action = _command_action(context)

    if action in {"list", "snapshot"}:
        messages = lifecycle.list_messages("*")
        payload_messages: list[dict[str, Any]] = []
        lines: list[str] = []
        for message in messages:
            payload_messages.append(
                {
                    "message_id": message.message_id,
                    "team_name": message.team_name,
                    "sender": message.sender,
                    "recipient": message.recipient,
                    "subject": message.subject,
                    "created_at": message.created_at.isoformat(),
                }
            )
            lines.append(
                f"[{message.team_name}] {message.sender} -> {message.recipient} | {message.subject}"
            )
        if not lines:
            lines.append("当前工作区共享邮箱中没有消息。")
        payload = {
            "workspace_dir": str(context.settings.runtime.workspace_dir.resolve()),
            "message_count": len(payload_messages),
            "messages": payload_messages,
        }
        return CommandResult(exit_code=0, output="\n".join(lines), payload=payload)

    if action == "read":
        team_name = _command_extra(context, "team_name")
        recipient = _command_extra(context, "recipient", "*")
        if team_name is None:
            raise ValueError("messages read 需要提供 team_name")
        messages = lifecycle.read_mailbox(str(team_name), str(recipient))
        payload_messages = [message.model_dump(mode="json") for message in messages]
        output = _render_json(payload_messages)
        return CommandResult(
            exit_code=0,
            output=output,
            payload={"team_name": str(team_name), "recipient": str(recipient), "messages": payload_messages},
        )

    if action == "send":
        team_name = _command_extra(context, "team_name")
        sender = _command_extra(context, "sender")
        recipient = _command_extra(context, "recipient")
        subject = _command_extra(context, "subject")
        body = _command_extra(context, "body")
        if team_name is None or sender is None or recipient is None or subject is None or body is None:
            raise ValueError("messages send 需要提供 team_name、sender、recipient、subject 和 body")
        message = lifecycle.send_message(
            team_name=str(team_name),
            sender=str(sender),
            recipient=str(recipient),
            subject=str(subject),
            body=str(body),
            message_id=_command_extra(context, "message_id"),
            reply_to=_command_extra(context, "reply_to"),
            thread_id=_command_extra(context, "thread_id"),
            message_type=str(_command_extra(context, "message_type", "note")),
            metadata=_command_extra(context, "metadata"),
        )
        payload = message.model_dump(mode="json")
        return CommandResult(exit_code=0, output=_render_json(payload), payload=payload)

    raise ValueError(f"不支持的 messages 动作：{action}")








