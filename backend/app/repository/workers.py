"""同步仓库操作的协作取消：线程退出后才向调用方传播取消。"""

import asyncio
import threading
from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")


async def run_cancellable(operation: Callable[..., _T], *args: object) -> _T:
    """操作通过 cancel_event 接收取消；调用方等待其完成清理。"""
    cancel = threading.Event()
    worker = asyncio.create_task(asyncio.to_thread(operation, *args, cancel_event=cancel))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        cleanup = asyncio.gather(worker, return_exceptions=True)
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                continue
        raise
