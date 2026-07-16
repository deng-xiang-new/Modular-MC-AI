"""
Modular-MC-AI — 主入口文件
===========================
基于基岩版 WebSocket 协议的 Minecraft AI 助手。
采用模块化架构，所有业务逻辑以 Mod 形式组织在 mods/ 目录下。

架构：
  - core/   — 纯底层引擎（不可修改）
  - mods/   — 所有定制业务逻辑（通过 ModBase API）
  - data/   — 运行时数据存储
  - config.json — 全局配置

启动方式：
    python main.py

Minecraft 连接方式（在游戏内）：
    /connect <服务器IP>:8000
"""

import asyncio
import json
import sys
import os
import signal

import websockets

# --- 将项目根目录加入 Python 路径 ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# --- 导入核心模块 ---
from core.websocket import setup_logging, PrintToLogger, MinecraftWSConnection
from core.event import event_bus
from core.scheduler import scheduler
from core.ai_client import AIClient
from core.mod_api import CoreServices
from core.mod_loader import ModLoader


# ============================================================
# 配置加载
# ============================================================

def load_config() -> dict:
    """加载配置文件。"""
    config_path = os.path.join(PROJECT_ROOT, "config.json")
    if not os.path.exists(config_path):
        print(f"[错误] 找不到配置文件: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# WebSocket 连接处理
# ============================================================

async def handle_connection(websocket, services: CoreServices):
    """
    处理每个 Minecraft 客户端的 WebSocket 连接。
    """
    remote = websocket.remote_address
    ip = remote[0] if remote else "unknown"
    server_log = services.server_log
    error_log = services.error_log

    # ---- 安全检查（由 security mod 处理） ----
    try:
        sec_mod = services.get_mod("security")
        if sec_mod and not sec_mod.check_ip(ip):
            server_log.info(f"[主] IP 检查未通过: {ip}")
            await websocket.close(1008, "Security block")
            return
    except Exception as e:
        error_log.error(f"[主] 安全检查异常 [{ip}]: {type(e).__name__}: {e}", exc_info=True)

    # ---- 创建连接 ----
    conn = MinecraftWSConnection(websocket, remote, event_bus, server_log, error_log)

    # ---- 从事件总线获取所有需要订阅的游戏事件 ----
    for evt_name in event_bus.list_events():
        conn.subscribe_event(evt_name)

    # ---- 派发连接建立事件（供 Mod 如 terminal_control 监听） ----
    try:
        await event_bus.dispatch("ConnectionEstablished", {"connection": conn})
    except Exception as e:
        error_log.error(f"[主] 连接建立事件派发异常 [{remote}]: {e}", exc_info=True)

    # ---- 运行连接 ----
    try:
        await conn.run()
    except Exception as e:
        error_log.error(f"[主] 连接异常 [{remote}]: {type(e).__name__}: {e}", exc_info=True)
    finally:
        # ---- 派发连接关闭事件（供 Mod 清理活跃连接列表） ----
        try:
            await event_bus.dispatch("ConnectionClosed", {"connection": conn})
        except Exception as e:
            error_log.error(f"[主] 连接关闭事件派发异常 [{remote}]: {e}", exc_info=True)


# ============================================================
# 主函数
# ============================================================

async def main():
    """主入口点。"""
    # 1. 加载配置
    config = load_config()

    # 2. 初始化日志
    server_log, error_log = setup_logging(config)
    sys.stdout = PrintToLogger(server_log)

    print("=" * 50)
    print(f"Modular-MC-AI 启动中...")
    print(f"AI 名称: {config['ai'].get('name', 'AI')}")
    print(f"监听端口: {config['websocket']['port']}")
    print(f"AI 模型: {config['ai']['model']}")
    print(f"Mod 目录: mods/")
    print("=" * 50)

    # 3. 构建核心服务容器
    services = CoreServices()
    services.event_bus = event_bus
    services.scheduler = scheduler
    services.ai_client = AIClient(config)
    services.config = config
    services.server_log = server_log
    services.error_log = error_log
    services.ai_name = config["ai"].get("name", "AI")

    # 4. 加载所有 Mod
    mods_dir = os.path.join(PROJECT_ROOT, "mods")
    mod_loader = ModLoader(mods_dir)
    mod_loader.load_all(services)

    # 5. 启动调度器
    scheduler.start()

    # 6. 启动 WebSocket 服务器
    port = config["websocket"]["port"]
    host = config["websocket"]["host"]

    print(f"[*] WebSocket 服务启动在 {host}:{port}")
    print(f"[*] 在 Minecraft 中使用 /connect <IP>:{port} 连接")
    print(f"[*] 在聊天栏输入 @ai <问题> 与 AI 对话")
    print(f"[*] 管理命令：发送 SIGUSR1 热重载 Mod | 发送 SIGUSR2 查看 Mod 状态")
    print("-" * 40)

    async def connection_handler(websocket):
        await handle_connection(websocket, services)

    async with websockets.serve(connection_handler, host, port):
        stop_event = asyncio.Event()

        def signal_handler():
            print("\n[*] 收到停止信号，正在关闭...")
            scheduler.stop()
            mod_loader.unload_all()
            stop_event.set()

        def reload_handler():
            """SIGUSR1 → 热重载所有 Mod"""
            print("\n[*] 收到热重载信号 (SIGUSR1)，正在重载所有 Mod ...")
            count = mod_loader.reload_all(services)
            print(f"[*] 热重载完成，{count} 个 Mod 已重新加载")

        def status_handler():
            """SIGUSR2 → 打印所有 Mod 状态"""
            print("\n" + services.status_summary())

        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, signal_handler)
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
            loop.add_signal_handler(signal.SIGUSR1, reload_handler)
            loop.add_signal_handler(signal.SIGUSR2, status_handler)
        except NotImplementedError:
            pass

        await stop_event.wait()

    mod_loader.unload_all()
    print("[*] 服务已安全关闭。")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[-] 用户中断，服务关闭。")
    except SystemExit:
        pass
