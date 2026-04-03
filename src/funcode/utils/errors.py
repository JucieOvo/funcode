"""
模块名称：errors
功能描述：
    定义 graph、tools、permissions、mcp 等子系统共用的异常类型，统一错误抛出方式，
    避免各模块零散抛出难以识别的基础异常。

主要组件：
    - FuncodeError: 顶层业务异常。
    - ConfigurationMissingError: 配置缺失异常。
    - PermissionViolationError: 权限违规异常。
    - ToolExecutionError: 工具执行异常。

依赖说明：
    - 无外部依赖。

作者：JucieOvo
创建日期：2026-04-01
修改记录：
    - 2026-04-01 JucieOvo: 初始化通用异常定义。
"""


class FuncodeError(RuntimeError):
    """
    Funcode Python 实现的顶层业务异常。

    :param message: 错误描述。
    """


class ConfigurationMissingError(FuncodeError):
    """
    关键配置缺失时抛出的异常。

    :param message: 配置缺失说明。
    """


class PermissionViolationError(FuncodeError):
    """
    当工具访问越出允许范围时抛出的权限异常。

    :param message: 权限违规说明。
    """


class ToolExecutionError(FuncodeError):
    """
    当工具执行失败时抛出的统一异常。

    :param message: 执行失败说明。
    """
