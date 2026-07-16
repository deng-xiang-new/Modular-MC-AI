"""
Mod API — 统一 Mod 接口规范
============================
所有 mods/ 下的定制模块必须继承 ModBase 并实现相应生命周期方法。

核心设计原则：
  - Mod 不能直接访问 core 内部实现细节
  - Mod 通过 CoreServices 获取核心服务（事件总线、WebSocket、AI、日志等）
  - 所有跨模块交互必须走事件总线
  - Mod 必须声明完整的元信息（名称、版本、描述、依赖），否则不会被加载
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List
import logging


# ============================================================
# Mod 状态数据类
# ============================================================

@dataclass
class ModStatus:
    """
    Mod 运行时状态快照，用于状态查询和依赖分析。
    """
    name: str = ""                      # 唯一标识名
    version: str = ""                   # 语义化版本号
    description: str = ""               # 简介
    dependencies: List[str] = field(default_factory=list)      # 强依赖
    optional_dependencies: List[str] = field(default_factory=list)  # 可选依赖
    enabled: bool = False               # 是否已启用
    missing_deps: List[str] = field(default_factory=list)      # 缺失的强依赖
    missing_optional_deps: List[str] = field(default_factory=list)  # 缺失的可选依赖
    loaded_at: str = ""                 # 加载时间（ISO格式）
    error: Optional[str] = None         # 加载/启用时的错误信息


# ============================================================
# 提供给 Mod 的统一服务接口（门面模式）
# ============================================================

class CoreServices:
    """
    Mod 可见的核心服务集合。
    由 main.py 初始化后注入到每个 Mod。
    """

    def __init__(self):
        self.event_bus: Any = None          # EventBus 实例
        self.scheduler: Any = None          # Scheduler 实例
        self.ai_client: Any = None          # AIClient 实例
        self.config: dict = {}              # 全局配置
        self.server_log: logging.Logger = None
        self.error_log: logging.Logger = None
        self.ai_name: str = "AI"            # AI 名字
        self._mods: Dict[str, 'ModBase'] = {}   # mod_name -> Mod 实例
        self._mod_statuses: Dict[str, ModStatus] = {}  # mod_name -> ModStatus

    def get_mod(self, name: str):
        """获取另一个已加载的 Mod 实例。"""
        return self._mods.get(name)

    def get_mod_status(self, name: str) -> Optional[ModStatus]:
        """获取指定 Mod 的状态快照。"""
        return self._mod_statuses.get(name)

    def get_all_mod_statuses(self) -> Dict[str, ModStatus]:
        """获取所有 Mod 的状态快照（含加载失败的）。"""
        return dict(self._mod_statuses)

    def status_summary(self) -> str:
        """
        生成终端友好的 Mod 状态摘要字符串。
        供 mcctl /mod-status 命令和 SIGUSR2 信号处理调用。
        """
        statuses = self._mod_statuses
        if not statuses:
            return "⚠ 无 Mod 状态信息（服务可能尚未启动或 Mod 加载失败）"

        lines = []
        lines.append("=" * 72)
        lines.append(f"{'Mod 名称':<22} {'版本':<10} {'状态':<8} {'依赖':<20} {'备注'}")
        lines.append("-" * 72)

        for name, st in sorted(statuses.items()):
            state = "✓ 启用" if st.enabled else "✗ 未启用"
            deps = ", ".join(st.dependencies) if st.dependencies else "无"
            # 可选依赖追加显示
            if st.optional_dependencies:
                deps += f" [+{', '.join(st.optional_dependencies)}]"
            note = ""
            if st.error:
                note = f"❌ {st.error}"
            elif st.missing_deps:
                note = f"⚠ 缺强依赖: {', '.join(st.missing_deps)}"
            elif st.missing_optional_deps:
                note = f"ℹ 已降级: {', '.join(st.missing_optional_deps)} 缺失"
            elif not st.enabled:
                note = "未启用"
            lines.append(f"{name:<22} {st.version:<10} {state:<8} {deps:<20} {note}")

        lines.append("-" * 72)
        enabled_count = sum(1 for s in statuses.values() if s.enabled)
        lines.append(f"总计: {len(statuses)} 个 Mod | 已启用: {enabled_count} | "
                     f"异常: {sum(1 for s in statuses.values() if s.error)}")
        lines.append("=" * 72)
        return "\n".join(lines)


# ============================================================
# Mod 基类
# ============================================================

class ModBase(ABC):
    """
    所有 Mod 的抽象基类。

    生命周期：
      1. __init__()          - 实例化
      2. 元信息验证           - 名称/版本/描述/依赖必须合规
      3. on_enable(services) - 核心服务就绪后调用（注册事件、启动定时任务等）
      4. on_disable()        - 关闭前调用（清理资源）

    子类必须实现：
      - mod_name : str              — 唯一标识名
      - mod_version : str           — 语义化版本号
      - mod_description : str       — 一句话描述
      - mod_dependencies : list     — 依赖的其他 Mod 名称（至少为空列表 []）
      - on_enable(services)         — 启用逻辑
      - on_disable()                — 停用逻辑

    ⚠ 规范要求：元信息属性（名称、版本号、简介）必须为非空字符串，
      依赖必须为 list 类型，否则 Mod 不会被加载。
    """

    def __init__(self):
        self._services: Optional[CoreServices] = None
        self._enabled = False

    # ----- 子类必须定义 -----
    @property
    @abstractmethod
    def mod_name(self) -> str: ...
    @property
    @abstractmethod
    def mod_version(self) -> str: ...
    @property
    @abstractmethod
    def mod_description(self) -> str: ...

    # ----- 依赖声明（必须显式定义） -----
    @property
    def mod_dependencies(self) -> list:
        """
        返回此 Mod **强依赖**的其他 Mod 名称列表。
        若强依赖的 Mod 缺失，ModLoader 会记录 error 日志，但 Mod 仍会被加载
        （开发者应在 on_enable / 运行时做防御性 None 检查来实现降级）。
        默认空列表表示无强依赖。
        """
        return []

    @property
    def mod_optional_dependencies(self) -> list:
        """
        返回此 Mod **可选依赖**的其他 Mod 名称列表。
        可选依赖缺失时，ModLoader 只记录 info 日志（不告警），
        Mod 在运行时检测并优雅降级对应功能。
        默认空列表表示无可选依赖。
        """
        return []

    @abstractmethod
    def on_enable(self, services: CoreServices) -> None:
        """核心服务就绪，执行初始化逻辑。"""
        ...

    @abstractmethod
    def on_disable(self) -> None:
        """系统关闭，执行清理逻辑。"""
        ...

    # ----- 元信息验证 -----
    def validate_manifest(self) -> Optional[str]:
        """
        验证 Mod 元信息合规性。
        
        Returns:
            若合规返回 None，否则返回错误描述字符串。
        """
        # 名称验证
        name = self.mod_name
        if not name or not isinstance(name, str) or not name.strip():
            return "mod_name 必须为非空字符串"
        # 版本号验证
        version = self.mod_version
        if not version or not isinstance(version, str) or not version.strip():
            return "mod_version 必须为非空字符串"
        # 简介验证
        desc = self.mod_description
        if not desc or not isinstance(desc, str) or not desc.strip():
            return "mod_description 必须为非空字符串"
        # 强依赖验证
        deps = self.mod_dependencies
        if not isinstance(deps, list):
            return "mod_dependencies 必须为 list 类型"
        # 可选依赖验证
        opt_deps = self.mod_optional_dependencies
        if not isinstance(opt_deps, list):
            return "mod_optional_dependencies 必须为 list 类型"
        return None

    # ----- 便捷属性 -----
    @property
    def services(self) -> CoreServices:
        if not self._services:
            raise RuntimeError(f"Mod '{self.mod_name}' 尚未启用，services 不可用")
        return self._services

    @property
    def log(self) -> logging.Logger:
        return self.services.server_log

    @property
    def config(self) -> dict:
        return self.services.config

    @property
    def event_bus(self):
        return self.services.event_bus

    @property
    def scheduler(self):
        return self.services.scheduler

    @property
    def ai_client(self):
        return self.services.ai_client

    # ----- 内部方法（由 ModLoader 调用） -----
    def _enable(self, services: CoreServices) -> None:
        self._services = services
        self._enabled = True
        self.on_enable(services)
        self.log.info(f"[Mod] {self.mod_name} v{self.mod_version} 已启用")

    def _disable(self) -> None:
        if self._enabled:
            self.on_disable()
            self._enabled = False
