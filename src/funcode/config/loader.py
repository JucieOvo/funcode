"""
模块名称：loader
功能描述：
    将命令行参数与环境变量组装为统一运行配置对象。

主要组件：
    - load_app_settings: 生成应用运行配置。

依赖说明：
    - os: 环境变量读取
    - funcode.config.paths: 路径解析
    - funcode.config.settings: 配置模型

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化配置加载器。
"""

from __future__ import annotations

import os
from argparse import Namespace

from funcode.config.paths import resolve_workspace_path
from funcode.config.settings import AppSettings, CliSettings, ModelSettings, RuntimeSettings
from funcode.constants.env import (
    DEEPSEEK_API_KEY_ENV,
    DEEPSEEK_BASE_URL_ENV,
    DEFAULT_CWD_ENV,
    DEFAULT_MODEL_ENV,
    REASONING_EFFORT_ENV,
    SESSION_ID_ENV,
)
from funcode.constants.models import DEFAULT_CHAT_MODEL, DEFAULT_DEEPSEEK_BASE_URL


def _pick_string(cli_value: str | None, env_key: str, default: str | None = None) -> str | None:
    """
    选择字符串配置值，优先使用命令行参数，其次使用环境变量，最后使用默认值。

    :param cli_value: 命令行值。
    :param env_key: 环境变量键名。
    :param default: 默认值。
    :return: 选中的字符串值。
    """

    if cli_value is not None and str(cli_value).strip():
        return str(cli_value).strip()
    env_value = os.getenv(env_key)
    if env_value is not None and env_value.strip():
        return env_value.strip()
    return default


def _require_string(value: str | None, field_name: str, env_key: str) -> str:
    """
    校验必须存在的字符串配置。

    :param value: 待校验值。
    :param field_name: 字段名称。
    :param env_key: 对应环境变量键名。
    :return: 已校验的字符串。
    :raises ValueError: 当值缺失时触发。
    """

    if value is None or not value.strip():
        raise ValueError(f"{field_name} 缺失，请通过参数或环境变量 {env_key} 提供。")
    return value


def load_app_settings(namespace: Namespace) -> AppSettings:
    """
    从命令行参数与环境变量加载应用配置。

    :param namespace: argparse 解析结果。
    :return: 汇总后的应用配置对象。
    :raises ValueError: 当关键配置缺失时触发。
    """

    model_name = _pick_string(getattr(namespace, "model", None), DEFAULT_MODEL_ENV, DEFAULT_CHAT_MODEL)
    api_key = _require_string(
        _pick_string(getattr(namespace, "api_key", None), DEEPSEEK_API_KEY_ENV),
        field_name="DeepSeek API Key",
        env_key=DEEPSEEK_API_KEY_ENV,
    )
    base_url = _pick_string(
        getattr(namespace, "base_url", None),
        DEEPSEEK_BASE_URL_ENV,
        DEFAULT_DEEPSEEK_BASE_URL,
    )
    reasoning_effort = _pick_string(
        getattr(namespace, "reasoning_effort", None),
        REASONING_EFFORT_ENV,
        "medium",
    )
    workspace_dir = resolve_workspace_path(
        _pick_string(getattr(namespace, "cwd", None), DEFAULT_CWD_ENV, None),
    )

    model_settings = ModelSettings(
        provider="deepseek",
        model_name=model_name or DEFAULT_CHAT_MODEL,
        api_key=api_key,
        base_url=base_url or DEFAULT_DEEPSEEK_BASE_URL,
        reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
    )
    runtime_settings = RuntimeSettings(
        workspace_dir=workspace_dir,
        session_id=_pick_string(getattr(namespace, "session_id", None), SESSION_ID_ENV, None),
        max_turns=int(getattr(namespace, "max_turns", 32)),
        stream=bool(getattr(namespace, "stream", True)),
        debug=bool(getattr(namespace, "debug", False)),
    )
    cli_settings = CliSettings(
        command=str(getattr(namespace, "command")),
        prompt=getattr(namespace, "prompt", None),
        system_prompt=getattr(namespace, "system_prompt", None),
        graph_name=str(getattr(namespace, "graph_name", "main")),
        output_format=str(getattr(namespace, "output_format", "text")),
    )

    return AppSettings(model=model_settings, runtime=runtime_settings, cli=cli_settings)
