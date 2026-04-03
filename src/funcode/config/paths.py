"""
模块名称：paths
功能描述：
    统一处理 Windows 优先的路径解析逻辑，保证 CLI 与运行时使用一致的路径规则。

主要组件：
    - resolve_workspace_path: 解析工作目录。
    - resolve_optional_file_path: 解析可选文件路径。

依赖说明：
    - pathlib: 路径解析

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化路径解析工具。
"""

from __future__ import annotations

from pathlib import Path


def resolve_workspace_path(raw_path: str | None) -> Path:
    """
    解析工作目录路径。

    :param raw_path: 原始路径字符串，允许为空。
    :return: 解析后的绝对路径对象。
    :raises FileNotFoundError: 当目标路径不存在时触发。
    :raises NotADirectoryError: 当目标路径不是目录时触发。
    """

    candidate = Path(raw_path).expanduser() if raw_path else Path.cwd()
    resolved = candidate.resolve(strict=False)
    if not resolved.exists():
        raise FileNotFoundError(f"工作目录不存在：{resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"工作目录不是文件夹：{resolved}")
    return resolved


def resolve_optional_file_path(raw_path: str | None) -> Path | None:
    """
    解析可选文件路径。

    :param raw_path: 原始路径字符串。
    :return: 解析后的绝对路径对象，若未提供则返回 None。
    """

    if not raw_path:
        return None
    return Path(raw_path).expanduser().resolve(strict=False)
