"""
模块名称：fs
功能描述：
    提供 Windows 优先的路径处理、目录创建、文本读取等真实文件系统操作函数，
    供工具层、权限层与图节点复用。

主要组件：
    - ensure_directory: 确保目录存在。
    - normalize_workspace_path: 将用户输入路径解析到工作区绝对路径。
    - read_text_file: 读取 UTF-8 文本文件。

依赖说明：
    - pathlib: 路径处理。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化文件系统工具函数。
"""

from __future__ import annotations

from pathlib import Path


def ensure_directory(directory: Path) -> Path:
    """
    确保目录存在，不存在时递归创建。

    :param directory: 目标目录。
    :return: 创建后的绝对目录路径。
    """

    resolved_directory = directory.expanduser().resolve()
    resolved_directory.mkdir(parents=True, exist_ok=True)
    return resolved_directory


def normalize_workspace_path(workspace_dir: Path, raw_path: str) -> Path:
    """
    将用户输入路径归一化到工作区内的绝对路径。

    :param workspace_dir: 工作区目录。
    :param raw_path: 用户输入的相对路径或绝对路径。
    :return: 归一化后的绝对路径。
    """

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_dir / candidate
    return candidate.resolve()


def read_text_file(file_path: Path) -> str:
    """
    以 UTF-8 读取文本文件内容。

    :param file_path: 文件路径。
    :return: 文件内容。
    :raises FileNotFoundError: 文件不存在时触发。
    """

    return file_path.read_text(encoding="utf-8")
