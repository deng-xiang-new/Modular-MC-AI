"""
安全 Mod
合并白名单、黑名单、连接防护。
提供玩家访问控制和扫描攻击防御。
"""

import json
import os
import time
from collections import defaultdict
from typing import Dict, List

from core.mod_api import ModBase, CoreServices


class SecurityMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "security"

    @property
    def mod_version(self) -> str:
        return "1.0.0"

    @property
    def mod_description(self) -> str:
        return "白名单、黑名单、连接防护"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        sec_config = self.config.get("security", {})
        base_dir = "data/security"

        self._whitelist_path = os.path.join(base_dir, "whitelist.json")
        self._blacklist_path = os.path.join(base_dir, "blacklist.json")
        self._banlist_path = os.path.join(base_dir, "banlist.json")

        self._threshold = sec_config.get("scan_threshold", 5)
        self._window_seconds = sec_config.get("scan_window_seconds", 60)
        self._ban_hours = sec_config.get("ban_duration_hours", 24)

        # 连接跟踪
        self._connections: Dict[str, List[float]] = defaultdict(list)
        self._banned: Dict[str, float] = {}

        # 初始化文件
        os.makedirs(base_dir, exist_ok=True)
        self._init_json_list(self._whitelist_path)
        self._init_json_list(self._blacklist_path)
        self._load_banlist()

        # 注册连接拦截钩子（白名单 + 黑名单 + 扫描检测）
        self.log.info("[security] 安全模块已就绪")

    def on_disable(self) -> None:
        self._save_banlist()

    # ============================================================
    # 连接检查（供 core 在建立 WS 连接时调用）
    # ============================================================

    def check_ip(self, ip: str) -> bool:
        """检查 IP 是否允许连接。返回 True 表示允许。"""
        if self._is_ip_banned(ip):
            return False
        return self._record_ip(ip)

    def check_player(self, player_name: str) -> bool:
        """检查玩家是否被允许使用 AI。"""
        return self._is_whitelisted(player_name) and not self._is_blacklisted(player_name)

    # ============================================================
    # 白名单
    # ============================================================

    def _is_whitelisted(self, name: str) -> bool:
        data = self._read_json_list(self._whitelist_path)
        if not data:
            return True  # 空白名单表示允许所有人
        return name in data

    # ============================================================
    # 黑名单
    # ============================================================

    def _is_blacklisted(self, name: str) -> bool:
        return name in self._read_json_list(self._blacklist_path)

    # ============================================================
    # IP 封禁
    # ============================================================

    def _is_ip_banned(self, ip: str) -> bool:
        if ip in self._banned:
            if time.time() < self._banned[ip]:
                self.log.info(f"[security] 拒绝已封禁IP: {ip}")
                return True
            del self._banned[ip]
            self._save_banlist()
        return False

    def _record_ip(self, ip: str) -> bool:
        now = time.time()
        # 清理窗口外的旧记录
        if ip in self._connections:
            self._connections[ip] = [t for t in self._connections[ip] if now - t < self._window_seconds]
            if not self._connections[ip]:
                del self._connections[ip]  # 空列表回收，防止内存泄漏

        self._connections[ip].append(now)
        if len(self._connections[ip]) > self._threshold:
            ban_until = now + self._ban_hours * 3600
            self._banned[ip] = ban_until
            self._save_banlist()
            self.log.info(f"[security] ⚠️ IP {ip} 触发扫描检测，封禁至 {time.ctime(ban_until)}")
            del self._connections[ip]  # 封禁后无需保留连接记录
            return False
        return True

    def _load_banlist(self):
        try:
            if os.path.exists(self._banlist_path):
                with open(self._banlist_path, "r") as f:
                    data = json.load(f)
                    self._banned = {ip: until for ip, until in data.items() if until > time.time()}
        except Exception:
            pass

    def _save_banlist(self):
        os.makedirs(os.path.dirname(self._banlist_path), exist_ok=True)
        with open(self._banlist_path, "w") as f:
            json.dump(self._banned, f, indent=2)

    # ============================================================
    # 工具
    # ============================================================

    @staticmethod
    def _init_json_list(path: str):
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f)

    @staticmethod
    def _read_json_list(path: str) -> list:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []
