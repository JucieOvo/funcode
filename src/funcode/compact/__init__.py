"""
模块名称：compact
功能描述：
    汇总上下文压缩能力，暴露压缩结果与压缩器。

主要组件：
    - CompressionResult: 压缩结果对象
    - ContextCompressor: 上下文压缩器
    - compress_messages: 便捷压缩函数

依赖说明：
    - funcode.compact.compressor: 压缩核心实现

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始实现压缩包导出。
"""

from __future__ import annotations

from .compressor import CompressionResult, ContextCompressor, compress_messages

__all__ = [
    "CompressionResult",
    "ContextCompressor",
    "compress_messages",
]
