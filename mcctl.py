#!/usr/bin/env python3
"""
mcctl — Modular-MC-AI 终端控制客户端
通过 Unix 域套接字连接后台服务，发送游戏指令及查询 Mod 状态。

用法：
  python mcctl.py                       交互式终端
  python mcctl.py "/mc say hello"       单条命令
  python mcctl.py "/list"               查看连接
  python mcctl.py "/mod-status"         查看所有 Mod 状态
"""

import asyncio
import sys
import os

SOCKET_PATH = "/tmp/minecraft-ai.sock"


async def interactive():
    """交互式模式"""
    if not os.path.exists(SOCKET_PATH):
        print(f"[!] 套接字不存在: {SOCKET_PATH}")
        print(f"    请确认 Minecraft AI Companion 服务正在运行。")
        sys.exit(1)

    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    async def read_responses():
        """后台读取服务器返回数据并输出到终端"""
        while True:
            data = await reader.readline()
            if not data:
                break
            sys.stdout.write(data.decode("utf-8", errors="replace"))
            sys.stdout.flush()

    # 启动后台读取任务
    read_task = asyncio.create_task(read_responses())

    # 主线读取用户输入
    loop = asyncio.get_running_loop()
    try:
        while not read_task.done():
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            writer.write(line.encode("utf-8"))
            await writer.drain()
            if line.strip() in ("/exit", "/quit"):
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        read_task.cancel()
        try:
            await read_task
        except asyncio.CancelledError:
            pass
        writer.close()
        await writer.wait_closed()


async def one_shot(command: str):
    """单条命令模式"""
    if not os.path.exists(SOCKET_PATH):
        print(f"[!] 套接字不存在: {SOCKET_PATH}")
        sys.exit(1)

    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    # 跳过欢迎横幅
    await reader.readline()  # == Minecraft AI Terminal ==
    await reader.readline()  # 提示
    await reader.readline()  # 空行

    writer.write(f"{command}\n".encode("utf-8"))
    await writer.drain()

    # 跳过回显的 >> 提示符
    while True:
        resp = await reader.readline()
        if not resp:
            break
        text = resp.decode("utf-8", errors="replace")
        if text.startswith(">> "):
            continue
        sys.stdout.write(text)
        sys.stdout.flush()
        if not text.startswith("==") and not text.startswith("输入"):
            break

    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 单条命令模式: python mcctl.py "/mc say hello"
        command = " ".join(sys.argv[1:])
        asyncio.run(one_shot(command))
    else:
        # 交互式: python mcctl.py
        print("连接中... (输入 /help 查看命令, /exit 退出)\n")
        asyncio.run(interactive())
