"""
核心事件中心模块
提供游戏事件的分发与监听机制，基于观察者模式实现松耦合。
"""

import asyncio
import logging
from typing import Callable, Awaitable, Dict, List, Any

# 事件处理器类型
EventHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class EventBus:
    """
    轻量级异步事件总线。
    各模块通过 subscribe 注册监听，通过 dispatch 触发事件。
    """

    def __init__(self):
        self._listeners: Dict[str, List[EventHandler]] = {}

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """
        订阅某个事件。

        Args:
            event_name: 事件名，如 "PlayerMessage", "PlayerJoin", "PlayerLeave"
            handler: 异步回调函数，签名为 async def handler(event_data)
        """
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """取消订阅。"""
        if event_name in self._listeners and handler in self._listeners[event_name]:
            self._listeners[event_name].remove(handler)

    async def dispatch(self, event_name: str, event_data: Dict[str, Any]) -> None:
        """
        异步分发事件给所有订阅者。

        使用 create_task 将每个 handler 作为独立后台任务运行，
        确保 WebSocket 接收循环不被慢 handler 阻塞。
        单个 handler 的异常不会影响其他 handler 或事件循环。
        """
        handlers = self._listeners.get(event_name, [])
        for handler in handlers:
            asyncio.create_task(self._run_handler_safely(handler, event_name, event_data))

    async def _run_handler_safely(self, handler: EventHandler, event_name: str, event_data: Dict[str, Any]):
        """安全执行单个处理器并记录异常。"""
        try:
            await handler(event_data)
        except Exception as e:
            logging.getLogger("error").error(
                f"[EventBus] 处理器异常 | event={event_name} "
                f"handler={getattr(handler, '__name__', repr(handler))} "
                f"error={type(e).__name__}: {e}",
                exc_info=True
            )

    def list_events(self) -> List[str]:
        """列出当前已注册的事件类型。"""
        return list(self._listeners.keys())

    def clear_all(self) -> int:
        """
        清除所有事件订阅。用于热重载时彻底断开旧 Mod 的引用链，
        防止旧实例通过闭包继续响应事件（幽灵对象问题）。

        Returns:
            被清除的处理器总数。
        """
        count = sum(len(handlers) for handlers in self._listeners.values())
        self._listeners.clear()
        return count


# 全局事件总线单例
event_bus = EventBus()
