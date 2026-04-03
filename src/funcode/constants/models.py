"""
模块名称：models
功能描述：
    存放模型层默认值与支持范围。

主要组件：
    - DEFAULT_CHAT_MODEL: 默认聊天模型。
    - SUPPORTED_REASONING_EFFORTS: 支持的推理强度集合。

依赖说明：
    - 无

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化模型常量。
"""

DEFAULT_CHAT_MODEL = "deepseek-reasoner"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
SUPPORTED_REASONING_EFFORTS = ("low", "medium", "high")
