"""
模块名称：importing
功能描述：
    提供跨子系统延迟导入能力，降低子代理并行写代码时的循环依赖风险。

主要组件：
    - optional_import: 按模块路径和属性名进行延迟导入。

依赖说明：
    - importlib: 模块动态导入。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化延迟导入工具。
"""

from __future__ import annotations

import importlib
from typing import Any


def optional_import(module_name: str, attribute_name: str) -> Any:
    """
    延迟导入指定模块属性。

    :param module_name: 模块路径。
    :param attribute_name: 属性名称。
    :return: 导入后的对象。
    :raises ImportError: 模块或属性不存在时触发。
    """

    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute_name)
    except AttributeError as exc:
        raise ImportError(f"模块 {module_name} 缺少属性 {attribute_name}") from exc
