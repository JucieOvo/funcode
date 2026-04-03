"""
模块名称：agents.lifecycle
功能描述：Agent 运行生命周期（spawn/send_input/wait/resume/close）真实持久化实现。
作者：JucieOvo
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from funcode.agents.models import AgentDefinition, AgentRunMessage, AgentRunRecord, AgentRuntimeState, AgentTaskSpec
from funcode.agents.registry import AgentRegistry
from funcode.config.loader import load_app_settings
from funcode.llm.factory import build_chat_model, build_messages_for_inference
from funcode.mcp.registry import McpRegistry
from funcode.permissions.context import create_permission_context
from funcode.schemas import ExecutionRequest, MessageRecord
from funcode.session.manager import SessionManager
from funcode.session.repository import SessionRepository
from funcode.swarm.mailbox import FileMailbox
from funcode.swarm.models import SwarmMessage, SwarmTask
from funcode.swarm.store import SwarmStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_name(value: Any, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} 不能为空")
    if text in {".", ".."}:
        raise ValueError(f"{label} 非法")
    if Path(text).name != text or ":" in text:
        raise ValueError(f"{label} 非法")
    return text


def _non_empty_text(value: Any, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} 不能为空")
    return text


def _parse_mapping_value(raw_value: Any | None) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("metadata 必须是对象")
        return dict(parsed)
    raise ValueError("metadata 必须是字典、JSON 字符串或 None")


class AgentLifecycleService:
    _ACTIVE_STATUSES: tuple[str, ...] = ("queued", "running")
    _TERMINAL_STATUSES: tuple[str, ...] = ("waiting", "completed", "failed", "interrupted", "closed", "cancelled")

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()
        self.runtime_dir = self.workspace_dir / ".funcode"
        self.agent_dir = self.runtime_dir / "agents"
        self.run_dir = self.agent_dir / "runs"
        self.swarm_dir = self.runtime_dir / "swarm"
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.swarm_dir.mkdir(parents=True, exist_ok=True)

    def _package_src_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _worker_module_name(self) -> str:
        return "funcode.agents.worker"

    def _extract_background_pid(self, record: AgentRunRecord) -> int | None:
        background = record.metadata.get("background", {})
        if not isinstance(background, dict):
            return None
        pid_value = background.get("pid")
        if pid_value is None:
            return None
        try:
            parsed_pid = int(pid_value)
        except (TypeError, ValueError):
            return None
        return parsed_pid if parsed_pid > 0 else None

    def _build_worker_command(
        self,
        *,
        run_id: str,
        max_turns: int,
        system_prompt: str | None,
        graph_name: str,
        output_format: str,
    ) -> list[str]:
        command = [
            sys.executable,
            "-m",
            self._worker_module_name(),
            "--workspace-dir",
            str(self.workspace_dir),
            "--run-id",
            run_id,
            "--max-turns",
            str(max_turns),
            "--graph-name",
            graph_name,
            "--output-format",
            output_format,
        ]
        if system_prompt is not None and system_prompt.strip():
            command.extend(["--system-prompt", system_prompt.strip()])
        return command

    def _build_worker_env(self) -> dict[str, str]:
        env = dict(os.environ)
        src_dir = str(self._package_src_dir())
        existing_pythonpath = env.get("PYTHONPATH", "").strip()
        if existing_pythonpath:
            pythonpath_items = [item for item in existing_pythonpath.split(os.pathsep) if item]
            if src_dir not in pythonpath_items:
                pythonpath_items.insert(0, src_dir)
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_items)
        else:
            env["PYTHONPATH"] = src_dir
        return env

    @staticmethod
    def _default_run_context() -> dict[str, Any]:
        return {
            "permission_snapshot": {},
            "mcp_resources": [],
            "agent_snapshots": [],
            "team_snapshots": [],
            "mailbox_snapshot": {},
            "tool_scope": {
                "mode": "inherit",
                "allowed_tools": [],
                "source": "default",
            },
            "worktree_path": None,
            "fork_context": {},
            "use_exact_tools": False,
            "replacement_state": {
                "entries": [],
                "source": "default",
                "updated_at": _utc_now().isoformat(),
            },
            "transcript_state": {
                "messages": [],
                "content_replacements": [],
                "source": "default",
                "updated_at": _utc_now().isoformat(),
            },
            "captured_at": _utc_now().isoformat(),
            "source": "default",
        }

    @staticmethod
    def _coerce_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {}

    @staticmethod
    def _coerce_mapping_list(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.append(dict(item))
        return result

    @staticmethod
    def _coerce_bool(value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default

    @staticmethod
    def _coerce_text_list(value: Any) -> list[str]:
        raw_items: list[Any]
        if isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        elif isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif value is None:
            raw_items = []
        else:
            raw_items = [value]
        normalized_items: list[str] = []
        for raw_item in raw_items:
            text = str(raw_item).strip()
            if not text:
                continue
            if text not in normalized_items:
                normalized_items.append(text)
        return normalized_items

    @staticmethod
    def _normalize_transcript_messages(raw_messages: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_messages, list):
            return []
        normalized: list[dict[str, Any]] = []
        for message in raw_messages:
            if not isinstance(message, dict):
                continue
            role_text = str(message.get("role") or "").strip()
            content_text = str(message.get("content") or "").strip()
            if not role_text or not content_text:
                continue
            normalized.append(
                {
                    "role": role_text,
                    "content": content_text,
                    "message_id": str(message.get("message_id") or message.get("messageId") or "").strip() or None,
                    "source": str(message.get("source") or "").strip() or None,
                    "created_at": str(message.get("created_at") or message.get("createdAt") or "").strip() or None,
                }
            )
        return normalized

    @staticmethod
    def _normalize_content_replacements(raw_replacements: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_replacements, list):
            return []
        replacements: list[dict[str, Any]] = []
        for item in raw_replacements:
            if isinstance(item, dict):
                replacements.append(dict(item))
        return replacements

    @staticmethod
    def _normalize_replacement_state(raw_state: Any) -> dict[str, Any]:
        if isinstance(raw_state, str):
            text = raw_state.strip()
            if not text:
                return {"entries": [], "source": "empty_string", "updated_at": _utc_now().isoformat()}
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("replacement_state 如果是 JSON 字符串，必须解析为对象")
            raw_state = parsed
        if not isinstance(raw_state, dict):
            return {"entries": [], "source": "default", "updated_at": _utc_now().isoformat()}
        entries = AgentLifecycleService._normalize_content_replacements(raw_state.get("entries"))
        return {
            "entries": entries,
            "source": str(raw_state.get("source") or "metadata").strip() or "metadata",
            "updated_at": str(raw_state.get("updated_at") or raw_state.get("updatedAt") or _utc_now().isoformat()),
        }

    @staticmethod
    def _replacement_state_has_content(state: dict[str, Any]) -> bool:
        normalized = AgentLifecycleService._normalize_replacement_state(state)
        return bool(normalized.get("entries"))

    @staticmethod
    def _normalize_transcript_state(raw_state: Any) -> dict[str, Any]:
        if isinstance(raw_state, str):
            text = raw_state.strip()
            if not text:
                return {
                    "messages": [],
                    "content_replacements": [],
                    "source": "empty_string",
                    "updated_at": _utc_now().isoformat(),
                }
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("transcript_state 如果是 JSON 字符串，必须解析为对象")
            raw_state = parsed
        if not isinstance(raw_state, dict):
            return {
                "messages": [],
                "content_replacements": [],
                "source": "default",
                "updated_at": _utc_now().isoformat(),
            }
        messages = AgentLifecycleService._normalize_transcript_messages(raw_state.get("messages"))
        content_replacements = AgentLifecycleService._normalize_content_replacements(
            raw_state.get("content_replacements", raw_state.get("contentReplacements"))
        )
        return {
            "messages": messages,
            "content_replacements": content_replacements,
            "source": str(raw_state.get("source") or "metadata").strip() or "metadata",
            "updated_at": str(raw_state.get("updated_at") or raw_state.get("updatedAt") or _utc_now().isoformat()),
        }

    @staticmethod
    def _transcript_state_has_content(state: dict[str, Any]) -> bool:
        normalized = AgentLifecycleService._normalize_transcript_state(state)
        return bool(normalized.get("messages")) or bool(normalized.get("content_replacements"))

    @staticmethod
    def _pick_first_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in source:
                return source.get(key)
        return None

    @staticmethod
    def _normalize_optional_path_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return str(Path(text).expanduser().resolve())

    @staticmethod
    def _normalize_tool_scope(raw_scope: Any) -> dict[str, Any]:
        scope_mapping = dict(raw_scope) if isinstance(raw_scope, dict) else {}
        if isinstance(raw_scope, (list, tuple, set, str)):
            scope_mapping = {
                "allowed_tools": AgentLifecycleService._coerce_text_list(raw_scope),
                "source": "scope_list",
            }
        allowed_tools = AgentLifecycleService._coerce_text_list(
            AgentLifecycleService._pick_first_value(scope_mapping, ("allowed_tools", "allowedTools", "command", "tools"))  # type: ignore[arg-type]
        )
        requested_mode = str(scope_mapping.get("mode") or "").strip().lower()
        if requested_mode not in {"inherit", "exact"}:
            requested_mode = "exact" if allowed_tools else "inherit"
        source = str(scope_mapping.get("source") or ("explicit" if allowed_tools else "default")).strip() or "default"
        return {
            "mode": requested_mode,
            "allowed_tools": allowed_tools,
            "source": source,
        }

    @staticmethod
    def _tool_scope_is_effective(tool_scope: dict[str, Any]) -> bool:
        normalized_scope = AgentLifecycleService._normalize_tool_scope(tool_scope)
        return normalized_scope["mode"] == "exact" or bool(normalized_scope["allowed_tools"])

    @staticmethod
    def _normalize_fork_context(raw_context: Any) -> dict[str, Any]:
        if isinstance(raw_context, str):
            text = raw_context.strip()
            if not text:
                return {}
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("fork_context 必须是 JSON 对象")
            raw_context = parsed
        if not isinstance(raw_context, dict):
            return {}
        normalized_context: dict[str, Any] = dict(raw_context)
        parent_run_id = str(
            AgentLifecycleService._pick_first_value(normalized_context, ("parent_run_id", "parentRunId")) or ""
        ).strip()
        parent_session_id = str(
            AgentLifecycleService._pick_first_value(normalized_context, ("parent_session_id", "parentSessionId")) or ""
        ).strip()
        inherit_parent_messages = AgentLifecycleService._coerce_bool(
            AgentLifecycleService._pick_first_value(
                normalized_context,
                ("inherit_parent_messages", "inheritParentMessages"),
            ),
            default=bool(parent_run_id),
        )
        message_snapshots: list[dict[str, Any]] = []
        raw_messages = AgentLifecycleService._pick_first_value(normalized_context, ("messages", "forkContextMessages"))
        if isinstance(raw_messages, list):
            for message in raw_messages:
                if not isinstance(message, dict):
                    continue
                role_text = str(message.get("role") or "").strip()
                content_text = str(message.get("content") or "").strip()
                if not role_text or not content_text:
                    continue
                message_snapshots.append(
                    {
                        "role": role_text,
                        "content": content_text,
                        "message_id": str(message.get("message_id") or message.get("messageId") or "").strip() or None,
                    }
                )
        return {
            "parent_run_id": parent_run_id or None,
            "parent_session_id": parent_session_id or None,
            "inherit_parent_messages": inherit_parent_messages,
            "messages": message_snapshots,
            "source": str(normalized_context.get("source") or "metadata").strip() or "metadata",
            "captured_at": str(normalized_context.get("captured_at") or normalized_context.get("capturedAt") or _utc_now().isoformat()),
        }

    @staticmethod
    def _parse_fork_context_input(raw_context: Any) -> tuple[dict[str, Any], bool]:
        """
        解析 fork_context 原始输入并保留“显式传入”语义。

        :param raw_context: fork_context 原始输入（dict / JSON 字符串 / None）。
        :return: (解析后的映射, 是否为显式输入)。
        :raises ValueError: 输入字符串不是 JSON 对象时触发。
        """

        if raw_context is None:
            return {}, False
        if isinstance(raw_context, dict):
            return dict(raw_context), True
        if isinstance(raw_context, str):
            text = raw_context.strip()
            if not text:
                return {}, True
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("fork_context 必须是 JSON 对象")
            return dict(parsed), True
        raise ValueError("fork_context 必须是字典、JSON 字符串或 None")

    @staticmethod
    def _mapping_has_any_key(mapping: dict[str, Any], keys: tuple[str, ...]) -> bool:
        """
        判断映射中是否包含候选键中的任意一个。

        :param mapping: 待检测映射。
        :param keys: 候选键集合。
        :return: 是否命中任意键。
        """

        return any(key in mapping for key in keys)

    def _resolve_execution_workspace_dir(self, run_context: dict[str, Any]) -> Path:
        normalized_context = self._normalize_run_context(run_context)
        worktree_path_text = normalized_context.get("worktree_path")
        if worktree_path_text is None:
            return self.workspace_dir
        candidate_path = Path(str(worktree_path_text)).resolve()
        if not candidate_path.exists() or not candidate_path.is_dir():
            raise FileNotFoundError(f"worktree_path 不存在或不可访问：{candidate_path}")
        return candidate_path

    def _normalize_run_context(self, raw_context: Any) -> dict[str, Any]:
        default_context = self._default_run_context()
        if not isinstance(raw_context, dict):
            return default_context
        tool_scope = self._normalize_tool_scope(raw_context.get("tool_scope", raw_context.get("toolScope")))
        fork_context = self._normalize_fork_context(raw_context.get("fork_context", raw_context.get("forkContext")))
        worktree_path = self._normalize_optional_path_text(raw_context.get("worktree_path", raw_context.get("worktreePath")))
        use_exact_tools = self._coerce_bool(
            raw_context.get("use_exact_tools", raw_context.get("useExactTools")),
            default=False,
        )
        replacement_state = self._normalize_replacement_state(
            raw_context.get("replacement_state", raw_context.get("replacementState"))
        )
        transcript_state = self._normalize_transcript_state(
            raw_context.get("transcript_state", raw_context.get("transcriptState"))
        )
        normalized: dict[str, Any] = {
            "permission_snapshot": self._coerce_mapping(raw_context.get("permission_snapshot")),
            "mcp_resources": self._coerce_mapping_list(raw_context.get("mcp_resources")),
            "agent_snapshots": self._coerce_mapping_list(raw_context.get("agent_snapshots")),
            "team_snapshots": self._coerce_mapping_list(raw_context.get("team_snapshots")),
            "mailbox_snapshot": self._coerce_mapping(raw_context.get("mailbox_snapshot")),
            "tool_scope": tool_scope,
            "worktree_path": worktree_path,
            "fork_context": fork_context,
            "use_exact_tools": use_exact_tools,
            "replacement_state": replacement_state,
            "transcript_state": transcript_state,
            "captured_at": str(raw_context.get("captured_at") or default_context["captured_at"]),
            "source": str(raw_context.get("source") or default_context["source"]),
        }
        return normalized

    def _extract_run_context(self, record: AgentRunRecord) -> dict[str, Any]:
        return self._normalize_run_context(record.metadata.get("run_context"))

    def _build_workspace_run_context(self, *, settings: Any | None = None, context_workspace_dir: Path | None = None) -> dict[str, Any]:
        from funcode.runtime.swarm_lifecycle import SwarmLifecycleService

        snapshot_workspace_dir = context_workspace_dir.resolve() if context_workspace_dir is not None else self.workspace_dir
        if settings is None:
            settings = load_app_settings(
                Namespace(
                    command="run",
                    prompt="context_snapshot",
                    system_prompt=None,
                    graph_name="main",
                    output_format="text",
                    model=None,
                    api_key=None,
                    base_url=None,
                    reasoning_effort=None,
                    cwd=str(snapshot_workspace_dir),
                    session_id=None,
                    max_turns=32,
                    stream=False,
                    debug=False,
                )
            )
        permission_context = create_permission_context(settings)
        mcp_registry = McpRegistry()
        mcp_registry.discover_workspace_resources(snapshot_workspace_dir)
        mcp_resources = [resource.model_dump(mode="json") for resource in mcp_registry.list_resources()]
        swarm_snapshot = SwarmLifecycleService(self.workspace_dir).snapshot()
        return self._normalize_run_context(
            {
                "permission_snapshot": permission_context.model_dump(mode="json"),
                "mcp_resources": mcp_resources,
                "agent_snapshots": list(swarm_snapshot.get("agent_snapshots") or []),
                "team_snapshots": list(swarm_snapshot.get("team_snapshots") or []),
                "mailbox_snapshot": dict(swarm_snapshot.get("mailbox_snapshot") or {}),
                "captured_at": _utc_now().isoformat(),
                "source": "workspace_runtime_snapshot",
            }
        )

    def _merge_run_context(self, preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        normalized_preferred = self._normalize_run_context(preferred)
        normalized_fallback = self._normalize_run_context(fallback)
        resolved: dict[str, Any] = {}
        for key in ("permission_snapshot", "mailbox_snapshot"):
            preferred_mapping = self._coerce_mapping(normalized_preferred.get(key))
            resolved[key] = preferred_mapping if preferred_mapping else self._coerce_mapping(normalized_fallback.get(key))
        for key in ("mcp_resources", "agent_snapshots", "team_snapshots"):
            preferred_list = self._coerce_mapping_list(normalized_preferred.get(key))
            resolved[key] = preferred_list if preferred_list else self._coerce_mapping_list(normalized_fallback.get(key))
        preferred_tool_scope = self._normalize_tool_scope(normalized_preferred.get("tool_scope"))
        fallback_tool_scope = self._normalize_tool_scope(normalized_fallback.get("tool_scope"))
        resolved["tool_scope"] = (
            preferred_tool_scope if self._tool_scope_is_effective(preferred_tool_scope) else fallback_tool_scope
        )
        preferred_worktree_path = self._normalize_optional_path_text(normalized_preferred.get("worktree_path"))
        fallback_worktree_path = self._normalize_optional_path_text(normalized_fallback.get("worktree_path"))
        resolved["worktree_path"] = preferred_worktree_path if preferred_worktree_path is not None else fallback_worktree_path
        preferred_fork_context = self._normalize_fork_context(normalized_preferred.get("fork_context"))
        fallback_fork_context = self._normalize_fork_context(normalized_fallback.get("fork_context"))
        resolved["fork_context"] = preferred_fork_context if preferred_fork_context else fallback_fork_context
        resolved["use_exact_tools"] = self._coerce_bool(
            normalized_preferred.get("use_exact_tools"),
            default=self._coerce_bool(normalized_fallback.get("use_exact_tools"), default=False),
        )
        preferred_replacement_state = self._normalize_replacement_state(normalized_preferred.get("replacement_state"))
        fallback_replacement_state = self._normalize_replacement_state(normalized_fallback.get("replacement_state"))
        resolved["replacement_state"] = (
            preferred_replacement_state
            if self._replacement_state_has_content(preferred_replacement_state)
            else fallback_replacement_state
        )
        preferred_transcript_state = self._normalize_transcript_state(normalized_preferred.get("transcript_state"))
        fallback_transcript_state = self._normalize_transcript_state(normalized_fallback.get("transcript_state"))
        resolved["transcript_state"] = (
            preferred_transcript_state
            if self._transcript_state_has_content(preferred_transcript_state)
            else fallback_transcript_state
        )
        resolved["captured_at"] = str(normalized_preferred.get("captured_at") or normalized_fallback.get("captured_at") or _utc_now().isoformat())
        resolved["source"] = str(normalized_preferred.get("source") or normalized_fallback.get("source") or "merged")
        return resolved

    def _ensure_run_context(
        self,
        record: AgentRunRecord,
        *,
        settings: Any | None = None,
        source: str,
    ) -> tuple[AgentRunRecord, dict[str, Any]]:
        existing_context = self._extract_run_context(record)
        context_workspace_dir = self._resolve_execution_workspace_dir(existing_context)
        if settings is None:
            workspace_context = self._build_workspace_run_context(context_workspace_dir=context_workspace_dir)
        else:
            settings_workspace_dir = getattr(getattr(settings, "runtime", object()), "workspace_dir", context_workspace_dir)
            workspace_context = self._build_workspace_run_context(
                settings=settings,
                context_workspace_dir=Path(str(settings_workspace_dir)).resolve(),
            )
        merged_context = self._merge_run_context(existing_context, workspace_context)
        if merged_context == existing_context:
            return record, merged_context
        updated_record = record.model_copy(
            update={
                "metadata": {
                    **record.metadata,
                    "run_context": merged_context,
                    "run_context_updated_by": source,
                    "run_context_updated_at": _utc_now().isoformat(),
                }
            }
        )
        persisted_record = self._save_run(updated_record)
        return persisted_record, merged_context

    def _build_effective_system_prompt(self, *, run_context: dict[str, Any], system_prompt: str | None) -> str | None:
        base_prompt = (system_prompt or "").strip()
        tool_scope = self._normalize_tool_scope(run_context.get("tool_scope"))
        allowed_tools = self._coerce_text_list(tool_scope.get("allowed_tools"))
        worktree_path = self._normalize_optional_path_text(run_context.get("worktree_path"))
        use_exact_tools = self._coerce_bool(run_context.get("use_exact_tools"), default=False)
        scope_lines: list[str] = []
        if allowed_tools:
            scope_lines.append(f"run 级 allowedTools: {', '.join(allowed_tools)}")
        if tool_scope.get("mode") == "exact" or use_exact_tools:
            scope_lines.append("run 级 use_exact_tools 已启用：仅允许使用 allowedTools 中声明的工具范围。")
        if worktree_path is not None:
            scope_lines.append(f"run 级 worktree_path: {worktree_path}")
        if not scope_lines:
            return system_prompt
        policy_block = "\n".join(scope_lines)
        if base_prompt:
            return f"{base_prompt}\n\n{policy_block}"
        return policy_block

    def _build_fork_message_history(self, *, record: AgentRunRecord, run_context: dict[str, Any]) -> list[dict[str, Any]]:
        fork_context = self._normalize_fork_context(run_context.get("fork_context"))
        explicit_messages = fork_context.get("messages")
        if isinstance(explicit_messages, list) and explicit_messages:
            normalized_messages: list[dict[str, Any]] = []
            for message in explicit_messages:
                if not isinstance(message, dict):
                    continue
                role_text = str(message.get("role") or "").strip()
                content_text = str(message.get("content") or "").strip()
                if not role_text or not content_text:
                    continue
                normalized_messages.append({"role": role_text, "content": content_text})
            if normalized_messages:
                return normalized_messages
        parent_run_id = str(fork_context.get("parent_run_id") or record.parent_run_id or "").strip()
        if not parent_run_id:
            return []
        if not self._coerce_bool(fork_context.get("inherit_parent_messages"), default=True):
            return []
        parent_record = self._load_run(parent_run_id)
        inherited_messages: list[dict[str, Any]] = []
        for message in parent_record.messages:
            if message.role not in {"system", "user", "assistant"}:
                continue
            content_text = str(message.content).strip()
            if not content_text:
                continue
            inherited_messages.append({"role": message.role, "content": content_text})
        return inherited_messages

    def _build_transcript_message_history(self, *, run_context: dict[str, Any]) -> list[dict[str, Any]]:
        transcript_state = self._normalize_transcript_state(run_context.get("transcript_state"))
        transcript_messages = transcript_state.get("messages")
        if not isinstance(transcript_messages, list):
            return []
        history: list[dict[str, Any]] = []
        for message in transcript_messages:
            if not isinstance(message, dict):
                continue
            role_text = str(message.get("role") or "").strip()
            content_text = str(message.get("content") or "").strip()
            if not role_text or not content_text:
                continue
            history.append({"role": role_text, "content": content_text})
        return history

    def _append_transcript_turn(
        self,
        *,
        run_context: dict[str, Any],
        run_id: str,
        session_id: str | None,
        user_input: str,
        assistant_output: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        transcript_state = self._normalize_transcript_state(run_context.get("transcript_state"))
        replacement_state = self._normalize_replacement_state(run_context.get("replacement_state"))
        existing_messages = self._normalize_transcript_messages(transcript_state.get("messages"))
        content_replacements = self._normalize_content_replacements(transcript_state.get("content_replacements"))

        user_message_id = uuid4().hex
        assistant_message_id = uuid4().hex
        now_text = _utc_now().isoformat()
        updated_messages = [
            *existing_messages,
            {
                "role": "user",
                "content": user_input,
                "message_id": user_message_id,
                "source": "wait",
                "created_at": now_text,
            },
            {
                "role": "assistant",
                "content": assistant_output,
                "message_id": assistant_message_id,
                "source": "wait",
                "created_at": now_text,
            },
        ]

        replacement_entry = {
            "replacement_id": uuid4().hex,
            "run_id": run_id,
            "session_id": session_id,
            "assistant_message_id": assistant_message_id,
            "source": "wait",
            "created_at": now_text,
            "preview": assistant_output[:200],
        }
        updated_replacement_entries = [
            *self._normalize_content_replacements(replacement_state.get("entries")),
            replacement_entry,
        ]
        updated_content_replacements = [*content_replacements, replacement_entry]

        updated_transcript_state = self._normalize_transcript_state(
            {
                **transcript_state,
                "messages": updated_messages,
                "content_replacements": updated_content_replacements,
                "updated_at": now_text,
                "source": "wait",
            }
        )
        updated_replacement_state = self._normalize_replacement_state(
            {
                **replacement_state,
                "entries": updated_replacement_entries,
                "updated_at": now_text,
                "source": "wait",
            }
        )
        updated_run_context = self._normalize_run_context(
            {
                **run_context,
                "transcript_state": updated_transcript_state,
                "replacement_state": updated_replacement_state,
                "captured_at": now_text,
                "source": "wait",
            }
        )
        return updated_run_context, updated_transcript_state, updated_replacement_state

    def _terminate_background_process(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return completed.returncode == 0
        try:
            os.kill(pid, 15)
            return True
        except OSError:
            return False

    def _registry(self) -> AgentRegistry:
        return AgentRegistry(workspace_dir=self.workspace_dir)

    def _store(self) -> SwarmStore:
        return SwarmStore(self.swarm_dir)

    def _mailbox(self) -> FileMailbox:
        return FileMailbox(self.swarm_dir / "mailbox.jsonl")

    def _agent_file(self, agent_name: str) -> Path:
        return self.agent_dir / f"{_normalize_name(agent_name, 'agent_name')}.json"

    def _run_file(self, run_id: str) -> Path:
        return self.run_dir / f"{_normalize_name(run_id, 'run_id')}.json"

    def _write_text_atomically(self, target_path: Path, content: str) -> None:
        """
        使用同目录临时文件 + 原子替换写入文本，避免写入中断导致目标文件为空或半截内容。

        :param target_path: 目标文件路径。
        :param content: 需要写入的完整文本内容。
        """

        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f".{target_path.name}.{uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _load_run(self, run_id: str) -> AgentRunRecord:
        target_path = self._run_file(run_id)
        if not target_path.exists():
            raise FileNotFoundError(f"agent run 不存在：{run_id}")
        return AgentRunRecord.model_validate_json(target_path.read_text(encoding="utf-8"))

    def _load_run_record_safely(self, run_file: Path) -> AgentRunRecord | None:
        """
        安全读取单个 run 文件。
        对空文件、半写入文件、损坏 JSON 文件执行跳过，避免影响列表与状态同步流程。

        :param run_file: run 文件路径。
        :return: 成功解析时返回记录，否则返回 None。
        """

        try:
            payload = run_file.read_text(encoding="utf-8")
        except OSError:
            return None
        if not payload.strip():
            return None
        try:
            return AgentRunRecord.model_validate_json(payload)
        except ValueError:
            return None

    def _save_run(self, record: AgentRunRecord) -> AgentRunRecord:
        target_path = self._run_file(record.run_id)
        persisted_record = record.model_copy(update={"updated_at": _utc_now()})
        serialized_record = json.dumps(
            persisted_record.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        self._write_text_atomically(target_path, serialized_record)
        return persisted_record

    def _append_run_message(self, record: AgentRunRecord, *, role: str, content: str, metadata: dict[str, Any] | None = None) -> AgentRunRecord:
        new_message = AgentRunMessage(message_id=uuid4().hex, role=role, content=_non_empty_text(content, "content"), metadata=metadata or {})  # type: ignore[arg-type]
        return record.model_copy(update={"messages": [*record.messages, new_message]})

    def _emit_mailbox_event(self, *, team_name: str | None, recipient: str, subject: str, body: str, metadata: dict[str, Any] | None = None) -> None:
        if team_name is None or not str(team_name).strip():
            return
        self._mailbox().send(
            SwarmMessage(
                message_id=uuid4().hex,
                team_name=str(team_name).strip(),
                sender="agent-lifecycle",
                recipient=recipient,
                subject=subject,
                body=body,
                message_type="update",
                metadata=metadata or {},
            )
        )

    def _persist_agent_definition(self, definition: AgentDefinition) -> AgentDefinition:
        target_path = self._agent_file(definition.agent_name)
        target_path.write_text(json.dumps(definition.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return AgentDefinition.model_validate_json(target_path.read_text(encoding="utf-8"))

    def _sync_agent_runtime_state(self, agent_name: str) -> AgentDefinition:
        normalized_agent_name = _normalize_name(agent_name, "agent_name")
        base_definition = self._registry().get(normalized_agent_name)
        runs = self.list_runs(agent_name=normalized_agent_name)
        active_statuses = set(self._ACTIVE_STATUSES)
        active_run = next((item for item in runs if item.status in active_statuses), None)
        completed_count = sum(
            1
            for item in runs
            if item.status in {"waiting", "completed"}
            or (item.status == "closed" and item.latest_output is not None and item.last_error_message is None)
        )
        failed_count = sum(1 for item in runs if item.status == "failed")
        if active_run is not None:
            runtime_status = "running" if active_run.status == "running" else "pending"
        elif runs:
            latest = runs[0]
            if completed_count > 0 and failed_count == 0:
                runtime_status = "completed"
            elif latest.status == "failed" or (failed_count > 0 and completed_count == 0):
                runtime_status = "failed"
            elif latest.status in {"interrupted", "cancelled"}:
                runtime_status = "cancelled"
            elif latest.status == "closed":
                runtime_status = (
                    "completed"
                    if latest.latest_output is not None and latest.last_error_message is None
                    else "cancelled"
                )
            elif latest.latest_output is not None and latest.last_error_message is None:
                runtime_status = "completed"
            else:
                runtime_status = "pending"
        else:
            runtime_status = "pending"
        last_seen_at = max((item.updated_at for item in runs), default=base_definition.runtime_state.last_seen_at if base_definition.runtime_state else None)
        runtime_state = AgentRuntimeState(
            status=runtime_status,  # type: ignore[arg-type]
            team_name=active_run.team_name if active_run is not None else base_definition.team_name,
            current_task_id=active_run.task.task_id if active_run is not None else None,
            last_task_id=runs[0].task.task_id if runs else (base_definition.runtime_state.last_task_id if base_definition.runtime_state else None),
            task_count=len(runs),
            completed_task_count=completed_count,
            failed_task_count=failed_count,
            last_seen_at=last_seen_at,
            metadata={
                "source": "agent_runs",
                "open_run_count": sum(1 for item in runs if item.status in active_statuses),
                "latest_run_id": runs[0].run_id if runs else None,
            },
        )
        return self._persist_agent_definition(base_definition.model_copy(update={"runtime_state": runtime_state}))

    def _ensure_task_for_run(self, record: AgentRunRecord) -> None:
        if record.team_name is None:
            return
        store = self._store()
        try:
            store.load_team(record.team_name)
        except FileNotFoundError:
            return
        try:
            store.load_task(record.team_name, record.task.task_id)
            return
        except FileNotFoundError:
            pass
        task = SwarmTask(
            task_id=record.task.task_id,
            team_name=record.team_name,
            subject=record.task.title,
            detail=record.task.instruction,
            owner=record.agent_name,
            status="pending",
            priority=record.task.priority,
            metadata={**record.task.metadata, "agent_run_id": record.run_id, "expected_output": record.task.expected_output},
        )
        store.save_task(task)

    def _update_swarm_task_status(self, record: AgentRunRecord, status: str, *, detail_suffix: str | None = None) -> None:
        if record.team_name is None:
            return
        try:
            task = self._store().load_task(record.team_name, record.task.task_id)
        except FileNotFoundError:
            return
        detail_value = task.detail if not detail_suffix else f"{task.detail}\n\n{detail_suffix}".strip()
        update_payload: dict[str, Any] = {
            "status": status,
            "owner": record.agent_name,
            "detail": detail_value,
            "attempt_count": task.attempt_count + (1 if status == "in_progress" else 0),
            "metadata": {
                **task.metadata,
                "agent_run_id": record.run_id,
                "agent_session_id": record.session_id,
                "agent_run_status": record.status,
            },
        }
        if status == "in_progress":
            update_payload["started_at"] = task.started_at or _utc_now()
            update_payload["finished_at"] = None
        if status in {"completed", "failed", "cancelled"}:
            update_payload["finished_at"] = _utc_now()
        if status == "completed":
            update_payload["metadata"]["latest_output"] = record.latest_output
        if status == "failed":
            update_payload["metadata"]["last_error_message"] = record.last_error_message
        self._store().save_task(task.model_copy(update=update_payload))

    def _assert_swarm_execution_gate(self, *, record: AgentRunRecord, source: str) -> AgentRunRecord:
        """
        在真正执行 run 前校验 swarm 编排门控（依赖与并发）。
        :param record: 待执行的 run 记录。
        :param source: 触发来源（wait/start_background）。
        :return: 可执行时返回最新 run 记录。
        :raises ValueError: 不可执行时抛错，并写入真实阻塞状态。
        """

        if record.team_name is None:
            return record

        from funcode.runtime.swarm_lifecycle import SwarmLifecycleService

        lifecycle = SwarmLifecycleService(self.workspace_dir)
        gate = lifecycle.check_task_execution_gate(
            team_name=record.team_name,
            task_id=record.task.task_id,
            agent_name=record.agent_name,
            current_run_id=record.run_id,
        )
        if gate.get("executable"):
            return self._load_run(record.run_id)

        blocked_reason = str(gate.get("reason") or "execution_blocked")
        blocked_detail = (
            f"run 执行被编排门控阻塞：reason={blocked_reason} | "
            f"deps={gate.get('unsatisfied_dependencies')} | "
            f"active={gate.get('owner_active_runs')}/{gate.get('owner_max_concurrency')}"
        )
        blocked_record = self._append_run_message(
            record,
            role="event",
            content=blocked_detail,
            metadata={"source": source, "execution_gate": gate},
        ).model_copy(
            update={
                "status": "queued",
                "last_error_message": f"execution_blocked:{blocked_reason}",
            }
        )
        persisted_record = self._save_run(blocked_record)
        self._update_swarm_task_status(
            persisted_record,
            "blocked",
            detail_suffix=blocked_detail,
        )
        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run blocked: {persisted_record.run_id}",
            body=blocked_detail,
            metadata={
                "run_id": persisted_record.run_id,
                "status": persisted_record.status,
                "execution_gate": gate,
            },
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        raise ValueError(blocked_detail)

    def list_runs(self, *, agent_name: str | None = None, team_name: str | None = None, status: str | None = None) -> list[AgentRunRecord]:
        records: list[AgentRunRecord] = []
        for run_file in sorted(self.run_dir.glob("*.json")):
            if not run_file.is_file():
                continue
            record = self._load_run_record_safely(run_file)
            if record is None:
                continue
            if agent_name is not None and record.agent_name != agent_name:
                continue
            if team_name is not None and record.team_name != team_name:
                continue
            if status is not None and record.status != status:
                continue
            records.append(record)
        return sorted(records, key=lambda item: (item.updated_at, item.created_at, item.run_id), reverse=True)

    def get_run(self, *, run_id: str) -> AgentRunRecord:
        return self._load_run(run_id)

    def start_background(
        self,
        *,
        run_id: str,
        max_turns: int = 32,
        system_prompt: str | None = None,
        graph_name: str = "main",
        output_format: str = "text",
    ) -> AgentRunRecord:
        record = self._load_run(run_id)
        if record.status in {"closed", "cancelled", "interrupted"}:
            raise ValueError(f"当前运行已结束，不能启动后台执行：{record.run_id}")
        if record.status == "running":
            return record
        pending_messages = [message for message in record.messages if message.role == "user" and message.consumed_at is None]
        if not pending_messages:
            raise ValueError(f"当前运行没有待消费的用户输入：{record.run_id}")

        record = self._assert_swarm_execution_gate(record=record, source="start_background")
        record, run_context = self._ensure_run_context(record, source="start_background")
        execution_workspace_dir = self._resolve_execution_workspace_dir(run_context)
        launch_command = self._build_worker_command(
            run_id=record.run_id,
            max_turns=max_turns,
            system_prompt=system_prompt,
            graph_name=graph_name,
            output_format=output_format,
        )
        launch_env = self._build_worker_env()

        popen_kwargs: dict[str, Any] = {
            "cwd": str(execution_workspace_dir),
            "env": launch_env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        launched_process = subprocess.Popen(launch_command, **popen_kwargs)
        background_metadata = {
            "mode": "subprocess",
            "pid": launched_process.pid,
            "launch_command": launch_command,
            "launched_at": _utc_now().isoformat(),
            "max_turns": max_turns,
            "graph_name": graph_name,
            "output_format": output_format,
            "system_prompt": system_prompt,
            "execution_cwd": str(execution_workspace_dir),
            "tool_scope": self._normalize_tool_scope(run_context.get("tool_scope")),
            "use_exact_tools": self._coerce_bool(run_context.get("use_exact_tools"), default=False),
            "replacement_state": self._normalize_replacement_state(run_context.get("replacement_state")),
            "transcript_state": self._normalize_transcript_state(run_context.get("transcript_state")),
        }
        queued_record = self._append_run_message(
            record,
            role="event",
            content=f"后台执行已启动，pid={launched_process.pid}",
            metadata={"source": "start_background", "pid": launched_process.pid},
        ).model_copy(
            update={
                "status": "queued",
                "last_error_message": None,
                "metadata": {
                    **record.metadata,
                    "background": background_metadata,
                },
            }
        )
        persisted_record = self._save_run(queued_record)
        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run background-started: {persisted_record.run_id}",
            body=f"后台执行已启动，pid={launched_process.pid}",
            metadata={"run_id": persisted_record.run_id, "pid": launched_process.pid, "status": persisted_record.status},
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        return self._load_run(run_id)

    def interrupt(self, *, run_id: str, reason: str | None = None) -> AgentRunRecord:
        record = self._load_run(run_id)
        if record.status in {"interrupted", "closed", "cancelled"}:
            return record
        normalized_reason = str(reason).strip() if isinstance(reason, str) and reason.strip() else "manual_interrupt"

        terminated = False
        background_pid = self._extract_background_pid(record)
        if background_pid is not None:
            terminated = self._terminate_background_process(background_pid)

        interrupted_record = self._append_run_message(
            record,
            role="event",
            content=f"run 已中断，原因：{normalized_reason}",
            metadata={"source": "interrupt", "terminated": terminated, "pid": background_pid},
        ).model_copy(
            update={
                "status": "interrupted",
                "finished_at": _utc_now(),
                "last_error_message": f"interrupted: {normalized_reason}",
                "metadata": {
                    **record.metadata,
                    "interrupt": {
                        "reason": normalized_reason,
                        "requested_at": _utc_now().isoformat(),
                        "terminated": terminated,
                        "pid": background_pid,
                    },
                },
            }
        )
        persisted_record = self._save_run(interrupted_record)

        if persisted_record.team_name is not None:
            self._update_swarm_task_status(
                persisted_record,
                "cancelled",
                detail_suffix=f"agent run {persisted_record.run_id} 已中断，原因：{normalized_reason}",
            )
        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run interrupted: {persisted_record.run_id}",
            body=f"中断原因：{normalized_reason}",
            metadata={
                "run_id": persisted_record.run_id,
                "status": persisted_record.status,
                "terminated": terminated,
                "pid": background_pid,
            },
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        return self._load_run(run_id)

    def spawn(
        self,
        *,
        agent_name: str,
        instruction: str,
        title: str | None = None,
        team_name: str | None = None,
        expected_output: str | None = None,
        task_id: str | None = None,
        parent_run_id: str | None = None,
        allowed_tools: list[str] | str | None = None,
        tool_scope: dict[str, Any] | list[str] | str | None = None,
        worktree_path: str | None = None,
        fork_context: dict[str, Any] | str | None = None,
        use_exact_tools: bool | str | int | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> AgentRunRecord:
        normalized_agent_name = _normalize_name(agent_name, "agent_name")
        definition = self._registry().get(normalized_agent_name)
        normalized_instruction = _non_empty_text(instruction, "instruction")
        normalized_metadata = _parse_mapping_value(metadata)
        raw_allowed_tools = (
            allowed_tools
            if allowed_tools is not None
            else self._pick_first_value(normalized_metadata, ("allowed_tools", "allowedTools"))
        )
        raw_tool_scope = (
            tool_scope
            if tool_scope is not None
            else self._pick_first_value(normalized_metadata, ("tool_scope", "toolScope"))
        )
        if raw_tool_scope is None and raw_allowed_tools is not None:
            raw_tool_scope = {"allowed_tools": raw_allowed_tools, "source": "spawn_allowed_tools"}
        requested_tool_scope = self._normalize_tool_scope(raw_tool_scope)
        tool_scope_explicit = raw_tool_scope is not None
        raw_worktree_path = (
            worktree_path
            if worktree_path is not None
            else self._pick_first_value(normalized_metadata, ("worktree_path", "worktreePath"))
        )
        requested_worktree_path = self._normalize_optional_path_text(raw_worktree_path)
        raw_fork_context = (
            fork_context
            if fork_context is not None
            else self._pick_first_value(normalized_metadata, ("fork_context", "forkContext"))
        )
        raw_fork_context_mapping, fork_context_explicit = self._parse_fork_context_input(raw_fork_context)
        requested_fork_context = self._normalize_fork_context(raw_fork_context)
        raw_use_exact_tools = (
            use_exact_tools
            if use_exact_tools is not None
            else self._pick_first_value(normalized_metadata, ("use_exact_tools", "useExactTools"))
        )
        requested_use_exact_tools = (
            self._coerce_bool(raw_use_exact_tools, default=False)
            if raw_use_exact_tools is not None
            else None
        )
        raw_transcript_state = self._pick_first_value(
            normalized_metadata,
            ("transcript_state", "transcriptState", "subagent_transcript"),
        )
        transcript_state_explicit = raw_transcript_state is not None
        requested_transcript_state = self._normalize_transcript_state(raw_transcript_state)
        raw_replacement_state = self._pick_first_value(
            normalized_metadata,
            ("replacement_state", "replacementState", "content_replacement_state", "contentReplacementState"),
        )
        replacement_state_explicit = raw_replacement_state is not None
        requested_replacement_state = self._normalize_replacement_state(raw_replacement_state)
        normalized_parent_run_id = str(parent_run_id).strip() if isinstance(parent_run_id, str) and parent_run_id.strip() else None
        parent_record: AgentRunRecord | None = None
        inherited_session_id: str | None = None
        parent_run_context: dict[str, Any] = self._default_run_context()
        if normalized_parent_run_id is not None:
            parent_record = self._load_run(normalized_parent_run_id)
            inherited_session_id = parent_record.session_id
            parent_run_context = self._extract_run_context(parent_record)
            normalized_metadata = {
                **normalized_metadata,
                "context_inheritance": {
                    "parent_run_id": parent_record.run_id,
                    "parent_agent_name": parent_record.agent_name,
                    "parent_team_name": parent_record.team_name,
                    "parent_session_id": parent_record.session_id,
                    "inherited_at": _utc_now().isoformat(),
                },
            }
        parent_tool_scope = self._normalize_tool_scope(parent_run_context.get("tool_scope"))
        parent_worktree_path = self._normalize_optional_path_text(parent_run_context.get("worktree_path"))
        parent_fork_context = self._normalize_fork_context(parent_run_context.get("fork_context"))
        parent_use_exact_tools = self._coerce_bool(parent_run_context.get("use_exact_tools"), default=False)
        parent_transcript_state = self._normalize_transcript_state(parent_run_context.get("transcript_state"))
        parent_replacement_state = self._normalize_replacement_state(parent_run_context.get("replacement_state"))
        resolved_tool_scope = requested_tool_scope if tool_scope_explicit else parent_tool_scope
        resolved_use_exact_tools = (
            requested_use_exact_tools if requested_use_exact_tools is not None else parent_use_exact_tools
        )
        if resolved_use_exact_tools:
            resolved_tool_scope = {
                **resolved_tool_scope,
                "mode": "exact",
                "source": str(resolved_tool_scope.get("source") or "use_exact_tools"),
            }
        resolved_worktree_path = requested_worktree_path if requested_worktree_path is not None else parent_worktree_path
        if resolved_worktree_path is not None:
            resolved_worktree_dir = Path(str(resolved_worktree_path)).resolve()
            if not resolved_worktree_dir.exists() or not resolved_worktree_dir.is_dir():
                raise FileNotFoundError(f"worktree_path 不存在或不可访问：{resolved_worktree_dir}")
            resolved_worktree_path = str(resolved_worktree_dir)
        resolved_transcript_state = (
            requested_transcript_state
            if transcript_state_explicit and self._transcript_state_has_content(requested_transcript_state)
            else parent_transcript_state
        )
        resolved_replacement_state = (
            requested_replacement_state
            if replacement_state_explicit and self._replacement_state_has_content(requested_replacement_state)
            else parent_replacement_state
        )
        resolved_fork_context = requested_fork_context if requested_fork_context else parent_fork_context
        if normalized_parent_run_id is not None and parent_record is not None:
            default_fork_context = {
                "parent_run_id": parent_record.run_id,
                "parent_session_id": parent_record.session_id,
                "inherit_parent_messages": True,
                "messages": [],
                "source": "spawn_parent",
                "captured_at": _utc_now().isoformat(),
            }
            has_explicit_parent_run_id = self._mapping_has_any_key(raw_fork_context_mapping, ("parent_run_id", "parentRunId"))
            has_explicit_parent_session_id = self._mapping_has_any_key(raw_fork_context_mapping, ("parent_session_id", "parentSessionId"))
            has_explicit_inherit_parent_messages = self._mapping_has_any_key(
                raw_fork_context_mapping,
                ("inherit_parent_messages", "inheritParentMessages"),
            )
            # 先继承已有上下文，再按“显式优先 + 默认兜底”补齐 parent 信息。
            merged_fork_context = dict(resolved_fork_context) if isinstance(resolved_fork_context, dict) else {}
            if (not has_explicit_parent_run_id) or not str(merged_fork_context.get("parent_run_id") or "").strip():
                merged_fork_context["parent_run_id"] = parent_record.run_id
            if (not has_explicit_parent_session_id) or not str(merged_fork_context.get("parent_session_id") or "").strip():
                merged_fork_context["parent_session_id"] = parent_record.session_id
            # 只有调用方显式设置 inherit_parent_messages 时，才允许覆盖默认继承行为。
            if not has_explicit_inherit_parent_messages:
                merged_fork_context["inherit_parent_messages"] = True
            if not str(merged_fork_context.get("source") or "").strip():
                merged_fork_context["source"] = (
                    "spawn_parent_explicit" if fork_context_explicit else str(default_fork_context["source"])
                )
            if not str(merged_fork_context.get("captured_at") or "").strip():
                merged_fork_context["captured_at"] = str(default_fork_context["captured_at"])
            resolved_fork_context = self._normalize_fork_context(merged_fork_context)
        if not self._transcript_state_has_content(resolved_transcript_state):
            fork_seed_messages = self._normalize_transcript_messages(resolved_fork_context.get("messages"))
            if fork_seed_messages:
                resolved_transcript_state = self._normalize_transcript_state(
                    {
                        "messages": fork_seed_messages,
                        "content_replacements": [],
                        "source": "spawn_fork_seed",
                        "updated_at": _utc_now().isoformat(),
                    }
                )
        context_workspace_dir = Path(str(resolved_worktree_path)).resolve() if resolved_worktree_path is not None else self.workspace_dir
        workspace_run_context = self._build_workspace_run_context(context_workspace_dir=context_workspace_dir)
        resolved_run_context = (
            self._merge_run_context(parent_run_context, workspace_run_context)
            if normalized_parent_run_id is not None
            else workspace_run_context
        )
        resolved_run_context = self._normalize_run_context(
            {
                **resolved_run_context,
                "tool_scope": resolved_tool_scope,
                "worktree_path": resolved_worktree_path,
                "fork_context": resolved_fork_context,
                "use_exact_tools": resolved_use_exact_tools,
                "replacement_state": resolved_replacement_state,
                "transcript_state": resolved_transcript_state,
                "source": "spawn",
            }
        )
        normalized_metadata = {
            **normalized_metadata,
            "run_context": resolved_run_context,
            "run_context_updated_by": "spawn",
            "run_context_updated_at": _utc_now().isoformat(),
            "tool_scope": self._normalize_tool_scope(resolved_run_context.get("tool_scope")),
            "allowed_tools": self._coerce_text_list(self._normalize_tool_scope(resolved_run_context.get("tool_scope")).get("allowed_tools")),
            "worktree_path": resolved_run_context.get("worktree_path"),
            "fork_context": self._normalize_fork_context(resolved_run_context.get("fork_context")),
            "use_exact_tools": self._coerce_bool(resolved_run_context.get("use_exact_tools"), default=False),
            "replacement_state": self._normalize_replacement_state(resolved_run_context.get("replacement_state")),
            "transcript_state": self._normalize_transcript_state(resolved_run_context.get("transcript_state")),
        }
        resolved_team_name = str(team_name).strip() if isinstance(team_name, str) and team_name.strip() else definition.team_name
        resolved_task_title = str(title).strip() if isinstance(title, str) and title.strip() else normalized_instruction.splitlines()[0][:80]
        task = AgentTaskSpec(
            task_id=_normalize_name(task_id or uuid4().hex, "task_id"),
            title=resolved_task_title,
            instruction=normalized_instruction,
            expected_output=str(expected_output).strip() if isinstance(expected_output, str) and expected_output.strip() else None,
            metadata=normalized_metadata,
            team_name=resolved_team_name,
            owner=normalized_agent_name,
            priority=max(0, int(normalized_metadata.get("priority", 0))),
            status="pending",
        )
        run_id = uuid4().hex
        record = AgentRunRecord(
            run_id=run_id,
            agent_name=normalized_agent_name,
            team_name=resolved_team_name,
            task=task,
            status="queued",
            session_id=inherited_session_id,
            parent_run_id=normalized_parent_run_id,
            messages=[AgentRunMessage(message_id=uuid4().hex, role="user", content=normalized_instruction, metadata={"source": "spawn"})],
            metadata=normalized_metadata,
        )
        persisted_record = self._save_run(record)
        self._ensure_task_for_run(persisted_record)
        self._update_swarm_task_status(persisted_record, "pending", detail_suffix=f"agent run {persisted_record.run_id} 已创建，等待执行。")
        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run spawned: {persisted_record.run_id}",
            body=f"任务标题：{persisted_record.task.title}\n任务标识：{persisted_record.task.task_id}",
            metadata={"run_id": persisted_record.run_id, "status": persisted_record.status},
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        return self._load_run(run_id)

    def send(self, *, run_id: str, content: str, metadata: dict[str, Any] | str | None = None) -> AgentRunRecord:
        record = self._load_run(run_id)
        if record.status in {"closed", "cancelled", "interrupted"}:
            raise ValueError(f"当前运行已结束，不能继续 send：{record.run_id}")
        if record.status == "running":
            raise ValueError(f"当前运行仍在执行，不能并发 send：{record.run_id}")
        normalized_metadata = _parse_mapping_value(metadata)
        updated_record = self._append_run_message(
            record,
            role="user",
            content=content,
            metadata={"source": "send", **normalized_metadata},
        ).model_copy(update={"status": "queued", "last_error_message": None})
        persisted_record = self._save_run(updated_record)
        self._update_swarm_task_status(persisted_record, "pending", detail_suffix=f"agent run {persisted_record.run_id} 收到新输入，等待执行。")
        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run queued: {persisted_record.run_id}",
            body=f"已追加用户输入，等待执行。运行状态：{persisted_record.status}",
            metadata={"run_id": persisted_record.run_id, "status": persisted_record.status},
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        return self._load_run(run_id)

    def send_input(self, *, run_id: str, content: str, metadata: dict[str, Any] | str | None = None) -> AgentRunRecord:
        normalized_metadata = _parse_mapping_value(metadata)
        normalized_metadata.setdefault("source", "send_input")
        return self.send(run_id=run_id, content=content, metadata=normalized_metadata)

    def wait(
        self,
        *,
        run_id: str,
        max_turns: int = 32,
        system_prompt: str | None = None,
        graph_name: str = "main",
        output_format: str = "text",
    ) -> AgentRunRecord:
        record = self._load_run(run_id)
        if record.status in {"closed", "cancelled", "interrupted"}:
            raise ValueError(f"当前运行已结束，不能 wait：{record.run_id}")
        if record.status == "running":
            raise ValueError(f"当前运行正在执行，不能重复 wait：{record.run_id}")
        pending_messages = [message for message in record.messages if message.role == "user" and message.consumed_at is None]
        if not pending_messages:
            raise ValueError(f"当前运行没有待消费的用户输入：{record.run_id}")

        record = self._assert_swarm_execution_gate(record=record, source="wait")
        running_record = record.model_copy(update={"status": "running", "started_at": record.started_at or _utc_now(), "last_error_message": None})
        running_record = self._save_run(running_record)
        self._update_swarm_task_status(running_record, "in_progress", detail_suffix=f"agent run {running_record.run_id} 已进入执行。")
        self._emit_mailbox_event(
            team_name=running_record.team_name,
            recipient=running_record.agent_name,
            subject=f"agent run running: {running_record.run_id}",
            body=f"任务 {running_record.task.task_id} 已开始执行。",
            metadata={"run_id": running_record.run_id, "status": running_record.status},
        )
        self._sync_agent_runtime_state(running_record.agent_name)

        pending_input_text = "\n\n".join(message.content for message in pending_messages).strip()
        existing_run_context = self._extract_run_context(running_record)
        execution_workspace_dir = self._resolve_execution_workspace_dir(existing_run_context)
        namespace = Namespace(
            command="run",
            prompt=pending_input_text,
            system_prompt=system_prompt,
            graph_name=graph_name,
            output_format=output_format,
            model=None,
            api_key=None,
            base_url=None,
            reasoning_effort=None,
            cwd=str(execution_workspace_dir),
            session_id=running_record.session_id,
            max_turns=max_turns,
            stream=False,
            debug=False,
        )
        settings = load_app_settings(namespace)
        running_record, run_context = self._ensure_run_context(running_record, settings=settings, source="wait")
        execution_workspace_dir = self._resolve_execution_workspace_dir(run_context)
        tool_scope = self._normalize_tool_scope(run_context.get("tool_scope"))
        allowed_tools = self._coerce_text_list(tool_scope.get("allowed_tools"))
        permission_snapshot = {
            **self._coerce_mapping(run_context.get("permission_snapshot")),
            "tool_scope": tool_scope,
            "allowed_tools": allowed_tools,
            "use_exact_tools": self._coerce_bool(run_context.get("use_exact_tools"), default=False),
        }
        request = ExecutionRequest(
            workspace_dir=execution_workspace_dir,
            user_input=pending_input_text,
            session_id=running_record.session_id,
            system_prompt=system_prompt,
            graph_name=graph_name,
            output_format=output_format,
            max_turns=max_turns,
            stream=False,
            debug=False,
            permission_snapshot=permission_snapshot,
            mcp_resources=self._coerce_mapping_list(run_context.get("mcp_resources")),
            agent_snapshots=self._coerce_mapping_list(run_context.get("agent_snapshots")),
            team_snapshots=self._coerce_mapping_list(run_context.get("team_snapshots")),
            mailbox_snapshot=self._coerce_mapping(run_context.get("mailbox_snapshot")),
        )
        repository = SessionRepository(self.workspace_dir)
        if False and record.status in {"interrupted", "failed", "cancelled"}:
            reset_record = self._append_run_message(
                record,
                role="event",
                content="resume 已将运行状态重置为 queued，等待继续执行。",
                metadata={"source": "resume", "status_reset": True},
            ).model_copy(
                update={
                    "status": "queued",
                    "finished_at": None,
                    "last_error_message": None,
                }
            )
            record = self._save_run(reset_record)
        manager = SessionManager(repository)
        if request.session_id and repository.exists(request.session_id):
            session_state = repository.load(request.session_id)
        else:
            session_state = manager.create_new_state(request)

        model = build_chat_model(
            model_name=settings.model.model_name,
            api_key=settings.model.api_key,
            base_url=settings.model.base_url,
            reasoning_effort=settings.model.reasoning_effort,
        )
        effective_system_prompt = self._build_effective_system_prompt(run_context=run_context, system_prompt=system_prompt)
        fork_message_history = self._build_fork_message_history(record=running_record, run_context=run_context)
        transcript_message_history = self._build_transcript_message_history(run_context=run_context)
        session_message_history = [message.model_dump(mode="python") for message in session_state.messages]
        use_exact_tools = self._coerce_bool(run_context.get("use_exact_tools"), default=False)
        if use_exact_tools:
            if transcript_message_history:
                inference_message_history = transcript_message_history
            elif fork_message_history:
                inference_message_history = fork_message_history
            else:
                inference_message_history = session_message_history
        else:
            if transcript_message_history:
                inference_message_history = transcript_message_history
            elif fork_message_history and session_message_history:
                inference_message_history = [*fork_message_history, *session_message_history]
            elif fork_message_history:
                inference_message_history = fork_message_history
            else:
                inference_message_history = session_message_history
        inference_messages = build_messages_for_inference(
            user_input=pending_input_text,
            tool_results=[],
            system_prompt=effective_system_prompt or session_state.system_prompt,
            message_history=inference_message_history,
        )

        try:
            response = model.invoke(inference_messages)
            response_content = getattr(response, "content", str(response))
            if isinstance(response_content, list):
                response_content = "\n".join(str(item) for item in response_content)
            assistant_output = str(response_content).strip()
            if not assistant_output:
                raise ValueError("模型返回内容为空")

            latest_record = self._load_run(run_id)
            if latest_record.status in {"interrupted", "closed", "cancelled"}:
                self._sync_agent_runtime_state(latest_record.agent_name)
                return latest_record

            updated_session_messages = list(session_state.messages)
            updated_session_messages.append(
                MessageRecord(role="user", content=pending_input_text, created_at=_utc_now().isoformat(), metadata={"agent_run_id": running_record.run_id, "agent_name": running_record.agent_name})
            )
            updated_session_messages.append(
                MessageRecord(role="assistant", content=assistant_output, created_at=_utc_now().isoformat(), metadata={"agent_run_id": running_record.run_id, "agent_name": running_record.agent_name})
            )
            persisted_session_state = session_state.model_copy(
                update={
                    "system_prompt": effective_system_prompt or session_state.system_prompt,
                    "messages": updated_session_messages,
                    "latest_output": assistant_output,
                    "turn_count": session_state.turn_count + 1,
                    "updated_at": _utc_now().isoformat(),
                }
            )
            manager.save(persisted_session_state)

            consumed_at = _utc_now()
            pending_ids = {message.message_id for message in pending_messages}
            consumed_messages: list[AgentRunMessage] = []
            for message in running_record.messages:
                consumed_messages.append(message.model_copy(update={"consumed_at": consumed_at}) if message.message_id in pending_ids else message)
            updated_run_context, updated_transcript_state, updated_replacement_state = self._append_transcript_turn(
                run_context=run_context,
                run_id=running_record.run_id,
                session_id=persisted_session_state.session_id,
                user_input=pending_input_text,
                assistant_output=assistant_output,
            )

            completed_record = running_record.model_copy(
                update={
                    "status": "waiting",
                    "session_id": persisted_session_state.session_id,
                    "finished_at": _utc_now(),
                    "latest_output": assistant_output,
                    "metadata": {
                        **running_record.metadata,
                        "run_context": updated_run_context,
                        "run_context_updated_by": "wait",
                        "run_context_updated_at": _utc_now().isoformat(),
                        "transcript_state": updated_transcript_state,
                        "replacement_state": updated_replacement_state,
                    },
                    "messages": [
                        *consumed_messages,
                        AgentRunMessage(
                            message_id=uuid4().hex,
                            role="assistant",
                            content=assistant_output,
                            metadata={
                                "session_id": persisted_session_state.session_id,
                                "graph_name": graph_name,
                                "success": True,
                                "tool_scope": tool_scope,
                                "use_exact_tools": use_exact_tools,
                                "worktree_path": run_context.get("worktree_path"),
                                "transcript_message_count": len(updated_transcript_state.get("messages") or []),
                                "replacement_entry_count": len(updated_replacement_state.get("entries") or []),
                            },
                        ),
                    ],
                }
            )
            persisted_record = self._save_run(completed_record)
            self._update_swarm_task_status(persisted_record, "completed", detail_suffix=f"agent run {persisted_record.run_id} 执行完成。")
            self._emit_mailbox_event(
                team_name=persisted_record.team_name,
                recipient=persisted_record.agent_name,
                subject=f"agent run completed: {persisted_record.run_id}",
                body=assistant_output,
                metadata={"run_id": persisted_record.run_id, "status": persisted_record.status, "session_id": persisted_record.session_id},
            )
            self._sync_agent_runtime_state(persisted_record.agent_name)
            return self._load_run(run_id)
        except Exception as exc:
            latest_record = self._load_run(run_id)
            if latest_record.status in {"interrupted", "closed", "cancelled"}:
                self._sync_agent_runtime_state(latest_record.agent_name)
                return latest_record
            failed_record = self._append_run_message(running_record, role="event", content=f"wait 执行失败：{exc}", metadata={"source": "wait", "error": str(exc)}).model_copy(
                update={"status": "failed", "finished_at": _utc_now(), "last_error_message": str(exc)}
            )
            persisted_record = self._save_run(failed_record)
            self._update_swarm_task_status(persisted_record, "failed", detail_suffix=f"agent run {persisted_record.run_id} 执行失败：{exc}")
            self._emit_mailbox_event(
                team_name=persisted_record.team_name,
                recipient=persisted_record.agent_name,
                subject=f"agent run failed: {persisted_record.run_id}",
                body=str(exc),
                metadata={"run_id": persisted_record.run_id, "status": persisted_record.status},
            )
            self._sync_agent_runtime_state(persisted_record.agent_name)
            raise

    def _resume_legacy(self, *, run_id: str) -> AgentRunRecord:
        record = self._load_run(run_id)
        repository = SessionRepository(self.workspace_dir)
        if record.status in {"interrupted", "failed", "cancelled"}:
            record = self._save_run(
                self._append_run_message(
                    record,
                    role="event",
                    content="resume 已将运行状态重置为 queued，等待继续执行。",
                    metadata={"source": "resume", "status_reset": True},
                ).model_copy(
                    update={
                        "status": "queued",
                        "finished_at": None,
                        "last_error_message": None,
                    }
                )
            )
        if record.session_id is not None:
            if repository.exists(record.session_id):
                return record
            raise FileNotFoundError(f"run 绑定的会话不存在：run_id={record.run_id}, session_id={record.session_id}")
        if record.parent_run_id is None:
            return record
        parent_record = self._load_run(record.parent_run_id)
        if parent_record.session_id is None:
            return record
        if not repository.exists(parent_record.session_id):
            raise FileNotFoundError(f"父 run 会话不存在：parent_run_id={parent_record.run_id}, session_id={parent_record.session_id}")
        repaired_record = self._append_run_message(
            record,
            role="event",
            content=f"resume 继承父运行会话：{parent_record.session_id}",
            metadata={"source": "resume", "parent_run_id": parent_record.run_id},
        ).model_copy(
            update={
                "session_id": parent_record.session_id,
                "metadata": {
                    **record.metadata,
                    "session_recovered": True,
                    "session_recovered_from_parent_run_id": parent_record.run_id,
                },
            }
        )
        persisted_record = self._save_run(repaired_record)
        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run resumed: {persisted_record.run_id}",
            body=f"已恢复会话：{persisted_record.session_id}",
            metadata={"run_id": persisted_record.run_id, "parent_run_id": parent_record.run_id, "session_id": persisted_record.session_id},
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        return self._load_run(run_id)

    def resume(self, *, run_id: str) -> AgentRunRecord:
        record = self._load_run(run_id)
        repository = SessionRepository(self.workspace_dir)
        if record.status in {"interrupted", "failed", "cancelled"}:
            record = self._save_run(
                self._append_run_message(
                    record,
                    role="event",
                    content="resume 已将运行状态重置为 queued，等待继续执行。",
                    metadata={"source": "resume", "status_reset": True},
                ).model_copy(
                    update={
                        "status": "queued",
                        "finished_at": None,
                        "last_error_message": None,
                    }
                )
            )

        parent_record: AgentRunRecord | None = None
        if record.parent_run_id is not None:
            parent_record = self._load_run(record.parent_run_id)
            run_context = self._extract_run_context(record)
            parent_run_context = self._extract_run_context(parent_record)
            recovered_run_context = self._merge_run_context(run_context, parent_run_context)
            if recovered_run_context != run_context:
                record = self._save_run(
                    self._append_run_message(
                        record,
                        role="event",
                        content=f"resume 恢复父运行上下文：{parent_record.run_id}",
                        metadata={"source": "resume", "parent_run_id": parent_record.run_id, "run_context_recovered": True},
                    ).model_copy(
                        update={
                            "metadata": {
                                **record.metadata,
                                "run_context": recovered_run_context,
                                "run_context_updated_by": "resume",
                                "run_context_updated_at": _utc_now().isoformat(),
                                "run_context_recovered_from_parent_run_id": parent_record.run_id,
                            }
                        }
                    )
                )

        run_context = self._extract_run_context(record)
        self._resolve_execution_workspace_dir(run_context)

        if record.session_id is not None:
            if repository.exists(record.session_id):
                return record
            raise FileNotFoundError(f"run 绑定的会话不存在：run_id={record.run_id}, session_id={record.session_id}")
        if parent_record is None:
            return record
        if parent_record.session_id is None:
            return record
        if not repository.exists(parent_record.session_id):
            raise FileNotFoundError(f"父 run 会话不存在：parent_run_id={parent_record.run_id}, session_id={parent_record.session_id}")

        repaired_record = self._append_run_message(
            record,
            role="event",
            content=f"resume 继承父运行会话：{parent_record.session_id}",
            metadata={"source": "resume", "parent_run_id": parent_record.run_id},
        ).model_copy(
            update={
                "session_id": parent_record.session_id,
                "metadata": {
                    **record.metadata,
                    "session_recovered": True,
                    "session_recovered_from_parent_run_id": parent_record.run_id,
                    "worktree_path": run_context.get("worktree_path"),
                    "use_exact_tools": self._coerce_bool(run_context.get("use_exact_tools"), default=False),
                    "transcript_state": self._normalize_transcript_state(run_context.get("transcript_state")),
                    "replacement_state": self._normalize_replacement_state(run_context.get("replacement_state")),
                    "transcript_message_count": len(
                        self._normalize_transcript_state(run_context.get("transcript_state")).get("messages") or []
                    ),
                    "replacement_entry_count": len(
                        self._normalize_replacement_state(run_context.get("replacement_state")).get("entries") or []
                    ),
                },
            }
        )
        persisted_record = self._save_run(repaired_record)
        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run resumed: {persisted_record.run_id}",
            body=f"已恢复会话：{persisted_record.session_id}",
            metadata={"run_id": persisted_record.run_id, "parent_run_id": parent_record.run_id, "session_id": persisted_record.session_id},
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        return self._load_run(run_id)

    def close(self, *, run_id: str, reason: str | None = None) -> AgentRunRecord:
        record = self._load_run(run_id)
        if record.status in {"queued", "running"}:
            record = self.interrupt(run_id=run_id, reason=reason or "close_requested")
        if record.status in {"closed", "cancelled"}:
            return record

        normalized_reason = str(reason).strip() if isinstance(reason, str) and reason.strip() else "manual_close"
        updated_record = self._append_run_message(record, role="event", content=f"run 已关闭，原因：{normalized_reason}", metadata={"source": "close"}).model_copy(
            update={"status": "closed", "closed_at": _utc_now(), "close_reason": normalized_reason}
        )
        persisted_record = self._save_run(updated_record)

        if persisted_record.team_name is not None:
            should_cancel_task = False
            try:
                task = self._store().load_task(persisted_record.team_name, persisted_record.task.task_id)
                should_cancel_task = task.status not in {"completed", "failed", "cancelled"}
            except FileNotFoundError:
                should_cancel_task = False
            if should_cancel_task:
                self._update_swarm_task_status(
                    persisted_record,
                    "cancelled",
                    detail_suffix=f"agent run {persisted_record.run_id} 已关闭，原因：{normalized_reason}",
                )

        self._emit_mailbox_event(
            team_name=persisted_record.team_name,
            recipient=persisted_record.agent_name,
            subject=f"agent run closed: {persisted_record.run_id}",
            body=f"关闭原因：{normalized_reason}",
            metadata={"run_id": persisted_record.run_id, "status": persisted_record.status},
        )
        self._sync_agent_runtime_state(persisted_record.agent_name)
        return self._load_run(run_id)
