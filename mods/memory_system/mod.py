# -*- coding: utf-8 -*-
"""
记忆系统 Mod
管理玩家个人记忆、全服记忆、对话上下文。

职责分工：
  - 内存 ContextWindow → 维护最近 N 轮对话原始消息（直接喂给 AI）
  - 文件 JSON Storage → 持久化长期历史 + 全服事件
  - System Prompt 只引用全服事件，不再注入冗余历史
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import aiofiles

from core.mod_api import ModBase, CoreServices

TZ_UTC8 = timezone(timedelta(hours=8))


class MemorySystemMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "memory_system"

    @property
    def mod_version(self) -> str:
        return "1.1.0"

    @property
    def mod_description(self) -> str:
        return "玩家记忆、全服记忆、对话上下文管理（支持持久化冷热唤醒）"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        mem_config = self.config.get("memory", {})
        self._players_dir = mem_config.get("players_dir", "data/memory/players")
        self._server_memory_path = mem_config.get("server_memory_path", "data/memory/server.json")
        self._summary_path = mem_config.get("summary_path", "data/memory/summary.json")
        self._max_history = mem_config.get("max_history_per_player", 50)

        os.makedirs(self._players_dir, exist_ok=True)
        self._init_file_sync(self._server_memory_path, {"events": [], "last_updated": ""})
        self._init_file_sync(self._summary_path, {"last_summary": "", "key_points": []})

        # 上下文管理
        self._context_windows: Dict[str, 'ContextWindow'] = {}
        self._context_max = 6
        self._context_cleanup = 1800

        # 并发锁：每个玩家独立 asyncio.Lock，保证“读-改-写”原子性
        self._locks: Dict[str, asyncio.Lock] = {}

        self.log.info("[memory_system] 记忆系统已就绪")

    def on_disable(self) -> None:
        self._context_windows.clear()
        self._locks.clear()

    # ============================================================
    # 公共 API — 持久化存储（异步、非阻塞）
    # ============================================================

    async def save_message(self, player_name: str, content: str, role: str = "user") -> None:
        """保存一条玩家对话记录（异步、并发安全）。"""
        lock = self._get_player_lock(player_name)
        async with lock:
            now = datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")
            filepath = self._get_player_file(player_name)
            data = await self._read_json_async(filepath)

            data.setdefault("name", player_name)
            data.setdefault("history", [])
            data["history"].append({"time": now, "role": role, "content": content})

            if len(data["history"]) > self._max_history:
                data["history"] = data["history"][-self._max_history:]

            await self._write_json_async(filepath, data)

    async def save_server_event(self, event_type: str, description: str) -> None:
        """保存全服事件记忆（异步）。"""
        now = datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")
        async with self._get_server_lock():
            data = await self._read_json_async(self._server_memory_path)
            data.setdefault("events", [])
            data["events"].append({"time": now, "type": event_type, "description": description})
            data["last_updated"] = now
            if len(data["events"]) > 100:
                data["events"] = data["events"][-100:]
            await self._write_json_async(self._server_memory_path, data)

    async def get_server_memory_summary(self) -> str:
        """获取全服记忆摘要字符串。"""
        data = await self._read_json_async(self._server_memory_path)
        events = data.get("events", [])
        if not events:
            return ""
        recent = events[-5:]
        return "\n".join(f"[{e['time']}] {e['description']}" for e in recent)

    # ============================================================
    # 公共 API — 内存上下文（支持异步从文件加载唤醒）
    # ============================================================

    async def get_context_messages(self, player_id: str) -> List[dict]:
        """异步获取玩家当前上下文消息列表。若内存为空，自动从 JSON 文件载入历史。"""
        self._cleanup_contexts()
        ctx = self._get_or_create_context(player_id)
        
        # 如果内存中没有任何对话记录，尝试从 JSON 文件中恢复最近的对话
        if not ctx.get_messages():
            await self._restore_from_file(player_id, ctx)
            
        return ctx.get_messages()

    def add_to_context(self, player_id: str, role: str, content: str) -> None:
        """向玩家上下文添加一条消息。"""
        self._cleanup_contexts()
        ctx = self._get_or_create_context(player_id)
        ctx.add_message(role, content)

    def clear_context(self, player_id: str) -> None:
        if player_id in self._context_windows:
            self._context_windows[player_id].clear()

    # ============================================================
    # 内部 — 异步冷启动唤醒记忆
    # ============================================================

    async def _restore_from_file(self, player_id: str, ctx: 'ContextWindow') -> None:
        """从 JSON 备份文件中异步恢复历史对话到内存。"""
        filepath = self._get_player_file(player_id)
        if not os.path.exists(filepath):
            return

        lock = self._get_player_lock(player_id)
        async with lock:
            try:
                data = await self._read_json_async(filepath)
                history = data.get("history", [])
                if not history:
                    return

                # 取出最近的 N 轮对话（一问一答算两项，限制最多加载 ctx._max_length 条数据）
                recent_history = history[-ctx._max_length:]
                for msg in recent_history:
                    # 重新灌入内存 ContextWindow
                    ctx.add_message(msg["role"], msg["content"])
                self.log.info(f"[memory_system] 成功为玩家 {player_id} 异步恢复了 {len(recent_history)} 条历史记忆")
            except Exception as e:
                self.log.error(f"[memory_system] 恢复玩家 {player_id} 记忆时发生异常: {e}")

    # ============================================================
    # 内部 — 异步文件 I/O
    # ============================================================

    @staticmethod
    def _init_file_sync(path: str, default: dict) -> None:
        """初始化文件，仅在 on_enable 时同步调用（启动前，不阻塞事件循环）。"""
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)

    @staticmethod
    async def _read_json_async(path: str) -> dict:
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()
                return json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @staticmethod
    async def _write_json_async(path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    # ============================================================
    # 内部 — 并发锁
    # ============================================================

    def _get_player_lock(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    _server_lock: Optional[asyncio.Lock] = None

    def _get_server_lock(self) -> asyncio.Lock:
        if self._server_lock is None:
            self._server_lock = asyncio.Lock()
        return self._server_lock

    # ============================================================
    # 内部 — 上下文管理
    # ============================================================

    def _get_player_file(self, player_name: str) -> str:
        return os.path.join(self._players_dir, f"{player_name}.json")

    def _get_or_create_context(self, player_id: str) -> 'ContextWindow':
        if player_id not in self._context_windows:
            self._context_windows[player_id] = ContextWindow(max_length=self._context_max)
        return self._context_windows[player_id]

    def _cleanup_contexts(self) -> None:
        now = time.time()
        expired = [
            pid for pid, ctx in self._context_windows.items()
            if now - ctx.last_access > self._context_cleanup
        ]
        for pid in expired:
            del self._context_windows[pid]


# ============================================================
# 上下文窗口（内部类）
# ============================================================

class ContextWindow:
    def __init__(self, max_length: int = 6):
        self._messages: List[dict] = []
        self._max_length = max_length
        self._last_access = time.time()

    def add_message(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
        self._last_access = time.time()
        system_msgs = [m for m in self._messages if m["role"] == "system"]
        other_msgs = [m for m in self._messages if m["role"] != "system"]
        if len(other_msgs) > self._max_length:
            other_msgs = other_msgs[-self._max_length:]
        self._messages = system_msgs + other_msgs

    def set_system_prompt(self, content: str) -> None:
        self._messages = [m for m in self._messages if m["role"] != "system"]
        self._messages.insert(0, {"role": "system", "content": content})

    def get_messages(self) -> List[dict]:
        self._last_access = time.time()
        return list(self._messages)

    def clear(self) -> None:
        self._messages = []

    @property
    def last_access(self) -> float:
        return self._last_access