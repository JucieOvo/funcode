"""
模块名称：llm
功能描述：
    汇总 Python 版 Funcode 的 LLM 工厂与模型配置对象。
主要组件：
    - build_chat_model: 构建 DeepSeek 聊天模型
    - build_messages_for_inference: 构建推理消息
    - DeepSeekModelConfig: DeepSeek 模型配置对象
    - InferencePayload: 推理输入聚合对象
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 LLM 包导出。
"""

from .factory import build_chat_model, build_messages_for_inference
from .models import DeepSeekModelConfig, InferencePayload

__all__ = [
    "DeepSeekModelConfig",
    "InferencePayload",
    "build_chat_model",
    "build_messages_for_inference",
]
