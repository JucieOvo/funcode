"""
模块名称：mcp.registry
功能描述：
    提供 Python 版 Funcode 的轻量级 MCP 资源注册中心。
    该模块既支持显式注册单个资源，也会在首次注册工作区根资源后，
    自动发现同一工作区内真实存在的文档与运行时状态文件，供命令层读取。

主要组件：
    - McpResource: MCP 资源数据模型
    - McpRegistry: MCP 资源注册与发现中心

依赖说明：
    - pathlib: 路径处理
    - datetime: 文件时间元数据
    - pydantic: 资源数据建模

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现 MCP 注册中心与工作区资源发现
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _build_uri_for_path(path: Path, workspace_root: Path | None) -> str:
    """
    根据真实文件路径构建稳定的 workspace URI。

    :param path: 目标文件路径。
    :param workspace_root: 工作区根目录，若可用则优先使用相对路径。
    :return: 统一的 workspace:// URI。
    """

    resolved_path = path.resolve()
    if workspace_root is not None:
        try:
            relative_path = resolved_path.relative_to(workspace_root.resolve())
            return f"workspace://{relative_path.as_posix()}"
        except ValueError:
            pass
    return f"file://{resolved_path.as_posix()}"


def _guess_title(path: Path, workspace_root: Path | None) -> str:
    """
    根据真实路径生成可读标题。

    :param path: 文件路径。
    :param workspace_root: 工作区根目录。
    :return: 可读标题。
    """

    if workspace_root is not None:
        try:
            relative_path = path.resolve().relative_to(workspace_root.resolve())
            return relative_path.as_posix()
        except ValueError:
            pass
    return path.stem or path.name


def _guess_kind(path: Path) -> str:
    """
    根据文件后缀推断资源类型。

    :param path: 文件路径。
    :return: 资源类型标签。
    """

    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".json":
        return "json"
    if suffix in {".yml", ".yaml"}:
        return "yaml"
    if suffix == ".txt":
        return "text"
    return "file"


class McpResource(BaseModel):
    """
    MCP 资源定义。

    这里的资源必须是真实可读的本地文件，不接受虚构路径或占位内容。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    uri: str = Field(description="资源唯一标识")
    title: str = Field(description="资源标题")
    path: Path = Field(description="本地文件路径")
    description: str = Field(default="", description="资源描述")
    kind: str = Field(default="file", description="资源类型")
    source: str = Field(default="workspace", description="资源来源")
    relative_path: str | None = Field(default=None, description="相对工作区路径")
    size_bytes: int | None = Field(default=None, description="文件大小")
    modified_at: str | None = Field(default=None, description="最后修改时间")
    tags: tuple[str, ...] = Field(default_factory=tuple, description="资源标签")


class McpRegistry:
    """
    轻量级 MCP 资源注册中心。

    设计目标：
        1. 显式注册单个真实文件资源。
        2. 在注册工作区根资源后，自动发现工作区内可读的真实资源。
        3. 避免重复注册与假数据拼接。
    """

    def __init__(self) -> None:
        self._resources: dict[str, McpResource] = {}
        self._discovered_roots: set[Path] = set()

    @staticmethod
    def _materialize_resource(path: Path, workspace_root: Path | None, source: str) -> McpResource:
        """
        把真实文件路径转换成资源模型。

        :param path: 目标文件路径。
        :param workspace_root: 工作区根目录。
        :param source: 资源来源标签。
        :return: 资源模型。
        :raises FileNotFoundError: 当文件不存在时触发。
        """

        resolved_path = path.resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"资源文件不存在：{resolved_path}")

        stat_result = resolved_path.stat()
        relative_path: str | None = None
        if workspace_root is not None:
            try:
                relative_path = resolved_path.relative_to(workspace_root.resolve()).as_posix()
            except ValueError:
                relative_path = None

        return McpResource(
            uri=_build_uri_for_path(resolved_path, workspace_root),
            title=_guess_title(resolved_path, workspace_root),
            path=resolved_path,
            description="自动发现的真实工作区资源" if source == "workspace_discovery" else "工作区真实资源",
            kind=_guess_kind(resolved_path),
            source=source,
            relative_path=relative_path,
            size_bytes=int(stat_result.st_size),
            modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat(),
            tags=("auto-discovered",) if source == "workspace_discovery" else ("workspace",),
        )

    def _register_resource(self, resource: McpResource) -> None:
        """
        向内部注册表写入资源，遇到重复 URI 时保持已有真实对象。

        :param resource: 资源模型。
        :raises ValueError: 当同一 URI 对应了不同路径时触发。
        """

        existing = self._resources.get(resource.uri)
        if existing is None:
            self._resources[resource.uri] = resource
            return
        if existing.path.resolve() != resource.path.resolve():
            raise ValueError(f"重复的 MCP URI 对应了不同路径：{resource.uri}")

    def register(self, resource: McpResource) -> None:
        """
        注册单个真实 MCP 资源，并在适当时触发工作区级自动发现。

        :param resource: 资源对象。
        """

        self._register_resource(resource)
        discovery_root = resource.path.parent if resource.path.is_file() else resource.path
        self.discover_workspace_resources(discovery_root)

    def discover_workspace_resources(self, workspace_root: Path) -> None:
        """
        扫描工作区中真实存在的文档与运行时状态文件。

        :param workspace_root: 工作区根目录。
        """

        resolved_root = workspace_root.resolve()
        if resolved_root in self._discovered_roots:
            return
        if not resolved_root.exists() or not resolved_root.is_dir():
            return

        self._discovered_roots.add(resolved_root)
        candidate_patterns = [
            "README.md",
            "AGENTS.md",
            "docs/**/*.md",
            "docs/**/*.json",
            ".funcode/**/*.md",
            ".funcode/**/*.json",
        ]
        for pattern in candidate_patterns:
            for candidate in sorted(resolved_root.glob(pattern)):
                if not candidate.is_file():
                    continue
                resource = self._materialize_resource(candidate, resolved_root, "workspace_discovery")
                self._register_resource(resource)

    def list_resources(self) -> list[McpResource]:
        """
        列出当前注册表中的全部资源。

        :return: 已注册资源列表。
        """

        return sorted(self._resources.values(), key=lambda item: item.uri)

    def read_resource(self, uri: str) -> str:
        """
        通过 URI 读取真实资源文本。

        :param uri: 资源 URI。
        :return: 资源文本内容。
        :raises KeyError: 当资源未注册时触发。
        :raises FileNotFoundError: 当资源路径在磁盘上已不存在时触发。
        """

        resource = self._resources[uri]
        if not resource.path.exists():
            raise FileNotFoundError(f"资源文件不存在：{resource.path}")
        return resource.path.read_text(encoding="utf-8")

    def snapshot(self) -> dict[str, Any]:
        """
        输出当前 MCP 注册中心的真实快照。

        :return: 资源统计与目录统计。
        """

        resources = self.list_resources()
        return {
            "resource_count": len(resources),
            "kind_counts": {
                kind: sum(1 for item in resources if item.kind == kind)
                for kind in sorted({item.kind for item in resources})
            },
            "source_counts": {
                source: sum(1 for item in resources if item.source == source)
                for source in sorted({item.source for item in resources})
            },
            "resources": [resource.model_dump(mode="json") for resource in resources],
        }
