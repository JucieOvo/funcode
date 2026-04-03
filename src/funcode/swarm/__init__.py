"""
模块名称：swarm
功能描述：
    暴露团队协作层的公共接口，包括协调器、文件邮箱与团队/任务/快照模型。
"""

from funcode.swarm.coordinator import SwarmCoordinator
from funcode.swarm.mailbox import FileMailbox
from funcode.swarm.models import (
    SwarmMailboxSnapshot,
    SwarmMessage,
    SwarmMessageType,
    SwarmTask,
    SwarmTaskStatus,
    SwarmTaskUpdate,
    SwarmTeam,
    SwarmTeamSummary,
    SwarmWorkspaceSnapshot,
)

__all__ = [
    "FileMailbox",
    "SwarmCoordinator",
    "SwarmMailboxSnapshot",
    "SwarmMessage",
    "SwarmMessageType",
    "SwarmTask",
    "SwarmTaskStatus",
    "SwarmTaskUpdate",
    "SwarmTeam",
    "SwarmTeamSummary",
    "SwarmWorkspaceSnapshot",
]
