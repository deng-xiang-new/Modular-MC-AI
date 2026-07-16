"""
命令执行器 Mod
封装 Minecraft 指令发送，提供统一的指令接口。
其他 Mod 可通过此 Mod 的 API 或直接通过连接对象发送指令。
"""

from core.mod_api import ModBase, CoreServices


class CommandExecutorMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "command_executor"

    @property
    def mod_version(self) -> str:
        return "1.0.0"

    @property
    def mod_description(self) -> str:
        return "Minecraft 指令发送封装"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        self.log.info("[command_executor] 命令执行器已就绪")

    def on_disable(self) -> None:
        pass

    # ============================================================
    # 公共 API
    # ============================================================

    @staticmethod
    def _clean_text(text: str, max_len: int = 400) -> str:
        """清理文本以适配 Minecraft 消息限制。"""
        clean = text.replace("\n", " ").replace('"', "'").replace("\\", "")
        if len(clean) > max_len:
            clean = clean[:max_len - 3] + "..."
        return clean

    async def say(self, conn, message: str, prefix: str = None) -> None:
        """在游戏公屏发送消息（不等待响应）。"""
        clean_msg = self._clean_text(message)
        if prefix:
            cmd = f'say §b[{prefix}] §f{clean_msg}'
        else:
            cmd = f'say §f{clean_msg}'
        await conn.send_command_fire_and_forget(cmd)

    async def tell(self, conn, player_name: str, message: str, prefix: str = None) -> None:
        """向指定玩家发送私密消息（不等待响应）。"""
        clean_msg = self._clean_text(message)
        if prefix:
            text = f'§b[{prefix}] §f{clean_msg}'
        else:
            text = f'§f{clean_msg}'
        cmd = f'tellraw {player_name} {{"rawtext":[{{"text":"{text}"}}]}}'
        await conn.send_command_fire_and_forget(cmd)

    async def title(self, conn, player_name: str, title_text: str, subtitle_text: str = "") -> None:
        """向玩家显示标题。"""
        clean_title = title_text.replace('"', "'").replace("\n", " ")
        await conn.send_command_fire_and_forget(
            f'titleraw {player_name} title {{"rawtext":[{{"text":"{clean_title}"}}]}}'
        )
        if subtitle_text:
            clean_sub = subtitle_text.replace('"', "'").replace("\n", " ")
            await conn.send_command_fire_and_forget(
                f'titleraw {player_name} subtitle {{"rawtext":[{{"text":"{clean_sub}"}}]}}'
            )
