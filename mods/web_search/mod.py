# -*- coding: utf-8 -*-
"""
智能联网搜索 Mod (高并发+数据持久化终极版)
1. 缓存数据统一持久化至 /opt/modular-mc-ai/data/web_search/ 目录。
2. 支持热重载与重启后的缓存继承，无惧数据丢失。
3. 包含本地分词拦截与 10 分钟空查询防穿透保护。
"""

import os
import json
import time
import re
from typing import Dict, Tuple, Optional
import httpx
from core.mod_api import ModBase, CoreServices


class WebSearchMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "web_search"

    @property
    def mod_version(self) -> str:
        return "1.3.0"  # 升级版本至 1.3.0 (持久化版)

    @property
    def mod_description(self) -> str:
        return "智能分析玩家问题，支持本地分词、10分钟空查询保护及 data 目录数据持久化"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        self._wiki_api_url = "https://minecraft.fandom.com/zh/api.php"
        
        # --- 缓存时间配置 ---
        self.decision_ttl = 300      # 玩家提问判定缓存：5分钟
        self.wiki_ttl = 1800         # 有效 Wiki 词条缓存：30分钟
        self.wiki_empty_ttl = 600    # 查无此词条的禁用时间：10 分钟

        # --- 持久化路径配置 ---
        # 统一规范放在项目的 data 目录下
        self.data_dir = os.path.join("data", "web_search")
        self.decision_cache_path = os.path.join(self.data_dir, "decision_cache.json")
        self.wiki_cache_path = os.path.join(self.data_dir, "wiki_cache.json")

        # 确保数据目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # --- 初始化并加载缓存 ---
        self._decision_cache = self._load_json_cache(self.decision_cache_path)
        self._wiki_cache = self._load_json_cache(self.wiki_cache_path)

        # --- 本地快速分词匹配规则 ---
        self._local_rules = [
            re.compile(r"([\u4e00-\u9fa5\w\s\-]+?)(?:怎么(?:合成|做|得|用|召唤|寻找|去|弄|获取|打))"),
            re.compile(r"(?:怎么|如何)(?:合成|制作|使用|召唤|去|获取|打)([\u4e00-\u9fa5\w\s\-]+)")
        ]

        # 注册定时清理并保存的任务（每 10 分钟清理一次过期缓存，并写入硬盘）
        self.scheduler.schedule_periodic(
            name="clear_and_save_search_cache",
            interval_seconds=600,
            coro_func=self._clear_and_save_cache_task
        )

        self.log.info(
            f"[web_search] 持久化版检索模块已就绪。已加载判定缓存 {len(self._decision_cache)} 条，"
            f"Wiki 缓存 {len(self._wiki_cache)} 条。"
        )

    def on_disable(self) -> None:
        # 模块停用时，执行最后一次保存，防止内存数据丢失
        self.scheduler.cancel("clear_and_save_search_cache")
        self._save_all_cache()
        self._decision_cache.clear()
        self._wiki_cache.clear()

    # ============================================================
    # 核心公共 API
    # ============================================================

    async def check_and_search(self, user_prompt: str) -> str:
        """判断并检索 Wiki"""
        # 1. 尝试本地分词规则匹配
        local_keywords = self._match_local_rules(user_prompt)
        
        if local_keywords:
            self.log.info(f"[web_search] 🚀 命中本地分词规则。提取关键词: {local_keywords}")
            decision = f"YES|{local_keywords}"
        else:
            decision = await self._get_ai_decision_with_cache(user_prompt)
        
        if not decision or "NO" in decision.upper() or "否" in decision:
            return "NO"

        # 2. 提取关键词
        keywords = self._extract_keywords(decision)
        if not keywords:
            return "NO"

        # 3. 检索 Wiki
        wiki_content = await self._get_wiki_with_cache(keywords)
        if wiki_content and wiki_content != "NO":
            return wiki_content
            
        return "NO"

    # ============================================================
    # 本地分词匹配器
    # ============================================================

    def _match_local_rules(self, prompt: str) -> Optional[str]:
        clean_prompt = prompt.strip()
        for rule in self._local_rules:
            match = rule.search(clean_prompt)
            if match:
                keyword = match.group(1).strip()
                if 1 < len(keyword) < 15 and not keyword.isdigit():
                    return keyword
        return None

    # ============================================================
    # 缓存读写代理
    # ============================================================

    async def _get_ai_decision_with_cache(self, prompt: str) -> str:
        now = time.time()
        
        if prompt in self._decision_cache:
            decision, expire_time = self._decision_cache[prompt]
            if now < expire_time:
                self.log.info(f"[web_search] 判定缓存命中: '{prompt}'")
                return decision

        decision = await self._ask_ai_for_decision(prompt)
        self._decision_cache[prompt] = (decision, now + self.decision_ttl)
        return decision

    async def _get_wiki_with_cache(self, keywords: str) -> str:
        now = time.time()
        
        if keywords in self._wiki_cache:
            content, expire_time = self._wiki_cache[keywords]
            if now < expire_time:
                if content == "NO":
                    self.log.info(f"[web_search] 🛡 处于空查询保护期，拦截对: '{keywords}' 的请求")
                else:
                    self.log.info(f"[web_search] Wiki 缓存命中: '{keywords}'")
                return content

        wiki_content = await self._search_minecraft_wiki(keywords)
        
        if wiki_content:
            self._wiki_cache[keywords] = (wiki_content, now + self.wiki_ttl)
        else:
            self.log.warning(f"[web_search] Wiki 未检索到结果。启用 10 分钟防穿透保护: '{keywords}'")
            self._wiki_cache[keywords] = ("NO", now + self.wiki_empty_ttl)
            
        return wiki_content

    # ============================================================
    # 缓存持久化底座 (JSON 读写)
    # ============================================================

    def _load_json_cache(self, file_path: str) -> dict:
        """从文件加载缓存"""
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.log.error(f"[web_search] 读取缓存文件失败 {file_path}: {e}")
        return {}

    def _save_all_cache(self) -> None:
        """将缓存强制写入硬盘"""
        try:
            with open(self.decision_cache_path, "w", encoding="utf-8") as f:
                json.dump(self._decision_cache, f, ensure_ascii=False, indent=2)
            with open(self.wiki_cache_path, "w", encoding="utf-8") as f:
                json.dump(self._wiki_cache, f, ensure_ascii=False, indent=2)
            self.log.info("[web_search] 💾 检索缓存数据已成功同步保存至 data/web_search/ 目录")
        except Exception as e:
            self.log.error(f"[web_search] 写入缓存文件失败: {e}")

    async def _clear_and_save_cache_task(self) -> None:
        """定时任务：清理过期内存缓存，并持久化剩余数据"""
        now = time.time()
        
        # 清理过期的内存数据
        before_dec = len(self._decision_cache)
        self._decision_cache = {k: v for k, v in self._decision_cache.items() if v[1] > now}
        dec_cleaned = before_dec - len(self._decision_cache)

        before_wiki = len(self._wiki_cache)
        self._wiki_cache = {k: v for k, v in self._wiki_cache.items() if v[1] > now}
        wiki_cleaned = before_wiki - len(self._wiki_cache)

        if dec_cleaned > 0 or wiki_cleaned > 0:
            self.log.info(f"[web_search] 定时清理过期缓存: 判定 {dec_cleaned} 条，Wiki {wiki_cleaned} 条")

        # 将筛选后的有效缓存持久化至本地硬盘
        self._save_all_cache()

    # ============================================================
    # 底层 API 调用
    # ============================================================

    async def _ask_ai_for_decision(self, prompt: str) -> str:
        system_instruction = (
            "你是一个判定器。判断玩家的问题是否需要查询 Minecraft 官方 Wiki 知识库才能准确回答。\n"
            "一些常识、闲聊、情感对话不需要查询（如‘你好’、‘今天天气真好’）。\n"
            "涉及到合成表、方块属性、特定生物特性、游戏更新内容、指令用法等具体硬核游戏设定时，需要查询。\n\n"
            "【输出格式规范】\n"
            "- 如果不需要查询，必须且只能回复：NO\n"
            "- 如果需要查询，必须回复：YES|检索关键词1 检索关键词2\n"
            "（关键词应为简短的 MC 游戏术语，不要带特殊符号，用空格隔开）"
        )
        try:
            decision = await self.ai_client.chat([
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"玩家问题：{prompt}"}
            ])
            return decision.strip()
        except Exception as e:
            self.log.error(f"[web_search] AI 预决策请求失败: {e}")
            return "NO"

    def _extract_keywords(self, decision_text: str) -> str:
        if "|" in decision_text:
            parts = decision_text.split("|", 1)
            if len(parts) > 1:
                return parts[1].strip()
        return ""

    async def _search_minecraft_wiki(self, keywords: str) -> str:
        headers = {"User-Agent": "Modular-MC-AI-Bot/1.0 (Contact: admin@localhost)"}
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            try:
                search_params = {
                    "action": "query",
                    "list": "search",
                    "srsearch": keywords,
                    "format": "json",
                    "utf8": 1,
                    "srlimit": 1
                }
                resp = await client.get(self._wiki_api_url, params=search_params)
                search_data = resp.json()
                search_results = search_data.get("query", {}).get("search", [])
                
                if not search_results:
                    return ""
                
                best_page_title = search_results[0]["title"]
                self.log.info(f"[web_search] 匹配到最相关词条: {best_page_title}")

                content_params = {
                    "action": "query",
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "titles": best_page_title,
                    "format": "json",
                    "utf8": 1
                }
                resp_content = await client.get(self._wiki_api_url, params=content_params)
                content_data = resp_content.json()
                pages = content_data.get("query", {}).get("pages", {})
                
                for page_id, page_info in pages.items():
                    extract = page_info.get("extract", "").strip()
                    if extract:
                        return f"【Minecraft Wiki 知识库参考 (关于 {best_page_title})】\n{extract[:600]}"
                
            except Exception as e:
                self.log.error(f"[web_search] 请求 Minecraft Wiki 异常: {e}")
                
        return ""