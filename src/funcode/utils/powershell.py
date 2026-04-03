"""
模块名称：powershell
功能描述：
    提供 Windows 优先的 PowerShell 命令执行能力，作为 Python 版 Funcode
    的核心本地执行工具基础设施。

主要组件：
    - PowerShellResult: PowerShell 执行结果对象。
    - run_powershell_command: 执行 PowerShell 命令。

依赖说明：
    - subprocess: 子进程执行。
    - pathlib: 工作目录处理。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 PowerShell 执行器。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from funcode.utils.errors import ToolExecutionError


@dataclass(slots=True, frozen=True)
class PowerShellResult:
    """
    PowerShell 执行结果。

    :param command: 实际执行的命令文本。
    :param return_code: 进程返回码。
    :param stdout: 标准输出。
    :param stderr: 标准错误。
    """

    command: str
    return_code: int
    stdout: str
    stderr: str


def run_powershell_command(command: str, workdir: Path, timeout_seconds: int = 120) -> PowerShellResult:
    """
    在指定目录下执行 PowerShell 命令。

    :param command: PowerShell 命令。
    :param workdir: 工作目录。
    :param timeout_seconds: 超时时间。
    :return: 执行结果。
    :raises ToolExecutionError: 命令执行失败或 PowerShell 不可用时触发。
    """

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    result = PowerShellResult(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if completed.returncode != 0:
        raise ToolExecutionError(
            f"PowerShell 命令执行失败，返回码={completed.returncode}，stderr={completed.stderr.strip()}"
        )
    return result
