"""
模块名称：env
功能描述：
    统一定义环境变量键名，避免字符串分散。

主要组件：
    - DEEPSEEK_API_KEY_ENV: DeepSeek API Key 环境变量。
    - DEEPSEEK_BASE_URL_ENV: DeepSeek 服务地址环境变量。
    - DEFAULT_MODEL_ENV: 默认模型环境变量。
    - DEFAULT_CWD_ENV: 默认工作目录环境变量。

依赖说明：
    - 无

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化环境变量常量。
"""

DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
DEFAULT_MODEL_ENV = "FUNCODE_MODEL"
DEFAULT_CWD_ENV = "FUNCODE_DEFAULT_CWD"
REASONING_EFFORT_ENV = "FUNCODE_REASONING_EFFORT"
SESSION_ID_ENV = "FUNCODE_SESSION_ID"
