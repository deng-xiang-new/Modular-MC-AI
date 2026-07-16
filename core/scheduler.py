"""
定时任务调度器
提供基于 asyncio 的轻量级定时任务管理。
支持在 start() 之前挂载任务，start() 时统一激活。
"""

import asyncio
from typing import Callable, Dict


class Scheduler:
    """
    异步定时任务调度器。

    特性：
      - 支持在 start() 之前注册周期性/一次性任务，start() 时统一激活
      - 正确处理 CancelledError，保证取消/清理的正常流程
      - 同名周期任务覆盖，cancel 同时移除缓存
    """

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._pending: list = []  # (name, interval_or_delay, coro_func, args, kwargs, is_periodic)
        self._running = False

    async def schedule_periodic(
        self,
        name: str,
        interval_seconds: int,
        coro_func: Callable,
        *args,
        **kwargs
    ) -> None:
        """注册一个周期性任务。若 _running=False 则缓存，由 start() 激活。"""
        if not self._running:
            self.cancel(name)
            self._pending.append((name, interval_seconds, coro_func, args, kwargs, True))
            return

        self.cancel(name)

        async def _runner():
            while self._running:
                try:
                    await coro_func(*args, **kwargs)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"[Scheduler] 周期任务 '{name}' 异常: {e}")
                try:
                    await asyncio.sleep(interval_seconds)
                except asyncio.CancelledError:
                    break

        task = asyncio.create_task(_runner())
        self._tasks[name] = task

    async def schedule_once(
        self,
        delay_seconds: int,
        coro_func: Callable,
        *args,
        **kwargs
    ) -> None:
        """注册一个一次性延迟任务。若 _running=False 则缓存。"""
        if not self._running:
            name = f"__once_{len(self._pending)}__"
            self._pending.append((name, delay_seconds, coro_func, args, kwargs, False))
            return

        async def _runner():
            try:
                await asyncio.sleep(delay_seconds)
            except asyncio.CancelledError:
                return
            try:
                await coro_func(*args, **kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[Scheduler] 一次性任务异常: {e}")

        asyncio.create_task(_runner())

    def cancel(self, name: str) -> None:
        """取消指定任务（含缓存中的待激活任务）。"""
        if name in self._tasks:
            self._tasks[name].cancel()
            del self._tasks[name]
        self._pending = [p for p in self._pending if p[0] != name]

    def start(self) -> None:
        """启动调度器。幂等，将缓存的待激活任务全部启动。"""
        if self._running:
            return
        self._running = True

        for name, interval_or_delay, func, args, kwargs, is_periodic in self._pending:
            if is_periodic:
                asyncio.create_task(
                    self.schedule_periodic(name, interval_or_delay, func, *args, **kwargs)
                )
            else:
                asyncio.create_task(
                    self.schedule_once(interval_or_delay, func, *args, **kwargs)
                )
        self._pending.clear()

    def stop(self) -> None:
        """停止调度器，取消所有活跃任务、清空缓存，并设为停止状态。"""
        self._running = False
        self._pending.clear()
        for name, task in list(self._tasks.items()):
            task.cancel()
        self._tasks.clear()

    def clear_all(self) -> int:
        """
        仅清空所有活跃任务和待激活任务，保留 _running 状态不变。
        专为热重载设计：取消旧 Mod 注册的所有任务，但不改变调度器的运行状态，
        使新 Mod 可以直接注册任务而无需额外的 start() / _running 修复。

        Returns:
            被清除的任务总数（活跃 + 待激活）。
        """
        active_count = len(self._tasks)
        pending_count = len(self._pending)
        self._pending.clear()
        for name, task in list(self._tasks.items()):
            task.cancel()
        self._tasks.clear()
        return active_count + pending_count


# 全局调度器单例
scheduler = Scheduler()
