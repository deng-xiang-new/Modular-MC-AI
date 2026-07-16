"""
基岩版 WebSocket 连接核心模块
处理 Minecraft 客户端连接、事件订阅、消息路由。
纯底层协议层 — 不依赖任何业务模块。
"""

import sys
import os
import asyncio
import uuid
import logging

import websockets

from core.packet import make_packet, parse_packet


# ============================================================
# 日志系统
# ============================================================

def setup_logging(config: dict):
    """配置双日志系统。返回 (server_logger, error_logger)。"""
    os.makedirs(os.path.dirname(config["logging"]["server_log"]), exist_ok=True)

    server_logger = logging.getLogger("server")
    server_logger.setLevel(logging.INFO)
    if not server_logger.handlers:
        sh = logging.FileHandler(config["logging"]["server_log"], encoding="utf-8")
        sh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        server_logger.addHandler(sh)
        server_logger.propagate = False

    error_logger = logging.getLogger("error")
    error_logger.setLevel(logging.WARNING)
    if not error_logger.handlers:
        eh = logging.FileHandler(config["logging"]["error_log"], encoding="utf-8")
        eh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        error_logger.addHandler(eh)
        error_logger.propagate = False

    return server_logger, error_logger


class PrintToLogger:
    """重定向 print，同时输出到控制台和 server.log。"""
    def __init__(self, logger):
        self._logger = logger
        self._stdout = sys.stdout

    def write(self, message):
        self._stdout.write(message)
        if message.strip():
            self._logger.info(message.rstrip())

    def flush(self):
        self._stdout.flush()


# ============================================================
# WebSocket 连接管理器（纯协议层）
# ============================================================

class MinecraftWSConnection:
    """
    管理单个 Minecraft 客户端的 WebSocket 连接。
    纯底层：负责建立连接、订阅事件、收发封包、分发事件。
    不包含安全、AI、命令等业务逻辑。
    """

    def __init__(self, websocket, remote_address, event_bus, server_log, error_log):
        self._ws = websocket
        self._address = remote_address
        self._event_bus = event_bus
        self._server_log = server_log
        self._error_log = error_log
        self._subscribed_events: set = set()
        self._pending_commands: dict[str, asyncio.Future] = {}

    @property
    def remote_address(self):
        return self._address

    def subscribe_event(self, event_name: str) -> None:
        """订阅一个游戏事件（立即生效）。"""
        self._subscribed_events.add(event_name)

    async def send_subscribed_events(self) -> None:
        """向游戏端发送订阅命令，使用 eventRequest 方式（兼容所有基岩版客户端）。"""
        for evt in self._subscribed_events:
            packet = make_packet("subscribe", event_name=evt)
            await self._ws.send(packet)
        self._server_log.info(f"[WS] 已订阅事件: {self._subscribed_events}")

    async def run(self):
        """运行连接处理循环。"""
        self._server_log.info(f"[WS] 客户端已连接: {self._address}")

        try:
            # 向游戏端发送所有事件订阅
            await self.send_subscribed_events()

            async for message in self._ws:
                await self._handle_message(message)

        except websockets.exceptions.ConnectionClosed as e:
            self._server_log.info(f"[WS] 客户端断开: {self._address}, code={e.code}")
        except Exception as e:
            self._error_log.error(f"[WS] 连接异常 [{self._address}]: {type(e).__name__}: {e}", exc_info=True)

    async def send_command(self, command_line: str, timeout: float = 5.0) -> dict:
        """
        向游戏发送指令并异步等待其返回结果。

        通过 requestId 将发送的封包与游戏返回的 commandResponse
        配对，利用 asyncio.Future 实现挂起等待。

        Args:
            command_line: 指令字符串（不需要 / 前缀）
            timeout: 超时秒数，默认 5 秒

        Returns:
            指令响应体 dict，含 statusCode、statusMessage 等字段。
            超时时返回 {"status": "timeout"}。
        """
        cmd_uuid = str(uuid.uuid4())
        packet = make_packet("commandRequest", command_line=command_line, request_id=cmd_uuid)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_commands[cmd_uuid] = future

        try:
            await self._ws.send(packet)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._error_log.warning(f"[WS] 指令超时 ({timeout}s): {command_line}")
            return {"status": "timeout"}
        finally:
            self._pending_commands.pop(cmd_uuid, None)

    async def send_command_fire_and_forget(self, command_line: str) -> None:
        """发送指令但不等待响应（向后兼容的快捷方法）。"""
        packet = make_packet("commandRequest", command_line=command_line)
        await self._ws.send(packet)

    async def _handle_message(self, message: str):
        """处理收到的原始消息并路由到事件总线或 Future。"""
        parsed = parse_packet(message)
        if parsed is None:
            return

        # ---- 指令响应：唤醒等待中的 Future ----
        if parsed["is_command_response"]:
            req_id = parsed["header"].get("requestId")
            if req_id and req_id in self._pending_commands:
                future = self._pending_commands[req_id]
                if not future.done():
                    future.set_result(parsed["body"])
            return

        # ---- 游戏事件：分发到事件总线 ----
        if parsed["is_event"] and parsed["event_name"]:
            event_data = {
                "header": parsed["header"],
                "body": parsed["body"],
                "event_name": parsed["event_name"],
                "connection": self
            }
            await self._event_bus.dispatch(parsed["event_name"], event_data)
