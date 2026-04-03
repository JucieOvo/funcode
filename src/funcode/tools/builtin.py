"""
模块名称：builtin
功能描述：
    定义 Funcode Python 版的内置真实工具集合，覆盖文件读取、目录遍历、
    路径匹配、文本搜索、文件写入、PowerShell 执行、计划更新与 MCP 资源读取。

主要组件：
    - FileReadTool: 文件读取工具
    - DirectoryListTool: 目录列举工具
    - GlobTool: 递归文件匹配工具
    - GrepTool: 文本搜索工具
    - FileWriteTool: 文本写入工具
    - PowerShellCommandTool: PowerShell 命令执行工具
    - PlanUpdateTool: 计划更新工具
    - McpResourceReadTool: MCP 资源读取工具

依赖说明：
    - pathlib: 路径处理
    - funcode.permissions.validators: 路径权限校验
    - funcode.utils.fs: 工作区路径规范化与文本读取
    - funcode.utils.powershell: PowerShell 执行

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现内置工具集合
    - 2026-04-01 JucieOvo: 新增 glob、grep、file_write 工具
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from html import unescape
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from funcode.permissions.validators import ensure_tool_path_allowed
from funcode.swarm.mailbox import FileMailbox
from funcode.swarm.models import SwarmMessage, SwarmTask, SwarmTaskUpdate, SwarmTeam
from funcode.swarm.store import SwarmStore
from funcode.runtime.swarm_lifecycle import SwarmLifecycleService
from funcode.tools.base import BaseTool, ToolResult
from funcode.tools.context import ToolExecutionContext
from funcode.session.repository import SessionRepository
from funcode.schemas.core import SessionState
from funcode.utils.fs import normalize_workspace_path, read_text_file
from funcode.utils.powershell import run_powershell_command


def _resolve_allowed_path(
    context: ToolExecutionContext,
    raw_path: str,
) -> Path:
    """
    将用户输入路径规范化后执行权限校验。

    :param context: 工具执行上下文。
    :param raw_path: 用户输入的原始路径。
    :return: 经过权限校验的绝对路径。
    """

    target_path = normalize_workspace_path(context.workspace_dir, raw_path)
    return ensure_tool_path_allowed(context.permission_context, target_path)


def _iter_text_files(root_dir: Path) -> list[Path]:
    """
    递归收集目录中的全部文件。

    :param root_dir: 搜索根目录。
    :return: 文件路径列表。
    """

    return [entry for entry in sorted(root_dir.rglob("*")) if entry.is_file()]


def _render_json(payload: Any) -> str:
    """
    将结构化数据渲染为稳定的 JSON 文本。
    :param payload: 待输出的数据。
    :return: JSON 格式文本。
    """

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_entity_name(value: Any, entity_label: str) -> str:
    """
    校验用于文件名的实体名称，避免路径穿越与非法分隔符。
    :param value: 原始名称值。
    :param entity_label: 实体中文标签，便于错误提示。
    :return: 规范化后的名称。
    :raises ValueError: 当名称为空或包含非法路径片段时触发。
    """

    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{entity_label} 不能为空")
    if normalized in {".", ".."}:
        raise ValueError(f"{entity_label} 不能是保留路径片段")
    if Path(normalized).name != normalized:
        raise ValueError(f"{entity_label} 不能包含路径分隔符")
    if ":" in normalized:
        raise ValueError(f"{entity_label} 不能包含冒号")
    return normalized


def _build_swarm_store(context: ToolExecutionContext) -> SwarmStore:
    """
    为当前工作区构造团队持久化存储。
    :param context: 工具执行上下文。
    :return: 团队存储对象。
    """

    swarm_root = _resolve_allowed_path(context, ".funcode/swarm")
    return SwarmStore(swarm_root)


def _build_mailbox(context: ToolExecutionContext) -> FileMailbox:
    """
    为当前工作区构造共享消息邮箱。
    :param context: 工具执行上下文。
    :return: 文件邮箱对象。
    """

    mailbox_path = _resolve_allowed_path(context, ".funcode/swarm/mailbox.jsonl")
    return FileMailbox(mailbox_path)


def _build_session_repository(context: ToolExecutionContext) -> SessionRepository:
    """
    构建当前工作区对应的会话仓库。
    :param context: 工具执行上下文。
    :return: 会话仓库对象。
    """

    return SessionRepository(context.workspace_dir)


def _build_task_output_path(context: ToolExecutionContext, output_name: str) -> Path:
    """
    构建任务输出文件的真实落盘路径。
    :param context: 工具执行上下文。
    :param output_name: 输出名称。
    :return: 经过权限校验后的目标文件路径。
    """

    normalized_name = _normalize_entity_name(output_name, "name")
    return _resolve_allowed_path(context, f".funcode/tasks-output/{normalized_name}.md")


def _format_session_brief(session_state: SessionState | None) -> str:
    """
    将会话状态渲染为便于阅读的简短摘要。
    :param session_state: 会话状态对象，允许为空。
    :return: 适合用于 brief 工具输出的文本。
    """

    if session_state is None:
        return "当前工作区没有可用会话记录。"

    latest_output = (session_state.latest_output or "").strip()
    if len(latest_output) > 400:
        latest_output = f"{latest_output[:400].rstrip()}..."

    lines = [
        f"- 会话 ID: {session_state.session_id}",
        f"- 图名称: {session_state.graph_name}",
        f"- 输出格式: {session_state.output_format}",
        f"- 轮次: {session_state.turn_count}",
        f"- 消息数: {len(session_state.messages)}",
        f"- 工具调用数: {len(session_state.tool_calls)}",
        f"- 工具结果数: {len(session_state.tool_results)}",
        f"- 计划步骤数: {len(session_state.plan_steps)}",
    ]
    if latest_output:
        lines.append(f"- 最近输出: {latest_output}")
    return "\n".join(lines)


def _select_session_state(context: ToolExecutionContext) -> SessionState | None:
    """
    从当前工作区中选取最合适的会话快照。
    优先级：
    1. 当前运行时显式指定的 session_id。
    2. 最近修改的会话文件。
    :param context: 工具执行上下文。
    :return: 可用于 brief 摘要的会话状态，若无则返回 None。
    """

    repository = _build_session_repository(context)
    session_id = context.settings.runtime.session_id
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


def _build_brief_text(context: ToolExecutionContext) -> str:
    """
    基于工作区、会话和团队存储生成真实摘要文本。
    :param context: 工具执行上下文。
    :return: 适合人类阅读的摘要文本。
    """

    workspace_root = context.workspace_dir.resolve()
    repository = _build_session_repository(context)
    session_state = _select_session_state(context)
    store = _build_swarm_store(context)
    teams = store.list_teams()
    total_tasks = sum(len(store.list_tasks(team.team_name)) for team in teams)
    resources = context.mcp_registry.list_resources()
    workspace_entries = [
        entry.name
        for entry in sorted(workspace_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if entry.name not in {".git", ".funcode"}
    ]
    session_files = []
    if repository.storage_dir.exists():
        session_files = sorted(path.name for path in repository.storage_dir.glob("*.json"))

    lines = [
        "# 工作区简报",
        f"- 工作区: {workspace_root}",
        f"- 目录条目数: {len(workspace_entries)}",
        f"- 会话文件数: {len(session_files)}",
        f"- 团队数: {len(teams)}",
        f"- 任务数: {total_tasks}",
        f"- MCP 资源数: {len(resources)}",
    ]
    if workspace_entries:
        lines.append(f"- 工作区顶层条目: {', '.join(workspace_entries[:12])}")
    if teams:
        team_summaries = []
        for team in teams[:8]:
            team_summaries.append(f"{team.team_name}({len(store.list_tasks(team.team_name))})")
        lines.append(f"- 团队概览: {', '.join(team_summaries)}")
    lines.append("")
    lines.append("## 会话概况")
    lines.append(_format_session_brief(session_state))
    lines.append("")
    lines.append("## 当前计划")
    if context.plan_steps:
        lines.extend(f"- {step}" for step in context.plan_steps)
    else:
        lines.append("- 当前没有记录的计划步骤。")
    if resources:
        lines.append("")
        lines.append("## MCP 资源")
        lines.extend(f"- {resource.title}: {resource.uri}" for resource in resources[:10])
    return "\n".join(lines).strip()


def _build_questions_directory(context: ToolExecutionContext) -> Path:
    """
    构建工作区内用于保存提问记录的真实目录。

    :param context: 工具执行上下文。
    :return: 已经完成权限校验的 questions 目录路径。
    """

    return _resolve_allowed_path(context, ".funcode/questions")


def _normalize_question_options(raw_options: Any) -> list[str]:
    """
    将用户传入的可选项标准化为字符串列表。

    :param raw_options: 用户输入的原始可选项，可以是列表、JSON 字符串或普通字符串。
    :return: 清洗后的可选项列表。
    :raises ValueError: 当可选项类型无法识别时触发。
    """

    if raw_options is None:
        return []
    if isinstance(raw_options, list):
        return [str(item).strip() for item in raw_options if str(item).strip()]
    if isinstance(raw_options, str):
        text = raw_options.strip()
        if not text:
            return []
        try:
            parsed_options = json.loads(text)
        except json.JSONDecodeError:
            return [item.strip() for item in re.split(r"[\n,]+", text) if item.strip()]
        if isinstance(parsed_options, list):
            return [str(item).strip() for item in parsed_options if str(item).strip()]
        raise ValueError("options 字段如果是 JSON 字符串，必须解析为数组")
    raise ValueError("options 必须是列表、JSON 字符串、普通字符串或 None")


def _strip_html_tags(html_text: str) -> str:
    """
    将搜索结果中的 HTML 片段还原为可读文本。

    :param html_text: 原始 HTML 片段。
    :return: 清理后的纯文本。
    """

    text = unescape(html_text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_duckduckgo_url(raw_url: str) -> str:
    """
    将 DuckDuckGo 搜索结果中的跳转链接还原为目标链接。

    :param raw_url: DuckDuckGo 返回的原始地址。
    :return: 可直接展示或访问的目标地址。
    """

    absolute_url = urljoin("https://duckduckgo.com", raw_url)
    parsed_url = urlparse(absolute_url)
    query_values = parse_qs(parsed_url.query)
    if "uddg" in query_values and query_values["uddg"]:
        return unquote(query_values["uddg"][0])
    return absolute_url


def _extract_duckduckgo_results(html_text: str, max_results: int) -> list[dict[str, str]]:
    """
    从 DuckDuckGo HTML 搜索页面中提取结构化搜索结果。

    :param html_text: 搜索引擎返回的 HTML 文本。
    :param max_results: 最多提取的结果条数。
    :return: 搜索结果列表。
    """

    anchor_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(anchor_pattern.finditer(html_text))
    results: list[dict[str, str]] = []

    for index, match in enumerate(matches[:max_results]):
        next_match_start = matches[index + 1].start() if index + 1 < len(matches) else min(
            len(html_text),
            match.start() + 5000,
        )
        block_text = html_text[match.start() : next_match_start]
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</a>',
            block_text,
            re.IGNORECASE | re.DOTALL,
        )
        results.append(
            {
                "title": _strip_html_tags(match.group(2)),
                "url": _decode_duckduckgo_url(match.group(1)),
                "snippet": _strip_html_tags(snippet_match.group(1)) if snippet_match else "",
            }
        )

    return results


def _looks_like_search_block_page(html_text: str) -> bool:
    """
    判断搜索页面是否更像是被限制访问或人机校验页。

    :param html_text: 搜索响应正文。
    :return: 如果像被拦截页面则返回 True。
    """

    lowered_text = html_text.lower()
    blocked_markers = (
        "captcha",
        "verify",
        "access denied",
        "blocked",
        "robot",
        "unusual traffic",
    )
    return any(marker in lowered_text for marker in blocked_markers)


def _search_default_tools(query: str) -> list[dict[str, str]]:
    """
    基于当前默认工具注册表执行名称和描述搜索。

    :param query: 用户输入的检索关键词。
    :return: 命中的工具列表。
    """

    from funcode.tools.registry import create_default_tool_registry

    registry = create_default_tool_registry()
    needle = query.casefold()
    matches: list[dict[str, str]] = []
    for tool_name in registry.list_tools():
        tool = registry.get(tool_name)
        haystack = f"{tool.name}\n{tool.description}".casefold()
        if needle in haystack:
            matches.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                }
            )
    return matches


def _search_duckduckgo(query: str, max_results: int, timeout_seconds: float) -> list[dict[str, str]]:
    """
    使用真实 HTTP 请求调用 DuckDuckGo 简化搜索接口。

    :param query: 搜索关键词。
    :param max_results: 最多返回的结果条数。
    :param timeout_seconds: 网络超时阈值。
    :return: 结构化搜索结果。
    :raises ConnectionError: 当网络不可用或搜索引擎返回限制页面时触发。
    :raises RuntimeError: 当搜索引擎返回非成功状态码时触发。
    """

    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=us-en"
    request = Request(
        url=search_url,
        headers={
            "User-Agent": "funcode/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.7",
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", response.getcode()))
            response_body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            html_text = response_body.decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"web_search 搜索请求返回失败状态：{exc.code}") from exc
    except URLError as exc:
        raise ConnectionError(f"web_search 网络请求失败：{exc.reason}") from exc

    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"web_search 搜索请求返回非成功状态：{status_code}")

    results = _extract_duckduckgo_results(html_text, max_results=max_results)
    if not results and _looks_like_search_block_page(html_text):
        raise ConnectionError("web_search 访问搜索引擎时受到限制，当前环境无法完成真实搜索")
    return results


def _candidate_skill_roots(workspace_dir: Path) -> list[Path]:
    """
    生成当前工作区与本机可见的 skills 目录候选列表。
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


def _collect_skill_catalog(workspace_dir: Path) -> list[dict[str, str]]:
    """
    收集当前工作区与本机可见的真实 skills 目录条目。
    """

    workspace_dir = workspace_dir.resolve()
    skill_catalog: list[dict[str, str]] = []
    for skill_root in _candidate_skill_roots(workspace_dir):
        for entry in sorted(skill_root.iterdir(), key=lambda path: path.name.casefold()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            skill_catalog.append(
                {
                    "skill_name": entry.name,
                    "root": str(skill_root),
                    "path": str(entry),
                    "resolved_path": str(entry.resolve(strict=False)),
                }
            )
    return skill_catalog


def _build_todo_file_path(context: ToolExecutionContext) -> Path:
    """
    构建 TODO 列表的真实持久化文件路径。
    """

    session_key = context.settings.runtime.session_id or "default"
    normalized_key = _normalize_entity_name(session_key, "session_id")
    return _resolve_allowed_path(
        context,
        f".funcode/todos/{normalized_key}.json",
    )


def _normalize_todo_items(raw_todos: Any) -> list[dict[str, Any]]:
    """
    将输入的 TODO 列表规范化为可持久化的结构。
    """

    if not isinstance(raw_todos, list):
        raise ValueError("todo_write 宸ュ叿闇€瑕侀潪绌?todos 鍒楄〃")

    normalized_todos: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_todos, start=1):
        if isinstance(raw_item, str):
            content = raw_item.strip()
            if not content:
                raise ValueError("todo_write 宸ュ叿鍐呯殑 TODO 鏂囨湰涓嶈兘涓虹┖")
            normalized_todos.append(
                {
                    "id": str(index),
                    "content": content,
                    "status": "pending",
                }
            )
            continue

        if not isinstance(raw_item, dict):
            raise ValueError("todo_write 宸ュ叿鐨?todos 鍏冪礌蹇呴』鏄瓧鍏告垨瀛楃涓?")

        content = str(raw_item.get("content", "")).strip()
        if not content:
            raise ValueError("todo_write 宸ュ叿鍐呯殑 TODO content 涓嶈兘涓虹┖")

        status = str(raw_item.get("status", "pending")).strip().lower()
        if status not in {"pending", "in_progress", "completed"}:
            raise ValueError("todo_write 宸ュ叿鍐呯殑 status 蹇呴』鏄?pending、in_progress 鎴?completed")

        normalized_item: dict[str, Any] = {
            "id": str(raw_item.get("id") or index),
            "content": content,
            "status": status,
        }
        if raw_item.get("priority") is not None:
            normalized_item["priority"] = raw_item["priority"]
        if raw_item.get("assignee") is not None:
            normalized_item["assignee"] = str(raw_item["assignee"]).strip()
        if raw_item.get("note") is not None:
            normalized_item["note"] = str(raw_item["note"]).strip()
        normalized_todos.append(normalized_item)

    return normalized_todos


class AskUserQuestionTool(BaseTool):
    """
    将问题与可选项写入工作区中的真实 JSON 文件，便于后续人工或代理处理。
    """

    name = "ask_user_question"
    description = "将问题和可选项写入工作区 .funcode/questions 目录并返回文件路径。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        question = str(arguments["question"]).strip()
        if not question:
            raise ValueError("ask_user_question 工具需要非空 question")

        options = _normalize_question_options(arguments.get("options"))
        questions_dir = _build_questions_directory(context)
        questions_dir.mkdir(parents=True, exist_ok=True)

        created_at = datetime.now(timezone.utc)
        record = {
            "tool_name": self.name,
            "workspace_dir": str(context.workspace_dir.resolve()),
            "created_at": created_at.isoformat(),
            "question": question,
            "options": options,
        }
        file_name = f"question-{created_at.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}.json"
        question_path = questions_dir / file_name
        question_path.write_text(_render_json(record), encoding="utf-8")

        return ToolResult(
            tool_name=self.name,
            content=str(question_path),
            metadata={
                "path": str(question_path),
                "question": question,
                "option_count": len(options),
            },
        )


class TodoWriteTool(BaseTool):
    """
    将当前 TODO 列表写入工作区内的真实 JSON 文件。
    """

    name = "todo_write"
    description = "将 TODO 列表写入工作区 .funcode/todos 目录并返回文件路径。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        raw_todos = arguments.get("todos")
        normalized_todos = _normalize_todo_items(raw_todos)
        todo_path = _build_todo_file_path(context)
        todo_path.parent.mkdir(parents=True, exist_ok=True)

        old_todos: list[dict[str, Any]] = []
        if todo_path.exists():
            loaded_document = json.loads(todo_path.read_text(encoding="utf-8"))
            if not isinstance(loaded_document, dict):
                raise ValueError(f"todo_write 目标文件内容损坏：{todo_path}")
            old_todos = loaded_document.get("todos", [])
            if not isinstance(old_todos, list):
                raise ValueError(f"todo_write 目标文件内容损坏：{todo_path}")

        all_done = bool(normalized_todos) and all(
            str(todo.get("status")) == "completed" for todo in normalized_todos
        )
        stored_todos = [] if all_done else normalized_todos
        document = {
            "tool_name": self.name,
            "workspace_dir": str(context.workspace_dir.resolve()),
            "session_id": context.settings.runtime.session_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "todos": stored_todos,
        }
        todo_path.write_text(_render_json(document), encoding="utf-8")

        payload = {
            "file_path": str(todo_path),
            "old_todos": old_todos,
            "new_todos": stored_todos,
            "all_done": all_done,
        }
        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={
                "file_path": str(todo_path),
                "old_count": len(old_todos),
                "new_count": len(stored_todos),
                "all_done": all_done,
            },
        )


class SkillTool(BaseTool):
    """
    在当前工作区与本机可见 skills 目录中检索真实技能条目。
    """

    name = "skill"
    description = "检索当前工作区与本机可见 skills 目录中的真实技能条目。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        if not query:
            raise ValueError("skill 宸ュ叿闇€瑕侀潪绌?query")

        limit = int(arguments.get("limit", 20))
        if limit < 1:
            raise ValueError("skill 宸ュ叿鐨?limit 蹇呴』澶т簬 0")

        workspace_dir = context.workspace_dir.resolve()
        needle = query.casefold()
        skill_catalog = _collect_skill_catalog(workspace_dir)
        matching_skills = [
            skill
            for skill in skill_catalog
            if needle in skill["skill_name"].casefold()
            or needle in skill["root"].casefold()
            or needle in skill["path"].casefold()
        ]

        from funcode.commands.service import create_default_registry

        command_names = create_default_registry().list_commands()
        matching_commands = [
            command_name
            for command_name in command_names
            if needle in command_name.casefold()
        ]

        payload = {
            "workspace_dir": str(workspace_dir),
            "query": query,
            "skill_root_count": len(_candidate_skill_roots(workspace_dir)),
            "skill_count": len(skill_catalog),
            "match_count": len(matching_skills),
            "command_match_count": len(matching_commands),
            "skills": matching_skills[:limit],
            "command_matches": matching_commands[:limit],
        }
        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={
                "query": query,
                "match_count": len(matching_skills),
                "command_match_count": len(matching_commands),
            },
        )


class ToolSearchTool(BaseTool):
    """
    基于默认工具注册表按名称与描述执行检索的工具。
    """

    name = "tool_search"
    description = "基于当前默认工具列表，按名称和描述检索匹配工具并返回结果。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        if not query:
            raise ValueError("tool_search 工具需要非空 query")

        matches = _search_default_tools(query)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(
                {
                    "query": query,
                    "count": len(matches),
                    "tools": matches,
                }
            ),
            metadata={
                "query": query,
                "count": len(matches),
            },
        )


class WebSearchTool(BaseTool):
    """
    通过真实 HTTP 请求调用公开搜索页面并返回简化检索结果。
    """

    name = "web_search"
    description = "通过真实 HTTP 请求执行简化网络搜索，并在受限时明确报错。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        if not query:
            raise ValueError("web_search 工具需要非空 query")

        max_results = int(arguments.get("max_results", 5))
        if max_results < 1:
            raise ValueError("web_search 工具的 max_results 必须大于 0")

        timeout_seconds = float(arguments.get("timeout_seconds", 30))
        if timeout_seconds <= 0:
            raise ValueError("web_search 工具的 timeout_seconds 必须大于 0")

        results = _search_duckduckgo(query=query, max_results=max_results, timeout_seconds=timeout_seconds)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(
                {
                    "query": query,
                    "count": len(results),
                    "results": results,
                }
            ),
            metadata={
                "query": query,
                "count": len(results),
                "max_results": max_results,
            },
        )


class FileReadTool(BaseTool):
    """
    读取工作区内文本文件的工具。
    """

    name = "file_read"
    description = "读取指定文本文件内容。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        raw_path = str(arguments["path"])
        allowed_path = _resolve_allowed_path(context, raw_path)
        content = read_text_file(allowed_path)
        return ToolResult(
            tool_name=self.name,
            content=content,
            metadata={"path": str(allowed_path)},
        )


class DirectoryListTool(BaseTool):
    """
    列举目录下文件与子目录的工具。
    """

    name = "list_directory"
    description = "列举指定目录下的文件与子目录。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        raw_path = str(arguments.get("path", "."))
        allowed_path = _resolve_allowed_path(context, raw_path)
        if not allowed_path.exists():
            raise FileNotFoundError(f"目录不存在：{allowed_path}")
        if not allowed_path.is_dir():
            allowed_path = allowed_path.parent
        entries: list[str] = []
        for entry in sorted(allowed_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            entry_type = "FILE" if entry.is_file() else "DIR"
            entries.append(f"{entry_type}\t{entry.name}")
        return ToolResult(
            tool_name=self.name,
            content="\n".join(entries),
            metadata={"path": str(allowed_path), "count": len(entries)},
        )


class GlobTool(BaseTool):
    """
    递归匹配文件路径的工具。
    """

    name = "glob"
    description = "在工作区内递归匹配文件路径。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        pattern = str(arguments["pattern"]).strip()
        if not pattern:
            raise ValueError("glob 工具需要非空 pattern")
        raw_path = str(arguments.get("path", "."))
        allowed_path = _resolve_allowed_path(context, raw_path)
        search_root = allowed_path if allowed_path.is_dir() else allowed_path.parent
        workspace_root = context.workspace_dir.resolve()
        matches = [
            str(path.relative_to(workspace_root))
            for path in search_root.rglob(pattern)
            if path.is_file()
        ]
        return ToolResult(
            tool_name=self.name,
            content="\n".join(matches),
            metadata={"root": str(search_root), "pattern": pattern, "count": len(matches)},
        )


class GrepTool(BaseTool):
    """
    在文本文件中搜索关键字的工具。
    """

    name = "grep"
    description = "在工作区内递归搜索文本关键字。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        pattern = str(arguments["pattern"]).strip()
        if not pattern:
            raise ValueError("grep 工具需要非空 pattern")
        raw_path = str(arguments.get("path", "."))
        ignore_case = bool(arguments.get("ignore_case", False))
        allowed_path = _resolve_allowed_path(context, raw_path)
        search_root = allowed_path if allowed_path.is_dir() else allowed_path.parent
        workspace_root = context.workspace_dir.resolve()
        needle = pattern.casefold() if ignore_case else pattern
        matches: list[str] = []
        for file_path in _iter_text_files(search_root):
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                haystack = line.casefold() if ignore_case else line
                if needle in haystack:
                    matches.append(
                        f"{file_path.relative_to(workspace_root)}:{line_number}:{line}"
                    )
        return ToolResult(
            tool_name=self.name,
            content="\n".join(matches),
            metadata={"root": str(search_root), "pattern": pattern, "count": len(matches)},
        )


class FileWriteTool(BaseTool):
    """
    将文本内容写入文件的工具。
    """

    name = "file_write"
    description = "写入或覆盖指定文本文件内容。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        raw_path = str(arguments["path"])
        content = str(arguments.get("content", ""))
        overwrite = bool(arguments.get("overwrite", True))
        allowed_path = _resolve_allowed_path(context, raw_path)
        if allowed_path.exists() and not overwrite:
            raise FileExistsError(f"目标文件已存在且不允许覆盖：{allowed_path}")
        allowed_path.parent.mkdir(parents=True, exist_ok=True)
        allowed_path.write_text(content, encoding="utf-8")
        return ToolResult(
            tool_name=self.name,
            content=content,
            metadata={
                "path": str(allowed_path),
                "overwrite": overwrite,
                "written_chars": len(content),
            },
        )


class TaskOutputTool(BaseTool):
    """
    将任务输出写入工作区中的独立 Markdown 文件。
    """

    name = "task_output"
    description = "将任务输出文本写入工作区 .funcode/tasks-output 目录。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        output_name = str(arguments["name"]).strip()
        if not output_name:
            raise ValueError("task_output 工具需要非空 name")

        raw_text = arguments.get("text", arguments.get("content", ""))
        content_text = str(raw_text).strip()
        if not content_text:
            raise ValueError("task_output 工具需要非空文本内容")

        output_path = _build_task_output_path(context, output_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_text = f"# {output_name}\n\n{content_text}\n"
        output_path.write_text(markdown_text, encoding="utf-8")
        return ToolResult(
            tool_name=self.name,
            content=markdown_text,
            metadata={
                "path": str(output_path),
                "name": output_name,
                "written_chars": len(markdown_text),
            },
        )


class FileEditTool(BaseTool):
    """
    对文本文件执行字符串替换编辑的工具。
    """

    name = "file_edit"
    description = "对指定文本文件进行字符串替换编辑。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        raw_path = str(arguments["path"])
        search_text = str(arguments["search"])
        replace_text = str(arguments.get("replace", ""))
        replace_count_value = arguments.get("count")
        allowed_path = _resolve_allowed_path(context, raw_path)

        if not allowed_path.exists():
            raise FileNotFoundError(f"目标文件不存在：{allowed_path}")

        original_content = allowed_path.read_text(encoding="utf-8")
        if search_text not in original_content:
            raise ValueError("file_edit 找不到需要替换的目标字符串")

        if replace_count_value is None:
            updated_content = original_content.replace(search_text, replace_text)
            replaced_count = original_content.count(search_text)
        else:
            replace_count = int(replace_count_value)
            if replace_count < 1:
                raise ValueError("file_edit 的 count 必须大于 0")
            updated_content = original_content.replace(search_text, replace_text, replace_count)
            replaced_count = min(original_content.count(search_text), replace_count)

        allowed_path.write_text(updated_content, encoding="utf-8")
        return ToolResult(
            tool_name=self.name,
            content=updated_content,
            metadata={
                "path": str(allowed_path),
                "search": search_text,
                "replace": replace_text,
                "replaced_count": replaced_count,
            },
        )


class TaskCreateTool(BaseTool):
    """
    创建并落盘一个新的团队任务。
    """

    name = "task_create"
    description = "创建一个新的团队任务并写入 swarm 存储。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        subject = str(arguments["subject"]).strip()
        detail = str(arguments["detail"]).strip()
        owner_value = arguments.get("owner")
        status_value = arguments.get("status", "pending")
        dependencies_value = arguments.get("dependencies", [])

        if not subject:
            raise ValueError("subject 不能为空")
        if not detail:
            raise ValueError("detail 不能为空")

        if isinstance(dependencies_value, str):
            dependencies = [item.strip() for item in dependencies_value.split(",") if item.strip()]
        elif isinstance(dependencies_value, list):
            dependencies = [str(item).strip() for item in dependencies_value if str(item).strip()]
        else:
            raise ValueError("dependencies 必须是列表或以逗号分隔的字符串")

        owner = str(owner_value).strip() if owner_value is not None else None
        if owner == "":
            owner = None

        task_id = str(arguments.get("task_id") or f"task-{uuid4().hex}")
        created_at = datetime.now(timezone.utc)
        task = SwarmTask(
            task_id=task_id,
            team_name=team_name,
            subject=subject,
            detail=detail,
            owner=owner,
            status=str(status_value),
            dependencies=dependencies,
            created_at=created_at,
            updated_at=created_at,
        )

        store = _build_swarm_store(context)
        store.save_task(task)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(task.model_dump(mode="json")),
            metadata={"team_name": team_name, "task_id": task_id},
        )


class WebFetchTool(BaseTool):
    """
    真实抓取网页内容的工具。
    """

    name = "web_fetch"
    description = "抓取指定 URL 的网页内容并返回状态码。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        url = str(arguments["url"]).strip()
        timeout_seconds = float(arguments.get("timeout_seconds", 30))

        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("web_fetch 只接受 http 或 https URL")

        request = Request(
            url=url,
            headers={
                "User-Agent": "funcode/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*",
            },
        )

        response_body = b""
        status_code = 0
        content_type = ""
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                status_code = int(getattr(response, "status", response.getcode()))
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                response_body = response.read()
                text = response_body.decode(charset, errors="replace")
        except HTTPError as exc:
            status_code = int(exc.code)
            content_type = exc.headers.get_content_type() if exc.headers else "text/plain"
            charset = exc.headers.get_content_charset() if exc.headers else "utf-8"
            response_body = exc.read()
            text = response_body.decode(charset, errors="replace")
        except URLError as exc:
            raise ConnectionError(f"web_fetch 请求失败：{exc.reason}") from exc

        return ToolResult(
            tool_name=self.name,
            content=_render_json(
                {
                    "url": url,
                    "status_code": status_code,
                    "content_type": content_type,
                    "body": text,
                }
            ),
            metadata={
                "url": url,
                "status_code": status_code,
                "content_type": content_type,
                "body_bytes": len(response_body),
            },
        )


class TaskListTool(BaseTool):
    """
    列出指定团队下全部任务的工具。
    """

    name = "task_list"
    description = "列出指定团队下的任务。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        store = _build_swarm_store(context)
        tasks = [task.model_dump(mode="json") for task in store.list_tasks(team_name)]
        return ToolResult(
            tool_name=self.name,
            content=_render_json({"team_name": team_name, "count": len(tasks), "tasks": tasks}),
            metadata={"team_name": team_name, "count": len(tasks)},
        )


class TaskGetTool(BaseTool):
    """
    读取指定团队中的单个任务。
    """

    name = "task_get"
    description = "读取指定团队中的单个任务。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        task_id = _normalize_entity_name(arguments["task_id"], "task_id")
        store = _build_swarm_store(context)
        task = store.load_task(team_name, task_id)
        payload = task.model_dump(mode="json")
        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={"team_name": team_name, "task_id": task_id},
        )


class TaskUpdateTool(BaseTool):
    """
    更新指定任务并落盘。
    """

    name = "task_update"
    description = "更新指定团队中的任务状态、归属人与说明。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        task_id = _normalize_entity_name(arguments["task_id"], "task_id")
        store = _build_swarm_store(context)
        task = store.load_task(team_name, task_id)
        update_payload: dict[str, Any] = {}

        if arguments.get("status") is not None:
            update_payload["status"] = arguments["status"]
        if arguments.get("owner") is not None:
            update_payload["owner"] = str(arguments["owner"]).strip() or None
        notes_value = arguments.get("notes")
        detail_value = arguments.get("detail")
        if detail_value is None and notes_value is not None:
            detail_value = notes_value
        if detail_value is not None:
            update_payload["detail"] = str(detail_value)

        if not update_payload:
            raise ValueError("task_update 至少需要提供 status、owner 或 notes/detail 中的一项")

        update_model = SwarmTaskUpdate.model_validate(update_payload)
        merged_update = update_model.model_dump(mode="json", exclude_none=True)
        updated_task = task.model_copy(
            update={
                **merged_update,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        store.save_task(updated_task)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(updated_task.model_dump(mode="json")),
            metadata={"team_name": team_name, "task_id": task_id},
        )


class TaskStopTool(BaseTool):
    """
    将指定任务标记为已取消并落盘。
    """

    name = "task_stop"
    description = "将指定团队中的任务标记为 cancelled 并写回 swarm 存储。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        task_id = _normalize_entity_name(arguments["task_id"], "task_id")
        store = _build_swarm_store(context)
        task = store.load_task(team_name, task_id)
        updated_task = task.model_copy(
            update={
                "status": "cancelled",
                "updated_at": datetime.now(timezone.utc),
            }
        )
        store.save_task(updated_task)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(updated_task.model_dump(mode="json")),
            metadata={"team_name": team_name, "task_id": task_id},
        )


class TeamListTool(BaseTool):
    """
    列出所有已持久化团队。
    """

    name = "team_list"
    description = "列出所有已保存的团队。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        store = _build_swarm_store(context)
        teams = []
        for team in store.list_teams():
            teams.append(
                {
                    "team": team.model_dump(mode="json"),
                    "task_count": len(store.list_tasks(team.team_name)),
                }
            )
        return ToolResult(
            tool_name=self.name,
            content=_render_json({"count": len(teams), "teams": teams}),
            metadata={"count": len(teams)},
        )


class TeamGetTool(BaseTool):
    """
    读取单个团队定义。
    """

    name = "team_get"
    description = "读取指定团队定义。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        store = _build_swarm_store(context)
        team = store.load_team(team_name)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(team.model_dump(mode="json")),
            metadata={"team_name": team_name},
        )


class TeamCreateTool(BaseTool):
    """
    创建并落盘一个新的团队定义。
    """

    name = "team_create"
    description = "创建一个新的团队定义并写入 swarm 存储。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        description = str(arguments["description"]).strip()
        if not description:
            raise ValueError("description 不能为空")

        store = _build_swarm_store(context)
        team = SwarmTeam(
            team_name=team_name,
            description=description,
            workspace_dir=str(context.workspace_dir.resolve()),
        )
        store.save_team(team)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(team.model_dump(mode="json")),
            metadata={"team_name": team_name},
        )


class TeamDeleteTool(BaseTool):
    """
    删除团队定义以及其对应的任务目录。
    """

    name = "team_delete"
    description = "删除指定团队定义，并清理该团队的任务目录。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        store = _build_swarm_store(context)

        team = store.load_team(team_name)

        team_file = store._teams_dir / f"{team_name}.json"
        if not team_file.exists():
            raise FileNotFoundError(f"团队不存在：{team_name}")
        team_file.unlink()

        task_dir = store._tasks_dir / team_name
        if task_dir.exists():
            shutil.rmtree(task_dir)

        return ToolResult(
            tool_name=self.name,
            content=_render_json(team.model_dump(mode="json")),
            metadata={"team_name": team_name},
        )


class SendMessageTool(BaseTool):
    """
    向团队邮箱写入消息。
    """

    name = "send_message"
    description = "向指定团队写入一条邮箱消息。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        team_name = _normalize_entity_name(arguments["team_name"], "team_name")
        sender = str(arguments["sender"]).strip()
        recipient = str(arguments["recipient"]).strip()
        subject = str(arguments["subject"]).strip()
        body = str(arguments["body"]).strip()
        if not sender:
            raise ValueError("sender 不能为空")
        if not recipient:
            raise ValueError("recipient 不能为空")
        if not subject:
            raise ValueError("subject 不能为空")
        if not body:
            raise ValueError("body 不能为空")

        metadata_value = arguments.get("metadata") or {}
        if isinstance(metadata_value, str):
            metadata_value = json.loads(metadata_value)
        if not isinstance(metadata_value, dict):
            raise ValueError("metadata 必须是字典或可解析的 JSON 字符串")

        mailbox = _build_mailbox(context)
        message = SwarmMessage(
            message_id=str(arguments.get("message_id") or uuid4()),
            team_name=team_name,
            sender=sender,
            recipient=recipient,
            subject=subject,
            body=body,
            metadata=metadata_value,
        )
        mailbox.send(message)
        return ToolResult(
            tool_name=self.name,
            content=_render_json(message.model_dump(mode="json")),
            metadata={"team_name": team_name, "message_id": message.message_id},
        )


class PowerShellCommandTool(BaseTool):
    """
    在工作区中执行 PowerShell 命令的工具。
    """

    name = "powershell"
    description = "在指定工作目录执行 PowerShell 命令。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        if not context.permission_context.allow_powershell:
            raise PermissionError("当前权限上下文不允许执行 PowerShell 命令。")
        command = str(arguments["command"])
        raw_workdir = str(arguments.get("workdir", "."))
        workdir = normalize_workspace_path(context.workspace_dir, raw_workdir)
        allowed_workdir = ensure_tool_path_allowed(context.permission_context, workdir)
        result = run_powershell_command(command=command, workdir=allowed_workdir)
        return ToolResult(
            tool_name=self.name,
            content=result.stdout.strip(),
            metadata={
                "command": result.command,
                "return_code": result.return_code,
                "workdir": str(allowed_workdir),
                "stderr": result.stderr.strip(),
            },
        )


class PlanUpdateTool(BaseTool):
    """
    更新当前计划步骤的工具。
    """

    name = "update_plan"
    description = "更新当前对话计划步骤。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        steps = arguments.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("update_plan 工具需要非空 steps 列表。")
        normalized_steps = [str(step).strip() for step in steps if str(step).strip()]
        context.plan_steps.clear()
        context.plan_steps.extend(normalized_steps)
        return ToolResult(
            tool_name=self.name,
            content="\n".join(
                f"{index + 1}. {step}" for index, step in enumerate(context.plan_steps)
            ),
            metadata={"count": len(context.plan_steps)},
        )


class McpResourceReadTool(BaseTool):
    """
    读取 MCP 资源文本内容的工具。
    """

    name = "mcp_read"
    description = "按 URI 读取 MCP 资源。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        uri = str(arguments["uri"])
        content = context.mcp_registry.read_resource(uri)
        return ToolResult(
            tool_name=self.name,
            content=content,
            metadata={"uri": uri},
        )


class ListMcpResourcesTool(BaseTool):
    """
    列出当前 MCP 注册中心中已注册资源的工具。
    """

    name = "list_mcp_resources"
    description = "列出当前 MCP 注册中心中的已注册资源。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        resources = [resource.model_dump(mode="json") for resource in context.mcp_registry.list_resources()]
        return ToolResult(
            tool_name=self.name,
            content=_render_json({"count": len(resources), "resources": resources}),
            metadata={"count": len(resources)},
        )


class SleepTool(BaseTool):
    """
    执行真实等待的工具。
    """

    name = "sleep"
    description = "根据给定秒数执行真实等待。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        seconds = float(arguments.get("seconds", 0))
        if seconds < 0:
            raise ValueError("sleep 工具的 seconds 不能小于 0")

        time.sleep(seconds)
        return ToolResult(
            tool_name=self.name,
            content=_render_json({"seconds": seconds, "status": "completed"}),
            metadata={"seconds": seconds},
        )


class BriefTool(BaseTool):
    """
    基于当前工作区、会话和团队存储生成真实摘要文本。
    """

    name = "brief"
    description = "生成当前工作区与会话状态的真实简报文本。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        brief_text = _build_brief_text(context)
        return ToolResult(
            tool_name=self.name,
            content=brief_text,
            metadata={
                "workspace_dir": str(context.workspace_dir.resolve()),
                "session_id": context.settings.runtime.session_id,
                "plan_count": len(context.plan_steps),
            },
        )


class AgentListTool(BaseTool):
    """
    列出当前工作区可见的代理定义。
    """

    name = "agent_list"
    description = "列出当前工作区中真实可见的代理定义。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        lifecycle = SwarmLifecycleService(context.workspace_dir)
        snapshot = lifecycle.agent_snapshot()
        return ToolResult(
            tool_name=self.name,
            content=_render_json(snapshot),
            metadata={"agent_count": snapshot["agent_count"], "workspace_dir": snapshot["workspace_dir"]},
        )


class AgentGetTool(BaseTool):
    """
    读取单个代理定义。
    """

    name = "agent_get"
    description = "读取指定名称的代理定义。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        agent_name = _normalize_entity_name(arguments["agent_name"], "agent_name")
        lifecycle = SwarmLifecycleService(context.workspace_dir)
        definition = lifecycle.get_agent(agent_name)
        payload = definition.model_dump(mode="json")
        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={"agent_name": agent_name},
        )


class AgentCreateTool(BaseTool):
    """
    创建并落盘一个代理定义。
    """

    name = "agent_create"
    description = "创建一个新的代理定义并写入工作区 .funcode/agents 目录。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        agent_name = _normalize_entity_name(arguments["agent_name"], "agent_name")
        role = str(arguments["role"]).strip()
        description = str(arguments["description"]).strip()
        if not role:
            raise ValueError("role 不能为空")
        if not description:
            raise ValueError("description 不能为空")

        lifecycle = SwarmLifecycleService(context.workspace_dir)
        definition = lifecycle.create_agent(
            agent_name=agent_name,
            role=role,
            description=description,
            max_concurrency=int(arguments.get("max_concurrency", 1)),
            source=str(arguments.get("source", "manual")),
            team_name=arguments.get("team_name"),
            tags=arguments.get("tags"),
            runtime_state=arguments.get("runtime_state"),
            metadata=arguments.get("metadata"),
        )
        payload = definition.model_dump(mode="json")
        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={"agent_name": agent_name},
        )


class AgentUpdateTool(BaseTool):
    """
    更新并重新落盘代理定义。
    """

    name = "agent_update"
    description = "更新指定代理定义的角色、说明、并发或运行时状态。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        agent_name = _normalize_entity_name(arguments["agent_name"], "agent_name")
        lifecycle = SwarmLifecycleService(context.workspace_dir)
        update_payload = {
            key: arguments.get(key)
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
            if arguments.get(key) is not None
        }
        definition = lifecycle.update_agent(agent_name, **update_payload)
        payload = definition.model_dump(mode="json")
        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={"agent_name": agent_name},
        )


class AgentDeleteTool(BaseTool):
    """
    删除持久化的代理定义。
    """

    name = "agent_delete"
    description = "删除指定代理定义，并清理对应的 JSON 文件。"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        agent_name = _normalize_entity_name(arguments["agent_name"], "agent_name")
        lifecycle = SwarmLifecycleService(context.workspace_dir)
        definition = lifecycle.delete_agent(agent_name)
        payload = definition.model_dump(mode="json")
        return ToolResult(
            tool_name=self.name,
            content=_render_json(payload),
            metadata={"agent_name": agent_name},
        )
