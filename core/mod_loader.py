"""
Mod 加载器 — 拓扑排序启用 + 热重载防幽灵引用
=============================================
负责扫描、实例化、拓扑排序启用、反向停用、热重载所有 mods/ 下的 Mod。

关键安全机制：
  1. 拓扑排序（Topological Sort）—— 被依赖者先启用；缺失依赖排在最后
  2. 热重载防幽灵对象 —— reload_all() 主动清空 EventBus + Scheduler
  3. 停用与启用的严格顺序 —— 反向拓扑停用，正向拓扑启用
"""

import os
import sys
import importlib
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import List, Optional, Dict, Set

from core.mod_api import ModBase, CoreServices, ModStatus


class ModLoader:
    """Mod 生命周期管理器，支持拓扑排序和热重载。"""

    def __init__(self, mods_dir: str):
        self._mods_dir = mods_dir
        self._mods: List[ModBase] = []
        self._services: Optional[CoreServices] = None

    # ================================================================
    # 发现
    # ================================================================

    def discover(self) -> List[type]:
        """扫描 mods/ 目录，返回所有 ModBase 子类。"""
        mod_classes = []
        if not os.path.isdir(self._mods_dir):
            return mod_classes

        parent = os.path.dirname(self._mods_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        for entry in sorted(os.listdir(self._mods_dir)):
            mod_path = os.path.join(self._mods_dir, entry)
            if not os.path.isdir(mod_path):
                continue
            if entry.startswith("_") or entry.startswith("."):
                continue

            init_file = os.path.join(mod_path, "__init__.py")
            main_file = os.path.join(mod_path, "mod.py")
            candidate = main_file if os.path.isfile(main_file) else init_file
            if not os.path.isfile(candidate):
                continue

            try:
                module_name = f"mods.{entry}.{os.path.splitext(os.path.basename(candidate))[0]}"
                mod = importlib.import_module(module_name)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (isinstance(attr, type) and
                        issubclass(attr, ModBase) and
                        attr is not ModBase):
                        mod_classes.append(attr)
            except Exception as e:
                if self._services and self._services.server_log:
                    self._services.server_log.error(
                        f"[ModLoader] 发现阶段加载 '{entry}' 失败: {e}"
                    )
                else:
                    print(f"[ModLoader] 加载 '{entry}' 失败: {e}")

        return mod_classes

    # ================================================================
    # 拓扑排序
    # ================================================================

    def _topological_order(self, instances: List[ModBase]) -> List[ModBase]:
        """
        按依赖关系拓扑排序（Kahn's algorithm）。

        规则：
          - 若 Mod A 依赖 Mod B，则 B 的 on_enable 先于 A 执行
          - 无依赖的 Mod 排在最前
          - 缺失依赖的 Mod：对其未依赖到的节点不建边，但将该 Mod 自身入度 +1，
            模拟「被一个不存在的节点依赖」的效果，迫使它排在最后
          - 循环依赖的剩余节点：按 mod_name 字母序追加（稳定打破），并记录循环路径

        Returns:
            排序后的 Mod 列表（全新列表，不修改传入的 instances）。
        """
        name_to_instance: Dict[str, ModBase] = {m.mod_name: m for m in instances}
        loaded: Set[str] = set(name_to_instance.keys())

        # 入度表 + 邻接表（被依赖者 → 依赖者）
        in_degree: Dict[str, int] = {m.mod_name: 0 for m in instances}
        adj: Dict[str, List[str]] = {m.mod_name: [] for m in instances}

        for m in instances:
            has_missing_dep = False
            for dep in m.mod_dependencies:
                if dep not in loaded:
                    # 缺失依赖：不建立边，但该节点入度 +1，使其排在最后
                    has_missing_dep = True
                    continue
                # B → A（A 依赖 B，所以 B 先被启用）
                adj[dep].append(m.mod_name)
                in_degree[m.mod_name] += 1

            if has_missing_dep:
                # 人工 +1 入度：模拟被不存在的节点依赖，确保排在最后
                in_degree[m.mod_name] += 1

        # Kahn's BFS
        queue: deque[str] = deque()
        for m in instances:
            if in_degree[m.mod_name] == 0:
                queue.append(m.mod_name)

        sorted_names: List[str] = []
        while queue:
            name = queue.popleft()
            sorted_names.append(name)
            for neighbor in adj.get(name, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 循环依赖或由于人工入度无法归零的剩余节点
        remaining = [m.mod_name for m in instances if m.mod_name not in sorted_names]
        if remaining:
            svc = self._services
            # 按字母序稳定打破，而非随机顺序
            remaining.sort()

            # 检测是否真正存在循环（而不仅仅是人工入度导致）
            cycle_info = self._detect_cycle(adj, remaining)
            if cycle_info:
                msg = (f"[ModLoader] ⚠ 检测到循环依赖 — 循环路径: {cycle_info}，"
                       f"将按字母序启用以打破循环")
                if svc:
                    svc.error_log.error(msg)
                    svc.server_log.warning(msg)
            else:
                msg = (f"[ModLoader] ⚠ 部分 Mod 存在缺失依赖或位于循环链尾部: {remaining}，"
                       f"将按字母序遍历启用")
                if svc:
                    svc.server_log.warning(msg)

            sorted_names.extend(remaining)

        # 映射回实例
        ordered = []
        for name in sorted_names:
            inst = name_to_instance.get(name)
            if inst:
                ordered.append(inst)
        return ordered

    def _detect_cycle(self, adj: Dict[str, List[str]], nodes: List[str]) -> Optional[str]:
        """
        检测 nodes 中是否存在真正的循环依赖。
        只考虑 nodes 内部的边。

        Returns:
            循环路径字符串，若无真正循环返回 None。
        """
        nodes_set = set(nodes)
        visited: Set[str] = set()
        stack: List[str] = []

        def dfs(node: str) -> Optional[str]:
            if node in stack:
                idx = stack.index(node)
                return " → ".join(stack[idx:] + [node])
            if node in visited:
                return None
            visited.add(node)
            stack.append(node)
            for neighbor in adj.get(node, []):
                if neighbor not in nodes_set:
                    continue
                result = dfs(neighbor)
                if result:
                    return result
            stack.pop()
            return None

        for n in nodes:
            if n not in visited:
                result = dfs(n)
                if result:
                    return result
        return None

    # ================================================================
    # 全量加载（含拓扑排序 + 状态追踪）
    # ================================================================

    def load_all(self, services: CoreServices) -> None:
        """
        扫描并启用所有 Mod，按拓扑顺序先启用被依赖者。

        三阶段：
          1. 实例化 + 元信息验证 + 注册到 services
          2. 依赖验证 + 拓扑排序
          3. 按拓扑顺序依次启用
        """
        self._services = services
        now_iso = datetime.now(timezone.utc).isoformat()

        # ---- 阶段 1：实例化、验证、注册 ----
        instances: List[ModBase] = []
        for cls in self.discover():
            try:
                instance = cls()
                err = instance.validate_manifest()
                if err:
                    status = ModStatus(
                        name=getattr(instance, 'mod_name', cls.__name__),
                        version=getattr(instance, 'mod_version', '?'),
                        description=getattr(instance, 'mod_description', ''),
                        dependencies=getattr(instance, 'mod_dependencies', []),
                        enabled=False,
                        loaded_at=now_iso,
                        error=f"元信息验证失败: {err}"
                    )
                    services._mod_statuses[status.name or cls.__name__] = status
                    services.error_log.error(
                        f"[ModLoader] ⚠ {cls.__name__} 跳过加载 — {err}"
                    )
                    services.server_log.warning(
                        f"[ModLoader] 跳过 '{cls.__name__}': {err}"
                    )
                    continue
                instances.append(instance)
            except Exception as e:
                services.error_log.error(
                    f"[ModLoader] 实例化 '{cls.__name__}' 失败: {e}\n{traceback.format_exc()}"
                )

        # 注册到 services._mods 和 _mod_statuses
        for instance in instances:
            name = instance.mod_name
            services._mods[name] = instance
            services._mod_statuses[name] = ModStatus(
                name=name,
                version=instance.mod_version,
                description=instance.mod_description,
                dependencies=list(instance.mod_dependencies),
                optional_dependencies=list(getattr(instance, 'mod_optional_dependencies', []) or []),
                enabled=False,
                loaded_at=now_iso
            )

        # ---- 阶段 2：依赖验证 + 拓扑排序 ----
        self._validate_dependencies(instances, services)
        ordered = self._topological_order(instances)

        # 【关键修复】在这里赋值 self._mods，后续 enable/unload 才能正确迭代
        self._mods = list(ordered)

        # ---- 阶段 3：按拓扑顺序启用 ----
        for instance in ordered:
            try:
                deps_ready = self._check_deps_ready(instance, services)
                if not deps_ready:
                    services.error_log.warning(
                        f"[ModLoader] '{instance.mod_name}' 的依赖尚未就绪，"
                        f"尝试启用可能导致运行时错误"
                    )

                instance._enable(services)
                status = services._mod_statuses.get(instance.mod_name)
                if status:
                    status.enabled = True
            except Exception as e:
                services.error_log.error(
                    f"[ModLoader] 启用 '{instance.mod_name}' 失败: {e}\n{traceback.format_exc()}"
                )
                status = services._mod_statuses.get(instance.mod_name)
                if status:
                    status.error = f"启用失败: {e}"

        order_str = " → ".join(f"{m.mod_name}" for m in ordered)
        services.server_log.info(
            f"[ModLoader] 已加载 {len(instances)} 个 Mod（顺序: {order_str}）"
        )

    def _check_deps_ready(self, instance: ModBase, services: CoreServices) -> bool:
        """检查实例的所有声明依赖是否已启用。"""
        for dep_name in instance.mod_dependencies:
            dep = services._mods.get(dep_name)
            if dep is None or not dep._enabled:
                return False
        return True

    def _validate_dependencies(self, instances: list, services: 'CoreServices') -> None:
        """验证所有 Mod 的强依赖和可选依赖关系。"""
        loaded_names = {inst.mod_name for inst in instances}

        for instance in instances:
            # ---- 强依赖 ----
            deps = instance.mod_dependencies
            if deps:
                missing = [d for d in deps if d not in loaded_names]
                status = services._mod_statuses.get(instance.mod_name)
                if status:
                    status.missing_deps = missing
                if missing:
                    services.error_log.error(
                        f"[ModLoader] ⚠ 强依赖缺失 — 模块 '{instance.mod_name}' "
                        f"(v{instance.mod_version}) 强依赖于: {missing}，"
                        f"但它们未安装或未加载。该模块可能出现功能异常，"
                        f"请检查 mods/ 目录或将其降级为可选依赖。"
                    )
                    services.server_log.warning(
                        f"[ModLoader] '{instance.mod_name}' 缺少强依赖: {missing}"
                    )

            # ---- 可选依赖 ----
            opt_deps = getattr(instance, 'mod_optional_dependencies', []) or []
            if opt_deps:
                missing_opt = [d for d in opt_deps if d not in loaded_names]
                status = services._mod_statuses.get(instance.mod_name)
                if status:
                    status.missing_optional_deps = missing_opt
                if missing_opt:
                    services.server_log.info(
                        f"[ModLoader] ℹ '{instance.mod_name}' 可选依赖缺失: {missing_opt}，"
                        f"对应功能将自动降级"
                    )

    # ================================================================
    # 卸载（反向拓扑顺序）
    # ================================================================

    def unload_all(self) -> None:
        """
        按反向拓扑顺序停用所有 Mod，然后彻底从内存中卸载。
        """
        if not self._mods:
            self._clear_module_cache()
            return

        # 反向拓扑：先停用依赖者
        ordered = self._topological_order(list(self._mods))
        reversed_order = list(reversed(ordered))

        for mod in reversed_order:
            try:
                mod._disable()
            except Exception as e:
                if self._services:
                    self._services.server_log.error(
                        f"[ModLoader] 停用 '{mod.mod_name}' 失败: {e}"
                    )

        # ---- 热重载安全：主动清空全局状态，防止幽灵对象 ----
        self._purge_global_state()

        # 清理 services 中的注册
        if self._services:
            for mod in self._mods:
                self._services._mods.pop(mod.mod_name, None)
            self._services._mod_statuses.clear()

        self._clear_module_cache()
        self._mods.clear()

    def _purge_global_state(self) -> None:
        """
        热重载安全关键步骤：主动清空 EventBus 和 Scheduler 中
        所有旧 Mod 注册的 handler 和 task，杜绝幽灵引用。
        """
        svc = self._services
        if not svc:
            return

        # 1. 清空 EventBus
        event_bus = svc.event_bus
        if event_bus and hasattr(event_bus, 'clear_all'):
            before_events = event_bus.list_events()
            before_count = sum(
                len(event_bus._listeners.get(e, [])) for e in before_events
            )
            cleared = event_bus.clear_all()
            if cleared > 0:
                svc.server_log.info(
                    f"[ModLoader] 🧹 热重载清理：EventBus 清除了 {cleared} 个旧 handler "
                    f"（事件类型: {before_events}）"
                )

        # 2. 清空 Scheduler — 使用 clear_all() 而非 stop()
        #    clear_all() 只取消任务不改变 _running 状态，新 Mod 可直接注册
        scheduler = svc.scheduler
        if scheduler and hasattr(scheduler, 'clear_all'):
            task_names = list(scheduler._tasks.keys()) if hasattr(scheduler, '_tasks') else []
            pending_count = len(scheduler._pending) if hasattr(scheduler, '_pending') else 0
            cleared = scheduler.clear_all()
            if cleared > 0:
                svc.server_log.info(
                    f"[ModLoader] 🧹 热重载清理：Scheduler 清除了 {cleared} 个任务 "
                    f"（活跃: {task_names}, 待激活: {pending_count}）"
                )

    def _clear_module_cache(self) -> None:
        """从 sys.modules 中删除所有属于 mods 包的模块缓存。"""
        to_remove = [
            name for name in sys.modules
            if name.startswith("mods.") or name == "mods"
        ]
        for module_name in to_remove:
            del sys.modules[module_name]

    # ================================================================
    # 热重载
    # ================================================================

    def reload_all(self, services: CoreServices) -> int:
        """
        热重载所有 Mod。

        流程：
          1. 反向拓扑停用 + EventBus/Scheduler 清理
          2. 清除 Python 模块缓存
          3. 重新扫描 → 拓扑排序 → 启用
        """
        if services.server_log:
            services.server_log.info("[ModLoader] ♻ 开始热重载所有 Mod ...")
        else:
            print("[ModLoader] ♻ 开始热重载所有 Mod ...")

        self.unload_all()

        # unload_all 中 clear_all() 已清空任务但保留 Scheduler._running = True
        # 无需额外重置，新 Mod 注册任务即可正常运行

        self.load_all(services)

        count = len(self._mods)
        if services.server_log:
            services.server_log.info(f"[ModLoader] ♻ 热重载完成，共 {count} 个 Mod")
        else:
            print(f"[ModLoader] ♻ 热重载完成，共 {count} 个 Mod")
        return count

    # ================================================================
    # 状态查询 API
    # ================================================================

    def get_mod_status(self, name: str) -> Optional[ModStatus]:
        if self._services:
            return self._services.get_mod_status(name)
        return None

    def get_all_mod_statuses(self) -> Dict[str, ModStatus]:
        if self._services:
            return self._services.get_all_mod_statuses()
        return {}

    def status_summary(self) -> str:
        statuses = self.get_all_mod_statuses()
        if not statuses:
            return "⚠ 无 Mod 状态信息（服务可能尚未启动或 Mod 加载失败）"

        lines = []
        lines.append("=" * 72)
        lines.append(f"{'Mod 名称':<22} {'版本':<10} {'状态':<8} {'依赖':<30} {'备注'}")
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
            lines.append(f"{name:<22} {st.version:<10} {state:<8} {deps:<30} {note}")

        lines.append("-" * 72)
        enabled_count = sum(1 for s in statuses.values() if s.enabled)
        lines.append(f"总计: {len(statuses)} 个 Mod | 已启用: {enabled_count} | "
                     f"异常: {sum(1 for s in statuses.values() if s.error)}")
        lines.append("=" * 72)
        return "\n".join(lines)

