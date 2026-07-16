"""
聊天处理 Mod
处理 @ai 前缀消息，调用 AI，返回结果。
这是核心交互入口 Mod。
"""

import asyncio
from core.mod_api import ModBase, CoreServices


class ChatHandlerMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "chat_handler"

    @property
    def mod_version(self) -> str:
        return "1.0.0"

    @property
    def mod_description(self) -> str:
        return "处理 @ai 消息，调用 AI 并返回回复"

    @property
    def mod_dependencies(self) -> list:
        return []  # 无强依赖 —— 任何模块缺失都不影响核心@ai响应

    @property
    def mod_optional_dependencies(self) -> list:
        return ["memory_system", "security", "time_system", "command_executor"]

    def on_enable(self, services: CoreServices) -> None:
        # 注册事件处理器（父类已通过 _enable 绑定 services）
        services.event_bus.subscribe("PlayerMessage", self._on_player_message)
        self.log.info("[chat_handler] 已注册 PlayerMessage 处理器")

    def on_disable(self) -> None:
        self.services.event_bus.unsubscribe("PlayerMessage", self._on_player_message)

    # ============================================================
    # 消息处理
    # ============================================================

    async def _on_player_message(self, event_data: dict):
        body = event_data.get("body", {})
        sender = body.get("sender", "")
        message = body.get("message", "")
        conn = event_data.get("connection")

        if not sender or sender == "外部的" or sender == "外部":
            return
        if not message.strip():
            return

        self.log.info(f"[聊天] {sender}: {message}")

        # ---- 安全检查（白名单 / 黑名单） ----
        try:
            sec_mod = self._find_mod("security")
            if sec_mod and not sec_mod.check_player(sender):
                self.log.info(f"[chat_handler] 玩家 {sender} 未通过安全策略，忽略")
                return
        except Exception as e:
            self.services.error_log.error(
                f"[chat_handler] 安全策略检查异常 [{sender}]: {type(e).__name__}: {e}"
            )

        # 检测 @ai 呼出
        if not self._is_ai_call(message):
            return

        user_prompt = self._extract_prompt(message)
        if not user_prompt:
            if conn:
                await self._safe_say(conn, f"@{sender} 有什么需要帮助的吗？在聊天栏输入 @ai 加上你的问题就行啦。")
            return

        self.log.info(f"[AI触发] {sender}: {user_prompt}")

        if conn:
            asyncio.create_task(self._process_ai_response(conn, sender, user_prompt))

    # ============================================================
    # AI 处理
    # ============================================================

    async def _process_ai_response(self, conn, sender: str, user_prompt: str):
        try:
            memory_mod = self._find_mod("memory_system")

            # 构建系统提示词（异步，只含全服事件+时间，不含文件历史）
            system_prompt = await self._build_system_prompt(sender)

            # 获取内存上下文（最近 N 轮对话，由 ContextWindow 全权管理）
            history = []
            if memory_mod and hasattr(memory_mod, 'get_context_messages'):
                history = await memory_mod.get_context_messages(sender)
                history = [m for m in history if m["role"] != "system"]

            # 调用 AI
            messages = [{"role": "system", "content": system_prompt}] + history
            messages.append({"role": "user", "content": user_prompt})
            ai_reply = await self.ai_client.chat(messages)

            # 发送到游戏（使用 JSON 安全转义，保留换行可读性）
            await self._safe_say(conn, f"@{sender}: {ai_reply}")
            self.log.info(f"[AI回复] -> {sender}: {ai_reply[:80]}...")

            # 保存到持久化存储（异步）
            if memory_mod and hasattr(memory_mod, 'save_message'):
                await memory_mod.save_message(sender, user_prompt, "user")
                await memory_mod.save_message(sender, ai_reply, "assistant")

            # 更新内存上下文
            if memory_mod and hasattr(memory_mod, 'add_to_context'):
                memory_mod.add_to_context(sender, "user", user_prompt)
                memory_mod.add_to_context(sender, "assistant", ai_reply)

        except Exception as e:
            self.services.error_log.error(f"[chat_handler] AI处理异常 [{sender}]: {e}", exc_info=True)
            try:
                await self._safe_say(conn, f"@{sender} 抱歉，处理你的消息时出了点小问题...")
            except Exception:
                pass

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _is_ai_call(message: str) -> bool:
        return message.startswith("@ai ") or message == "@ai"

    @staticmethod
    def _extract_prompt(message: str) -> str:
        if message.startswith("@ai "):
            return message[4:].strip()
        if message == "@ai":
            return ""
        return message[3:].strip()

    async def _safe_say(self, conn, text: str):
        """安全发送公屏消息，使用 tellraw + JSON 序列化自动转义。"""
        import json
        # 截断过长消息（MC 限制约 512 字符，留余量）
        if len(text) > 480:
            text = text[:477] + "..."
        rawtext = [{"text": f"§b[{self.services.ai_name}] §f{text}"}]
        cmd = f"tellraw @a {json.dumps({'rawtext': rawtext}, ensure_ascii=False)}"
        await conn.send_command_fire_and_forget(cmd)

    async def _build_system_prompt(self, player_name: str) -> str:
        """动态构建系统提示词。只含全服事件和当前时间，不含玩家文件历史。"""
        services = self.services
        ai_name = services.ai_name

        prompt = (
            f'你是"{ai_name}"，一个通过 WebSocket 连接到 Minecraft 基岩版服务器的 AI 智能助手。'
            f'你以数据流形态存在于服务器后台，没有实体形态。\n'
            f'【核心规则】\n'
            f'1. 不说自己能做任何游戏内操作，只能通过文字提供建议和陪伴。\n'
            f'2. 回答必须简洁、口语化，控制在 2-3 句话内。\n'
            f'3. 绝对不要使用 Markdown 格式，只输出纯文本。\n'
            f'4. 你是服务器的观察者，不是玩家。\n'
        )

        # 获取时间
        time_mod = self._find_mod("time_system")
        if time_mod and hasattr(time_mod, 'get_current_time_str'):
            prompt += f"\n【当前时间】{time_mod.get_current_time_str()}"

        # 获取全服事件摘要（不含玩家个人历史——由 ContextWindow 管理对话上下文）
        memory_mod = self._find_mod("memory_system")
        if memory_mod and hasattr(memory_mod, 'get_server_memory_summary'):
            sm = await memory_mod.get_server_memory_summary()
            if sm:
                prompt += f"\n【服务器事件背景】{sm}"

        prompt += f'\n\n请以"{ai_name}"的身份回答玩家 {player_name} 的问题。'
        return prompt

    def _find_mod(self, name: str):
        """查找其他已加载的 Mod 实例（跨 Mod 通信）。"""
        return self.services.get_mod(name)
