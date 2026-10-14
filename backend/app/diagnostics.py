"""记录异常类型和调用栈位置，避免将异常原文中的凭据或代码写入日志。"""

import logging
import traceback


def log_failure(
    logger: logging.Logger, operation: str, error: BaseException, **context: object
) -> None:
    """保留排障所需的操作、关联标识及栈帧，不记录异常消息、源码或局部变量。"""
    frames = [
        f"{frame.f_code.co_filename}:{line} in {frame.f_code.co_name}"
        for frame, line in traceback.walk_tb(error.__traceback__)
    ]
    logger.error(
        "%s failed; context=%r; exception=%s\n%s",
        operation,
        context,
        type(error).__name__,
        "\n".join(frames),
    )
