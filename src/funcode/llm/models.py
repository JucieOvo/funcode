"""
模块名称：llm.models
功能描述：
    定义 Python 版 Funcode 在 LLM 层使用的核心配置对象与消息构建辅助对象。
    该模块只负责配置与数据表达，不负责实际模型调用。
主要组件：
    - DeepSeekModelConfig: DeepSeek OpenAI 兼容模型连接配置
    - InferencePayload: 推理输入聚合对象
    - format_tool_results: 工具结果格式化辅助函数
依赖说明：
    - pydantic: 配置对象校验与序列化
    - typing: 类型注解支持
作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化 LLM 配置与推理输入模型。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from funcode.constants.models import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_DEEPSEEK_BASE_URL,
    SUPPORTED_REASONING_EFFORTS,
)


class DeepSeekModelConfig(BaseModel):
    """
    DeepSeek OpenAI 兼容模型配置。

    :param model_name: 模型名称
    :param api_key: DeepSeek API Key
    :param base_url: OpenAI 兼容服务地址
    :param reasoning_effort: 推理强度
    """

    model_config = ConfigDict(frozen=True)

    model_name: str = Field(default=DEFAULT_CHAT_MODEL, description="模型名称")
    api_key: str = Field(description="DeepSeek API Key")
    base_url: str = Field(default=DEFAULT_DEEPSEEK_BASE_URL, description="OpenAI 兼容服务地址")
    reasoning_effort: str = Field(default="medium", description="推理强度")

    @classmethod
    def from_env(
        cls,
        *,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
    ) -> "DeepSeekModelConfig":
        """
        从环境变量与调用参数构建模型配置。

        :param model_name: 可选模型名覆盖
        :param api_key: 可选 API Key 覆盖
        :param base_url: 可选服务地址覆盖
        :param reasoning_effort: 可选推理强度覆盖
        :return: 模型配置对象
        :raises ValueError: 当 API Key 缺失或推理强度非法时触发
        """

        import os

        resolved_api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not resolved_api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY，无法初始化 DeepSeek 模型。")

        resolved_reasoning_effort = (reasoning_effort or os.getenv("DEEPSEEK_REASONING_EFFORT", "medium")).strip()
        if resolved_reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
            raise ValueError(
                f"reasoning_effort 取值非法：{resolved_reasoning_effort}，"
                f"允许值为 {SUPPORTED_REASONING_EFFORTS}。"
            )

        return cls(
            model_name=(model_name or os.getenv("DEEPSEEK_MODEL", DEFAULT_CHAT_MODEL)).strip(),
            api_key=resolved_api_key,
            base_url=(base_url or os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL)).strip(),
            reasoning_effort=resolved_reasoning_effort,
        )


class InferencePayload(BaseModel):
    """
    推理输入聚合对象。

    :param system_prompt: 系统提示词
    :param user_input: 用户输入
    :param tool_results: 工具结果
    :param planning_prompt: 规划提示词
    :param subagent_prompt: 子代理提示词
    """

    model_config = ConfigDict(frozen=True)

    system_prompt: str
    user_input: str
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    planning_prompt: str
    subagent_prompt: str


def format_tool_results(tool_results: Iterable[Mapping[str, Any]]) -> str:
    """
    将工具结果格式化为适合注入提示词的纯文本。

    :param tool_results: 工具结果集合
    :return: 格式化后的文本
    """

    formatted_blocks: list[str] = []
    for index, tool_result in enumerate(tool_results, start=1):
        tool_name = str(tool_result.get("tool_name", f"tool_{index}"))
        content = str(tool_result.get("content", ""))
        metadata = tool_result.get("metadata", {})
        block_lines = [f"工具结果 {index}: {tool_name}", content]
        if metadata:
            block_lines.append(f"元数据: {metadata}")
        formatted_blocks.append("\n".join(line for line in block_lines if line))
    return "\n\n".join(formatted_blocks)
