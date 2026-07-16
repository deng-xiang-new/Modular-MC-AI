"""
终端控制 Mod（Unix 域套接字模式）
后台服务监听 /tmp/minecraft-ai.sock，任何 SSH 会话通过 mcctl 客户端连接。
与 systemd 后台运行完全兼容，无需停服。

客户端使用方式：
  python mcctl.py                      # 交互式
  python mcctl.py "/mc say hello"      # 单条命令
"""

import asyncio
import os
import json
from core.mod_api import ModBase, CoreServices

SOCKET_PATH = "/tmp/minecraft-ai.sock"


class TerminalControlMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "terminal_control"

    @property
    def mod_version(self) -> str:
        return "1.2.0"

    @property
    def mod_description(self) -> str:
        return "Unix 套接字终端控制，通过 mcctl 发送命令到游戏"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        self._conns: list = []
        self._conn_names: dict = {}

        services.event_bus.subscribe("ConnectionEstablished", self._on_connect)
        services.event_bus.subscribe("ConnectionClosed", self._on_disconnect)

        # 清理旧 socket 文件
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        self._server = None
        self._start_server_task = asyncio.create_task(self._start_server())

        self.log.info(f"[terminal_control] 套接字已就绪 │ 使用 python mcctl.py 连接")

    def on_disable(self) -> None:
        self._start_server_task.cancel()
        if self._server:
            self._server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        self.services.event_bus.unsubscribe("ConnectionEstablished", self._on_connect)
        self.services.event_bus.unsubscribe("ConnectionClosed", self._on_disconnect)
        self._conns.clear()

    async def _start_server(self):
        try:
            self._server = await asyncio.start_unix_server(
                self._handle_client, SOCKET_PATH
            )
            os.chmod(SOCKET_PATH, 0o666)  # 所有用户可连接
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.error(f"[terminal_control] 服务器启动失败: {e}")

    # ============================================================
    # 连接管理
    # ============================================================

    async def _on_connect(self, event_data: dict):
        conn = event_data.get("connection")
        if not conn or conn in self._conns:
            return
        self._conns.append(conn)
        alias = f"[{len(self._conns)}] {self._fmt_addr(conn)}"
        self._conn_names[id(conn)] = alias

    async def _on_disconnect(self, event_data: dict):
        conn = event_data.get("connection")
        if not conn:
            return
        if conn in self._conns:
            self._conns.remove(conn)
            self._conn_names.pop(id(conn), None)

    # ============================================================
    # 客户端处理
    # ============================================================

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """处理一个 mcctl 客户端连接。"""
        try:
            # 发送欢迎信息
            writer.write("== Minecraft AI Terminal ==\n输入 /help 查看命令\n\n".encode("utf-8"))
            await writer.drain()

            while True:
                writer.write(">> ".encode("utf-8"))
                await writer.drain()

                line = await reader.readline()
                if not line:
                    break

                cmd = line.decode("utf-8", errors="replace").strip()
                if not cmd:
                    continue

                response = await self._process_command(cmd)
                writer.write(response.encode("utf-8") + b"\n")
                await writer.drain()

                if cmd in ("/exit", "/quit"):
                    break

        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _process_command(self, line: str) -> str:
        """解析命令并返回结果字符串。"""
        if line == "/help" or line == "/?":
            return self._help_text()

        if line == "/exit" or line == "/quit":
            return "已断开连接。服务继续运行。"

        if line == "/list":
            return self._connections_text()

        if line == "/mod-status":
            return self._mod_status_text()

        if line.startswith("/mc "):
            cmd = line[4:].strip()
            return await self._exec_mc(cmd)

        if line.startswith("/all "):
            cmd = line[5:].strip()
            return await self._exec_all(cmd)

        if line[0].isdigit() and " " in line:
            idx_str, _, rest = line.partition(" ")
            return await self._exec_indexed(idx_str, rest.strip())

        if line == "/mc":
            return "用法: /mc <游戏命令>  例如: /mc say hello"

        return f"未知命令: {line} │ 输入 /help 查看帮助"

    # ============================================================
    # 命令执行
    # ============================================================

    async def _exec_mc(self, cmd: str) -> str:
        if not self._conns:
            return "[!] 没有活跃的游戏连接"
        target = self._conns[-1]
        alias = self._conn_names.get(id(target), "最新连接")
        return await self._send_one(target, cmd, alias)

    async def _exec_all(self, cmd: str) -> str:
        if not self._conns:
            return "[!] 没有活跃的游戏连接"
        count = 0
        for conn in list(self._conns):
            try:
                await conn.send_command_fire_and_forget(cmd)
                count += 1
            except Exception as e:
                return f"[!] 广播失败: {e}"
        return f"已向 {count} 个连接广播: {cmd}"

    async def _exec_indexed(self, idx_str: str, cmd: str) -> str:
        if not cmd:
            return "用法: <编号> <命令>  例如: 1 say hello"
        try:
            idx = int(idx_str) - 1
        except ValueError:
            return f"无效编号: {idx_str}"
        if idx < 0 or idx >= len(self._conns):
            return f"编号 {idx_str} 超出范围（1~{len(self._conns)}）"
        conn = self._conns[idx]
        alias = self._conn_names.get(id(conn), f"连接 {idx_str}")
        return await self._send_one(conn, cmd, alias)

    async def _send_one(self, conn, cmd: str, desc: str) -> str:
        try:
            await conn.send_command_fire_and_forget(cmd)
            return f"→ {desc}: {cmd}"
        except Exception as e:
            return f"[!] 发送失败: {e}"

    def _mod_status_text(self) -> str:
        """获取 Mod 状态摘要。"""
        try:
            return self.services.status_summary()
        except Exception as e:
            return f"[!] 无法获取 Mod 状态: {e}"

    def _help_text(self) -> str:
        return (
            "═════ 终端控制命令 ═════\n"
            "  /mc <指令>        发送到最新连接的游戏\n"
            "  /all <指令>       广播到所有连接\n"
            "  <编号> <指令>     发送到指定连接（如 1 say hi）\n"
            "  /list             列出当前活跃连接\n"
            "  /mod-status       查看所有 Mod 加载状态\n"
            "  /help /?          显示此帮助\n"
            "  /exit /quit       断开终端连接\n"
            "════════════════════════"
        )

    def _connections_text(self) -> str:
        if not self._conns:
            return "当前无活跃连接"
        lines = [f"活跃连接 ({len(self._conns)}):"]
        for i, conn in enumerate(self._conns, 1):
            alias = self._conn_names.get(id(conn), f"[{i}] ?")
            lines.append(f"  {alias}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_addr(conn) -> str:
        addr = getattr(conn, "remote_address", None)
        if addr:
            return f"{addr[0]}:{addr[1]}"
        return "unknown"
