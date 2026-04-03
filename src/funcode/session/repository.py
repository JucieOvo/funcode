"""
模块名称：session.repository
功能描述：提供会话 JSON 文件仓储，统一到 `.funcode/sessions`，
并兼容读取历史 `.funcode/sessions` 目录，避免运行根目录分裂。
作者：JucieOvo
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from funcode.schemas.core import SessionState


SESSION_ROOT_DIRECTORY_NAME = ".funcode"
LEGACY_SESSION_ROOT_DIRECTORY_NAME = ".funcode"
SESSION_STORAGE_DIRECTORY_NAME = "sessions"


class SessionRepository:
    """
    会话文件仓储。

    设计要点：
    1. 新写入统一落到 `.funcode/sessions`。
    2. 读取和 exists 兼容旧目录，避免历史会话不可见。
    3. 列表优先返回新目录；同 session_id 重名时忽略旧目录副本。
    """

    def __init__(self, workspace_dir: Path) -> None:
        """
        初始化仓储路径。
        :param workspace_dir: 工作区根目录。
        """

        self.workspace_dir = workspace_dir.resolve()
        self.storage_dir = self.workspace_dir / SESSION_ROOT_DIRECTORY_NAME / SESSION_STORAGE_DIRECTORY_NAME
        self.legacy_storage_dir = self.workspace_dir / LEGACY_SESSION_ROOT_DIRECTORY_NAME / SESSION_STORAGE_DIRECTORY_NAME

    def get_session_file_path(self, session_id: str) -> Path:
        """
        返回新目录中的会话文件路径。
        :param session_id: 会话标识。
        :return: 会话文件路径。
        """

        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError("session_id 不能为空字符串")
        return self.storage_dir / f"{normalized_session_id}.json"

    def _get_legacy_session_file_path(self, session_id: str) -> Path:
        """
        返回旧目录中的会话文件路径，仅用于兼容读取。
        :param session_id: 会话标识。
        :return: 旧目录会话文件路径。
        """

        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError("session_id 不能为空字符串")
        return self.legacy_storage_dir / f"{normalized_session_id}.json"

    def _resolve_existing_session_path(self, session_id: str) -> Path | None:
        """
        解析真实存在的会话文件路径（优先新目录）。
        :param session_id: 会话标识。
        :return: 已存在路径；若不存在则返回 None。
        """

        canonical_path = self.get_session_file_path(session_id)
        if canonical_path.exists():
            return canonical_path
        legacy_path = self._get_legacy_session_file_path(session_id)
        if legacy_path.exists():
            return legacy_path
        return None

    def exists(self, session_id: str) -> bool:
        """
        判断会话是否存在（兼容旧目录）。
        :param session_id: 会话标识。
        :return: 是否存在。
        """

        return self._resolve_existing_session_path(session_id) is not None

    def load(self, session_id: str) -> SessionState:
        """
        读取会话状态（兼容旧目录）。
        :param session_id: 会话标识。
        :return: 会话状态对象。
        :raises FileNotFoundError: 会话文件不存在时触发。
        """

        session_file_path = self._resolve_existing_session_path(session_id)
        if session_file_path is None:
            raise FileNotFoundError(f"会话文件不存在：{self.get_session_file_path(session_id)}")
        return SessionState.model_validate_json(session_file_path.read_text(encoding="utf-8"))

    def save(self, session_state: SessionState) -> Path:
        """
        保存会话状态到新目录。
        :param session_state: 会话状态。
        :return: 写入文件路径。
        """

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        session_file_path = self.get_session_file_path(session_state.session_id)
        session_file_path.write_text(session_state.model_dump_json(indent=2), encoding="utf-8")
        return session_file_path

    def list_session_files(self) -> list[Path]:
        """
        列出工作区可见的会话文件（新旧目录合并，按 session_id 去重）。
        :return: 会话文件路径列表。
        """

        canonical_files: list[Path] = []
        if self.storage_dir.exists():
            canonical_files = [
                path
                for path in sorted(self.storage_dir.glob("*.json"), key=lambda item: item.name.casefold())
                if path.is_file()
            ]

        legacy_files: list[Path] = []
        if self.legacy_storage_dir.exists():
            legacy_files = [
                path
                for path in sorted(self.legacy_storage_dir.glob("*.json"), key=lambda item: item.name.casefold())
                if path.is_file()
            ]

        if not canonical_files and not legacy_files:
            return []

        merged: dict[str, Path] = {path.stem: path for path in canonical_files}
        for path in legacy_files:
            if path.stem not in merged:
                merged[path.stem] = path
        return [merged[key] for key in sorted(merged.keys(), key=str.casefold)]

    def list_sessions(self) -> list[SessionState]:
        """
        读取所有会话并按更新时间倒序。
        :return: SessionState 列表。
        """

        sessions = [
            SessionState.model_validate_json(session_file.read_text(encoding="utf-8"))
            for session_file in self.list_session_files()
        ]
        return sorted(
            sessions,
            key=lambda session_state: (
                session_state.updated_at,
                session_state.created_at,
                session_state.session_id,
            ),
            reverse=True,
        )

    def count_sessions(self) -> int:
        """
        统计会话文件数量。
        :return: 会话数量。
        """

        return len(self.list_session_files())

    def build_inventory(self) -> dict[str, Any]:
        """
        构建会话统计快照。
        :return: 统计字典。
        """

        sessions = self.list_sessions()
        total_messages = sum(len(session_state.messages) for session_state in sessions)
        total_tool_calls = sum(len(session_state.tool_calls) for session_state in sessions)
        total_tool_results = sum(len(session_state.tool_results) for session_state in sessions)
        total_plan_steps = sum(len(session_state.plan_steps) for session_state in sessions)
        latest_session = sessions[0] if sessions else None
        return {
            "workspace_dir": str(self.workspace_dir),
            "storage_dir": str(self.storage_dir),
            "legacy_storage_dir": str(self.legacy_storage_dir),
            "session_count": len(sessions),
            "file_count": len(self.list_session_files()),
            "total_messages": total_messages,
            "total_tool_calls": total_tool_calls,
            "total_tool_results": total_tool_results,
            "total_plan_steps": total_plan_steps,
            "latest_session_id": latest_session.session_id if latest_session is not None else None,
            "latest_updated_at": latest_session.updated_at if latest_session is not None else None,
        }
