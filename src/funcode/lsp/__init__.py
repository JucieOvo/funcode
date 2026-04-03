"""
模块名称：funcode.lsp
功能描述：
    提供 Python 版 Funcode 的 LSP 语言服务管理入口，统一封装
    文档索引、符号检索、诊断、定义、引用和悬停查询能力。

主要组件：
    - LspServiceManager: LSP 服务管理器。
    - get_lsp_manager: 获取按工作区隔离的 LSP 管理器实例。
    - get_supported_lsp_actions: 返回当前支持的 LSP action 列表。

依赖说明：
    - funcode.lsp.manager: LSP 管理器实现

作者：JucieOvo
创建日期：2026-04-02
"""

from __future__ import annotations

from funcode.lsp.manager import (
    LspServiceManager,
    get_lsp_manager,
    get_supported_lsp_actions,
)

__all__ = ["LspServiceManager", "get_lsp_manager", "get_supported_lsp_actions"]

