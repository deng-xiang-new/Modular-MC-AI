"""
时间系统 Mod
提供 UTC+8 时间服务，供其他 Mod 调用以注入时间上下文。
"""

from datetime import datetime, timezone, timedelta

from core.mod_api import ModBase, CoreServices

TZ_UTC8 = timezone(timedelta(hours=8))


class TimeSystemMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "time_system"

    @property
    def mod_version(self) -> str:
        return "1.0.0"

    @property
    def mod_description(self) -> str:
        return "提供 UTC+8 时间信息"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        self.log.info("[time_system] 时间系统已就绪")

    def on_disable(self) -> None:
        pass

    # ============================================================
    # 公共 API
    # ============================================================

    @staticmethod
    def get_current_time_str() -> str:
        """获取当前 UTC+8 时间的格式化字符串。"""
        now = datetime.now(TZ_UTC8)
        return now.strftime("%Y年%m月%d日 %H:%M:%S (UTC+8)")

    @staticmethod
    def get_datetime() -> datetime:
        """获取当前 UTC+8 datetime 对象。"""
        return datetime.now(TZ_UTC8)
