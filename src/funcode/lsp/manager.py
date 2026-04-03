"""
模块名称：funcode.lsp.manager
功能描述：
    提供 LSP 语言服务管理器，实现按语言划分的服务实例与文档缓存层。
    当前实现聚焦本地工作区的真实文件分析，不使用 mock/stub。

主要组件：
    - LspServiceManager: 语言服务管理器，负责缓存与路由。
    - get_lsp_manager: 获取按工作区复用的管理器实例。
    - get_supported_lsp_actions: 返回支持的 action 集合。

依赖说明：
    - ast / py_compile: Python 语法与编译诊断
    - subprocess: Node/TypeScript 诊断调用
    - funcode.schemas.core: LSP 结构化模型

作者：JucieOvo
创建日期：2026-04-02
"""

from __future__ import annotations

import ast
import os
import py_compile
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from funcode.schemas.core import (
    LspDiagnostic,
    LspHover,
    LspLocation,
    LspReference,
    LspServiceState,
    LspSymbol,
)
from funcode.utils.errors import ToolExecutionError

_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_JS_SYMBOL_PATTERNS = (
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")),
    ("variable", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
)
_IGNORED_DIRECTORY_NAMES = {".git", ".venv", "__pycache__", "node_modules", ".funcode", ".idea", ".vscode"}
_LANGUAGE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "python": (".py", ".pyi"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx"),
}
_INDEXABLE_EXTENSIONS = {ext for extensions in _LANGUAGE_EXTENSIONS.values() for ext in extensions}
_SEARCHABLE_EXTENSIONS = _INDEXABLE_EXTENSIONS | {".json", ".md", ".toml", ".yaml", ".yml"}
_SUPPORTED_ACTIONS = (
    "document_symbols",
    "workspace_symbols",
    "diagnostics",
    "definition",
    "references",
    "hover",
    "search",
    "service_state",
)


def _resolve_node_command(binary_name: str) -> str:
    """
    解析 Node 生态命令真实可执行路径。
    目标：
        1. 优先使用 PATH 中可执行文件；
        2. Windows 下兼容 .cmd/.exe/.bat 后缀；
        3. 若 PATH 不可用，回退到常见 Node 安装目录（如 Program Files\\nodejs）。

    :param binary_name: 命令名，例如 node、npx。
    :return: 可执行文件绝对路径或可直接执行的命令名。
    :raises ToolExecutionError: 当无法定位命令时触发。
    """

    normalized_name = str(binary_name).strip()
    if not normalized_name:
        raise ToolExecutionError("Node 命令名称不能为空")

    candidates = [normalized_name]
    if os.name == "nt":
        base_name = normalized_name.lower()
        if not base_name.endswith((".cmd", ".exe", ".bat", ".ps1")):
            candidates = [
                f"{normalized_name}.cmd",
                f"{normalized_name}.exe",
                f"{normalized_name}.bat",
                normalized_name,
            ]

    for candidate in candidates:
        located = shutil.which(candidate)
        if located:
            return located

    if os.name == "nt":
        lookup_roots: list[Path] = []
        for environment_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "NVM_HOME", "NVM_SYMLINK"):
            raw_value = os.environ.get(environment_key)
            if not raw_value:
                continue
            root_path = Path(raw_value).resolve()
            lookup_roots.append(root_path)
            if root_path.name.lower() != "nodejs":
                lookup_roots.append(root_path / "nodejs")

        visited_directories: set[str] = set()
        for root_path in lookup_roots:
            root_text = str(root_path).lower()
            if root_text in visited_directories:
                continue
            visited_directories.add(root_text)
            if not root_path.exists() or not root_path.is_dir():
                continue
            for candidate in candidates:
                executable_path = (root_path / candidate).resolve()
                if executable_path.exists() and executable_path.is_file():
                    return str(executable_path)

    raise ToolExecutionError(
        f"无法定位 Node 生态命令：{normalized_name}。请确认 Node.js 已安装且命令可用。"
    )


def _utc_now() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat()


def _language_for_suffix(suffix: str) -> str | None:
    """根据文件扩展名解析语言类型。"""

    normalized_suffix = suffix.lower()
    for language_name, extensions in _LANGUAGE_EXTENSIONS.items():
        if normalized_suffix in extensions:
            return language_name
    return None


def _relative_path(workspace_dir: Path, target_path: Path) -> str:
    """将绝对路径转换为工作区相对路径。"""

    resolved_workspace = workspace_dir.resolve()
    resolved_target = target_path.resolve()
    try:
        return str(resolved_target.relative_to(resolved_workspace))
    except ValueError:
        return str(resolved_target)


@dataclass(slots=True)
class _DocumentSnapshot:
    """
    文档缓存快照。
    用于在同一进程内复用符号索引、引用索引和文档信息。
    """

    path: Path
    relative_path: str
    language: str
    mtime_ns: int
    size: int
    lines: list[str]
    symbols: list[LspSymbol]
    docs_by_name: dict[str, str]
    occurrences_by_name: dict[str, list[LspLocation]]
    indexed_at: str


class _BaseLanguageService:
    """语言服务基类。"""

    language: str = ""
    extensions: tuple[str, ...] = ()

    def parse_symbols(self, file_path: Path, source_text: str, workspace_dir: Path) -> tuple[list[LspSymbol], dict[str, str]]:
        raise NotImplementedError

    def collect_diagnostics(self, file_path: Path, workspace_dir: Path, source_text: str) -> list[LspDiagnostic]:
        raise NotImplementedError


class _PythonLanguageService(_BaseLanguageService):
    """Python 语言服务。"""

    language = "python"
    extensions = _LANGUAGE_EXTENSIONS["python"]

    def parse_symbols(self, file_path: Path, source_text: str, workspace_dir: Path) -> tuple[list[LspSymbol], dict[str, str]]:
        parsed_tree = ast.parse(source_text, filename=str(file_path))
        symbols: list[LspSymbol] = []
        docs_by_name: dict[str, str] = {}

        def append_symbol(
            *,
            name: str,
            kind: str,
            line: int,
            column: int,
            end_line: int | None,
            end_column: int | None,
            signature: str,
            container_name: str | None,
            documentation: str | None,
        ) -> None:
            symbols.append(
                LspSymbol(
                    name=name,
                    kind=kind,
                    path=_relative_path(workspace_dir, file_path),
                    line=line,
                    column=column,
                    language=self.language,
                    container_name=container_name,
                    signature=signature,
                )
            )
            if documentation:
                docs_by_name[name] = documentation

        def visit(node: ast.AST, container_name: str | None = None) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    append_symbol(
                        name=child.name,
                        kind="class",
                        line=child.lineno,
                        column=child.col_offset + 1,
                        end_line=getattr(child, "end_lineno", None),
                        end_column=(getattr(child, "end_col_offset", None) or 0) + 1
                        if getattr(child, "end_col_offset", None) is not None
                        else None,
                        signature=f"class {child.name}",
                        container_name=container_name,
                        documentation=ast.get_docstring(child),
                    )
                    visit(child, child.name)
                    continue
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arguments_text = ", ".join(argument.arg for argument in child.args.args)
                    prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                    append_symbol(
                        name=child.name,
                        kind="function",
                        line=child.lineno,
                        column=child.col_offset + 1,
                        end_line=getattr(child, "end_lineno", None),
                        end_column=(getattr(child, "end_col_offset", None) or 0) + 1
                        if getattr(child, "end_col_offset", None) is not None
                        else None,
                        signature=f"{prefix} {child.name}({arguments_text})",
                        container_name=container_name,
                        documentation=ast.get_docstring(child),
                    )
                    visit(child, child.name)
                    continue
                if container_name is None and isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            append_symbol(
                                name=target.id,
                                kind="variable",
                                line=target.lineno,
                                column=target.col_offset + 1,
                                end_line=target.lineno,
                                end_column=target.col_offset + 1 + len(target.id),
                                signature=target.id,
                                container_name=None,
                                documentation=None,
                            )
                    continue
                if container_name is None and isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    append_symbol(
                        name=child.target.id,
                        kind="variable",
                        line=child.target.lineno,
                        column=child.target.col_offset + 1,
                        end_line=child.target.lineno,
                        end_column=child.target.col_offset + 1 + len(child.target.id),
                        signature=child.target.id,
                        container_name=None,
                        documentation=None,
                    )
                    continue
                visit(child, container_name)

        visit(parsed_tree)
        return symbols, docs_by_name

    def collect_diagnostics(self, file_path: Path, workspace_dir: Path, source_text: str) -> list[LspDiagnostic]:
        diagnostics: list[LspDiagnostic] = []
        try:
            ast.parse(source_text, filename=str(file_path))
        except SyntaxError as exc:
            diagnostics.append(
                LspDiagnostic(
                    path=_relative_path(workspace_dir, file_path),
                    line=int(exc.lineno or 1),
                    column=int(exc.offset or 1),
                    severity="error",
                    message=str(exc.msg or "Python 语法错误"),
                    source="python-ast",
                    code="SyntaxError",
                )
            )
            return diagnostics

        try:
            py_compile.compile(str(file_path), doraise=True)
        except py_compile.PyCompileError as exc:
            compile_error = exc.exc_value
            if isinstance(compile_error, SyntaxError):
                diagnostics.append(
                    LspDiagnostic(
                        path=_relative_path(workspace_dir, file_path),
                        line=int(compile_error.lineno or 1),
                        column=int(compile_error.offset or 1),
                        severity="error",
                        message=str(compile_error.msg or "Python 编译失败"),
                        source="py_compile",
                        code="PyCompileError",
                    )
                )
            else:
                diagnostics.append(
                    LspDiagnostic(
                        path=_relative_path(workspace_dir, file_path),
                        line=1,
                        column=1,
                        severity="error",
                        message=str(exc),
                        source="py_compile",
                        code="PyCompileError",
                    )
                )
        return diagnostics


class _JavaScriptLanguageService(_BaseLanguageService):
    """JavaScript/TypeScript 语言服务。"""

    language = "javascript"
    extensions = _LANGUAGE_EXTENSIONS["javascript"] + _LANGUAGE_EXTENSIONS["typescript"]
    _tsc_pattern_a = re.compile(r"^(?P<path>.+?)\((?P<line>\d+),(?P<column>\d+)\): error TS(?P<code>\d+): (?P<message>.+)$")
    _tsc_pattern_b = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<column>\d+): error TS(?P<code>\d+): (?P<message>.+)$")

    def parse_symbols(self, file_path: Path, source_text: str, workspace_dir: Path) -> tuple[list[LspSymbol], dict[str, str]]:
        symbols: list[LspSymbol] = []
        seen_entries: set[tuple[str, int]] = set()
        language_name = "typescript" if file_path.suffix.lower() in _LANGUAGE_EXTENSIONS["typescript"] else "javascript"
        relative_path = _relative_path(workspace_dir, file_path)

        for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
            for kind, pattern in _JS_SYMBOL_PATTERNS:
                matched = pattern.search(raw_line)
                if matched is None:
                    continue
                symbol_name = matched.group(1)
                dedupe_key = (symbol_name, line_number)
                if dedupe_key in seen_entries:
                    continue
                seen_entries.add(dedupe_key)
                start_column = matched.start(1) + 1
                symbols.append(
                    LspSymbol(
                        name=symbol_name,
                        kind=kind,
                        path=relative_path,
                        line=line_number,
                        column=start_column,
                        language=language_name,
                        container_name=None,
                        signature=raw_line.strip(),
                    )
                )
                break
        return symbols, {}

    def collect_diagnostics(self, file_path: Path, workspace_dir: Path, source_text: str) -> list[LspDiagnostic]:
        suffix = file_path.suffix.lower()
        if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
            node_command = _resolve_node_command("node")
            completed = subprocess.run(
                [node_command, "--check", str(file_path.resolve())],
                cwd=str(workspace_dir.resolve()),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if completed.returncode == 0:
                return []
            rendered_message = (completed.stderr or completed.stdout or "").strip()
            return [
                LspDiagnostic(
                    path=_relative_path(workspace_dir, file_path),
                    line=1,
                    column=1,
                    severity="error",
                    message=rendered_message or "JavaScript 语法检查失败",
                    source="node --check",
                    code="NodeSyntaxError",
                )
            ]

        npx_command = _resolve_node_command("npx")
        # 使用 ignoreConfig 规避“指定文件 + 工作区 tsconfig”导致的 TS5112 配置级阻塞。
        # 目标是优先获取目标文件本身的真实诊断，而不是被项目配置诊断拦截。
        command = [
            npx_command,
            "tsc",
            "--pretty",
            "false",
            "--noEmit",
            "--skipLibCheck",
            "--ignoreConfig",
        ]
        if suffix in {".tsx", ".jsx"}:
            command.extend(["--jsx", "preserve"])
        if suffix == ".jsx":
            command.extend(["--allowJs", "true", "--checkJs", "true"])
        command.append(str(file_path.resolve()))

        completed = subprocess.run(
            command,
            cwd=str(workspace_dir.resolve()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode == 0:
            return []

        diagnostics: list[LspDiagnostic] = []
        rendered = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
        resolved_target = file_path.resolve()
        for raw_line in rendered.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            matched = self._tsc_pattern_a.match(line) or self._tsc_pattern_b.match(line)
            if matched is None:
                continue
            raw_reported_path = matched.group("path").strip().strip("\"'")
            reported_path = Path(raw_reported_path)
            resolved_reported = reported_path if reported_path.is_absolute() else (workspace_dir.resolve() / reported_path)
            try:
                if resolved_reported.resolve() != resolved_target:
                    continue
            except OSError:
                continue
            diagnostics.append(
                LspDiagnostic(
                    path=_relative_path(workspace_dir, file_path),
                    line=int(matched.group("line")),
                    column=int(matched.group("column")),
                    severity="error",
                    message=matched.group("message").strip(),
                    source="tsc",
                    code=f"TS{matched.group('code')}",
                )
            )

        if diagnostics:
            return diagnostics
        # 配置级错误不应阻塞文件级诊断结果输出。
        if "TS5112" in rendered:
            return []
        return [
            LspDiagnostic(
                path=_relative_path(workspace_dir, file_path),
                line=1,
                column=1,
                severity="error",
                message=(rendered.strip() or "TypeScript 诊断失败"),
                source="tsc",
                code="TSUnknown",
            )
        ]


class LspServiceManager:
    """
    LSP 语言服务管理器。
    按语言维护服务实例，并维护按文件粒度的索引缓存。
    """

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()
        self._lock = RLock()
        self._services: dict[str, _BaseLanguageService] = {
            "python": _PythonLanguageService(),
            "javascript": _JavaScriptLanguageService(),
            "typescript": _JavaScriptLanguageService(),
        }
        self._document_cache: dict[Path, _DocumentSnapshot] = {}
        self._last_indexed_at_by_language: dict[str, str] = {}

    def _iter_workspace_files(self, extensions: set[str]) -> list[Path]:
        matched_files: list[Path] = []
        for file_path in self.workspace_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in _IGNORED_DIRECTORY_NAMES for part in file_path.parts):
                continue
            if file_path.suffix.lower() not in extensions:
                continue
            matched_files.append(file_path)
        return matched_files

    def _resolve_service(self, file_path: Path) -> _BaseLanguageService:
        language = _language_for_suffix(file_path.suffix)
        if language is None:
            raise ToolExecutionError(f"LSP 不支持该文件类型：{file_path.suffix}")
        service = self._services.get(language)
        if service is None:
            raise ToolExecutionError(f"LSP 未注册语言服务：{language}")
        return service

    def _build_occurrences(self, file_path: Path, lines: list[str], language: str) -> dict[str, list[LspLocation]]:
        occurrences: dict[str, list[LspLocation]] = {}
        relative_path = _relative_path(self.workspace_dir, file_path)
        for line_number, raw_line in enumerate(lines, start=1):
            for matched in _TOKEN_PATTERN.finditer(raw_line):
                symbol_name = matched.group(0)
                entry = LspLocation(
                    path=relative_path,
                    line=line_number,
                    column=matched.start() + 1,
                    end_line=line_number,
                    end_column=matched.end() + 1,
                    language=language,
                )
                occurrences.setdefault(symbol_name, []).append(entry)
        return occurrences

    def _get_document_snapshot(self, file_path: Path) -> _DocumentSnapshot:
        resolved_path = file_path.resolve()
        if not resolved_path.exists() or not resolved_path.is_file():
            raise ToolExecutionError(f"LSP 目标文件不存在：{resolved_path}")
        service = self._resolve_service(resolved_path)
        file_stat = resolved_path.stat()

        with self._lock:
            cached = self._document_cache.get(resolved_path)
            if cached is not None and cached.mtime_ns == file_stat.st_mtime_ns and cached.size == file_stat.st_size:
                return cached

        # 统一使用 utf-8-sig 读取，兼容带 BOM 的源码文件，避免符号索引阶段因编码前缀中断。
        source_text = resolved_path.read_text(encoding="utf-8-sig", errors="replace")
        symbols, docs_by_name = service.parse_symbols(resolved_path, source_text, self.workspace_dir)
        lines = source_text.splitlines()
        occurrences = self._build_occurrences(resolved_path, lines, service.language)
        snapshot = _DocumentSnapshot(
            path=resolved_path,
            relative_path=_relative_path(self.workspace_dir, resolved_path),
            language=service.language,
            mtime_ns=file_stat.st_mtime_ns,
            size=file_stat.st_size,
            lines=lines,
            symbols=symbols,
            docs_by_name=docs_by_name,
            occurrences_by_name=occurrences,
            indexed_at=_utc_now(),
        )

        with self._lock:
            self._document_cache[resolved_path] = snapshot
            self._last_indexed_at_by_language[service.language] = snapshot.indexed_at
        return snapshot

    def _symbol_from_position(self, snapshot: _DocumentSnapshot, line: int, column: int) -> str | None:
        if line < 1 or line > len(snapshot.lines):
            return None
        raw_line = snapshot.lines[line - 1]
        position = max(1, column)
        for matched in _TOKEN_PATTERN.finditer(raw_line):
            start_col = matched.start() + 1
            end_col = matched.end() + 1
            if start_col <= position <= end_col:
                return matched.group(0)
        return None

    def _resolve_symbol_query(
        self,
        *,
        file_path: Path | None,
        symbol: str | None,
        line: int | None,
        column: int | None,
    ) -> tuple[str, _DocumentSnapshot | None]:
        normalized_symbol = str(symbol or "").strip()
        if normalized_symbol:
            if file_path is None:
                return normalized_symbol, None
            return normalized_symbol, self._get_document_snapshot(file_path)
        if file_path is None or line is None or column is None:
            raise ToolExecutionError("LSP 查询缺少 symbol 或 file_path+line+column 参数")
        snapshot = self._get_document_snapshot(file_path)
        position_symbol = self._symbol_from_position(snapshot, line, column)
        if position_symbol is None:
            raise ToolExecutionError("指定位置未命中任何符号")
        return position_symbol, snapshot

    def document_symbols(self, file_path: Path) -> list[LspSymbol]:
        snapshot = self._get_document_snapshot(file_path)
        return list(snapshot.symbols)

    def workspace_symbols(
        self,
        *,
        query: str | None = None,
        language: str | None = None,
        max_results: int = 200,
    ) -> list[LspSymbol]:
        normalized_query = str(query or "").strip().lower()
        normalized_language = str(language or "").strip().lower() or None
        symbols: list[LspSymbol] = []
        for file_path in self._iter_workspace_files(_INDEXABLE_EXTENSIONS):
            try:
                # 工作区级检索需要容忍局部文件异常，避免单文件解析失败导致全局 action 失败。
                snapshot = self._get_document_snapshot(file_path)
            except Exception:
                continue
            if normalized_language and snapshot.language != normalized_language:
                continue
            for symbol_item in snapshot.symbols:
                if normalized_query and normalized_query not in symbol_item.name.lower():
                    continue
                symbols.append(symbol_item)
                if len(symbols) >= max_results:
                    return symbols
        return symbols

    def diagnostics(self, file_path: Path) -> list[LspDiagnostic]:
        resolved_path = file_path.resolve()
        if not resolved_path.exists() or not resolved_path.is_file():
            raise ToolExecutionError(f"LSP 目标文件不存在：{resolved_path}")
        service = self._resolve_service(resolved_path)
        source_text = resolved_path.read_text(encoding="utf-8-sig", errors="replace")
        return service.collect_diagnostics(resolved_path, self.workspace_dir, source_text)

    def definition(
        self,
        *,
        file_path: Path | None = None,
        symbol: str | None = None,
        line: int | None = None,
        column: int | None = None,
        max_results: int = 20,
    ) -> list[LspLocation]:
        resolved_symbol, _ = self._resolve_symbol_query(
            file_path=file_path,
            symbol=symbol,
            line=line,
            column=column,
        )
        definitions: list[LspLocation] = []
        for symbol_item in self.workspace_symbols(query=resolved_symbol, max_results=max_results * 10):
            if symbol_item.name != resolved_symbol:
                continue
            definitions.append(
                LspLocation(
                    path=symbol_item.path,
                    line=symbol_item.line,
                    column=symbol_item.column,
                    language=symbol_item.language,
                )
            )
            if len(definitions) >= max_results:
                break
        return definitions

    def references(
        self,
        *,
        file_path: Path | None = None,
        symbol: str | None = None,
        line: int | None = None,
        column: int | None = None,
        max_results: int = 300,
    ) -> list[LspReference]:
        resolved_symbol, _ = self._resolve_symbol_query(
            file_path=file_path,
            symbol=symbol,
            line=line,
            column=column,
        )
        definitions = {
            (location.path, location.line, location.column)
            for location in self.definition(symbol=resolved_symbol, max_results=max_results)
        }
        references: list[LspReference] = []
        for candidate_path in self._iter_workspace_files(_INDEXABLE_EXTENSIONS):
            try:
                # 引用检索是跨文件操作，允许跳过不可解析文件以保证可用性。
                snapshot = self._get_document_snapshot(candidate_path)
            except Exception:
                continue
            for location in snapshot.occurrences_by_name.get(resolved_symbol, []):
                context_line = ""
                if 1 <= location.line <= len(snapshot.lines):
                    context_line = snapshot.lines[location.line - 1].strip()
                references.append(
                    LspReference(
                        symbol=resolved_symbol,
                        location=location,
                        is_definition=(location.path, location.line, location.column) in definitions,
                        context_line=context_line,
                    )
                )
                if len(references) >= max_results:
                    return references
        return references

    def hover(
        self,
        *,
        file_path: Path | None = None,
        symbol: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> LspHover | None:
        resolved_symbol, source_snapshot = self._resolve_symbol_query(
            file_path=file_path,
            symbol=symbol,
            line=line,
            column=column,
        )
        matching_symbols = [item for item in self.workspace_symbols(query=resolved_symbol, max_results=200) if item.name == resolved_symbol]
        if not matching_symbols:
            return None

        selected = matching_symbols[0]
        if source_snapshot is not None:
            for candidate in matching_symbols:
                if candidate.path == source_snapshot.relative_path:
                    selected = candidate
                    break

        selected_snapshot = self._get_document_snapshot(self.workspace_dir / selected.path)
        documentation = selected_snapshot.docs_by_name.get(selected.name)
        return LspHover(
            symbol=selected.name,
            kind=selected.kind,
            signature=selected.signature,
            documentation=documentation,
            location=LspLocation(
                path=selected.path,
                line=selected.line,
                column=selected.column,
                language=selected.language,
            ),
        )

    def search(self, *, query: str, use_regex: bool = False, max_results: int = 200) -> list[dict[str, Any]]:
        if not query.strip():
            raise ToolExecutionError("search 操作必须提供 query")
        compiled = re.compile(query) if use_regex else re.compile(re.escape(query))
        matches: list[dict[str, Any]] = []
        for file_path in self._iter_workspace_files(_SEARCHABLE_EXTENSIONS):
            snapshot = self._get_document_snapshot(file_path) if file_path.suffix.lower() in _INDEXABLE_EXTENSIONS else None
            lines = snapshot.lines if snapshot is not None else file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line_number, raw_line in enumerate(lines, start=1):
                for matched in compiled.finditer(raw_line):
                    matches.append(
                        {
                            "path": _relative_path(self.workspace_dir, file_path),
                            "line": line_number,
                            "column": matched.start() + 1,
                            "match_text": matched.group(0),
                            "line_text": raw_line.strip(),
                        }
                    )
                    if len(matches) >= max_results:
                        return matches
        return matches

    def service_state(self) -> list[LspServiceState]:
        with self._lock:
            cached_counts: dict[str, int] = {}
            for snapshot in self._document_cache.values():
                cached_counts[snapshot.language] = cached_counts.get(snapshot.language, 0) + 1
            states = [
                LspServiceState(
                    language=language_name,
                    extensions=list(service.extensions),
                    cached_document_count=cached_counts.get(language_name, 0),
                    last_indexed_at=self._last_indexed_at_by_language.get(language_name),
                )
                for language_name, service in sorted(self._services.items())
                if language_name in {"python", "javascript", "typescript"}
            ]
        return states


_MANAGER_LOCK = RLock()
_MANAGERS: dict[str, LspServiceManager] = {}


def get_lsp_manager(workspace_dir: Path) -> LspServiceManager:
    """获取按工作区复用的 LSP 管理器实例。"""

    resolved_workspace = str(workspace_dir.resolve())
    with _MANAGER_LOCK:
        manager = _MANAGERS.get(resolved_workspace)
        if manager is None:
            manager = LspServiceManager(Path(resolved_workspace))
            _MANAGERS[resolved_workspace] = manager
        return manager


def get_supported_lsp_actions() -> list[str]:
    """返回当前支持的 LSP action。"""

    return list(_SUPPORTED_ACTIONS)
