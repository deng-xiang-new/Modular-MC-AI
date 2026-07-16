# Modular-MC-AI — Mod 开发接口文档

> 版本：3.0 | 最后更新：2025-07-15

---

## 目录

1. [架构概述](#1-架构概述)
2. [快速上手：写一个 Mod](#2-快速上手写一个-mod)
3. [Mod 基类参考](#3-mod-基类参考)
4. [Mod 元信息规范](#4-mod-元信息规范)
5. [CoreServices 服务容器](#5-coreservices-服务容器)
6. [核心服务详解](#6-核心服务详解)
   - [6.1 EventBus（事件总线）](#61-eventbus事件总线)
   - [6.2 Scheduler（调度器）](#62-scheduler调度器)
   - [6.3 AIClient（AI 客户端）](#63-aiclientai-客户端)
   - [6.4 WebSocket 连接](#64-websocket-连接)
7. [游戏事件类型](#7-游戏事件类型)
8. [Mod 间通信与依赖](#8-mod-间通信与依赖)
9. [Mod 状态查询 API](#9-mod-状态查询-api)
10. [热重载机制](#10-热重载机制)
11. [日志系统](#11-日志系统)
12. [配置说明](#12-配置说明)
13. [参考实现](#13-参考实现)

---

## 1. 架构概述

项目采用 **三层架构**，将核心引擎与可定制业务逻辑完全分离：

```
Modular-MC-AI/
├── core/                  ← 纯底层引擎（不应该被修改）
│   ├── packet.py          → 基岩版封包构建/解析
│   ├── event.py           → 事件总线（观察者模式）
│   ├── scheduler.py       → 异步定时调度器
│   ├── websocket.py       → WS 连接管理（协议层）
│   ├── ai_client.py       → OpenAI 兼容 API 客户端
│   ├── mod_api.py         → Mod 基类 + 服务容器 + ModStatus
│   └── mod_loader.py      → Mod 发现/加载/卸载/热重载
│
├── mods/                  ← 所有定制业务逻辑
│   ├── chat_handler/      → @ai 消息处理
│   ├── memory_system/     → 记忆 & 上下文管理
│   ├── security/          → 白/黑名单 & 连接防护
│   ├── command_executor/  → MC 指令发送封装
│   ├── time_system/       → UTC+8 时间服务
│   └── terminal_control/  → 终端 → 游戏指令转发
│
├── config.json
├── main.py                ← 精简入口
├── mcctl.py               ← 终端控制客户端
├── deploy.sh              ← 一键部署脚本
└── MOD_API.md             ← 本文档
```

### 核心设计原则

1. **Mod 不直接访问 core 内部实现** — 所有交互通过 `CoreServices` 容器
2. **跨模块通信走事件总线** — 松耦合，可插拔
3. **Mod 有明确生命周期** — `on_enable` / `on_disable`
4. **元信息强制规范** — 名称/版本/描述/依赖必须合规，否则拒绝加载
5. **热重载支持** — 当 mod 文件变更时无需重启整个服务
6. **状态可查询** — 任何 Mod 的加载状态、依赖关系均可查询

---

## 2. 快速上手：写一个 Mod

### 最小示例

```python
# mods/welcome/mod.py

from core.mod_api import ModBase, CoreServices


class WelcomeMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "welcome"

    @property
    def mod_version(self) -> str:
        return "1.0.0"

    @property
    def mod_description(self) -> str:
        return "玩家加入时发送欢迎消息"

    @property
    def mod_dependencies(self) -> list:
        return []  # 必须显式声明，即使无依赖

    def on_enable(self, services: CoreServices) -> None:
        services.event_bus.subscribe("PlayerJoin", self._on_join)
        self.log.info("[welcome] 已就绪")

    def on_disable(self) -> None:
        self.event_bus.unsubscribe("PlayerJoin", self._on_join)

    # ---- 事件处理器 ----
    async def _on_join(self, event_data: dict):
        body = event_data.get("body", {})
        player = body.get("player", {}).get("name", "")
        conn = event_data.get("connection")

        if player and conn:
            await conn.send_command(f'say §a欢迎 {player} 加入服务器！')
```

### 步骤

1. 在 `mods/` 下创建新目录（如 `welcome/`）
2. 在该目录中创建 `mod.py`
3. 继承 `ModBase`，实现 **全部** 必须的属性/方法
4. 放到 `mods/` 下，启动时自动加载（或被热重载发现）

---

## 3. Mod 基类参考

### 抽象类：`ModBase`

位置：`core.mod_api.ModBase`

每个 Mod 必须实现以下内容：

| 成员 | 类型 | 说明 |
|------|------|------|
| `mod_name` | `@property → str` | 唯一标识名（非空字符串，用于跨 Mod 通信） |
| `mod_version` | `@property → str` | 语义化版本号，如 `"1.0.0"`（非空字符串） |
| `mod_description` | `@property → str` | 一句话描述（非空字符串） |
| `mod_dependencies` | `@property → list` | **必须覆盖**。强依赖的其他 Mod 名称列表，无依赖时返回 `[]` |
| `on_enable(services)` | 方法 | 核心服务就绪时调用，在此注册事件/启动定时任务 |
| `on_disable()` | 方法 | 系统关闭时调用，在此清理资源 |

### 便捷属性

在 `on_enable()` 之后，以下属性可直接使用：

| 属性 | 类型 | 说明 |
|------|------|------|
| `self.services` | `CoreServices` | 核心服务容器 |
| `self.log` | `Logger` | server 日志 |
| `self.config` | `dict` | 全局配置 |
| `self.event_bus` | `EventBus` | 事件总线 |
| `self.scheduler` | `Scheduler` | 定时调度器 |
| `self.ai_client` | `AIClient` | AI 客户端 |

---

## 4. Mod 元信息规范

> ⚠ **从 v3.0 起强制执行。** 不合规的 Mod 会**被拒绝加载**，并在日志中记录详细原因。

### 规范要求

| 字段 | 要求 | 错误示例 |
|------|------|---------|
| `mod_name` | 非空字符串 | `""`、`None`、非 str 类型 |
| `mod_version` | 非空字符串 | `""`、`None`、非 str 类型 |
| `mod_description` | 非空字符串 | `""`、`None`、非 str 类型 |
| `mod_dependencies` | 必须为 `list` 类型 | `None`、`"memory_system"`（字符串而非列表） |

### 合规示例

```python
class MyMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "my_mod"

    @property
    def mod_version(self) -> str:
        return "2.1.0"

    @property
    def mod_description(self) -> str:
        return "我的自定义 Mod，提供 XYZ 功能"

    @property
    def mod_dependencies(self) -> list:
        return ["memory_system", "time_system"]
```

### 不合规示例

```python
class BadMod(ModBase):

    @property
    def mod_name(self) -> str:
        return ""  # ❌ 空字符串，将被拒绝

    @property
    def mod_version(self) -> str:
        return "1.0.0"

    @property
    def mod_description(self) -> str:
        return "..."

    # ❌ 缺少 mod_dependencies 覆盖，默认空 list 尚可接受但不推荐
```

---

## 5. CoreServices 服务容器

位置：`core.mod_api.CoreServices`

这是 Mod 能接触到的所有核心服务的统一入口。

| 属性/方法 | 类型 | 说明 |
|-----------|------|------|
| `event_bus` | `EventBus` | 全局事件总线 |
| `scheduler` | `Scheduler` | 异步定时任务调度器 |
| `ai_client` | `AIClient` | OpenAI 兼容 API 客户端 |
| `config` | `dict` | `config.json` 的完整内容 |
| `server_log` | `logging.Logger` | 服务器运行日志 |
| `error_log` | `logging.Logger` | 错误日志 |
| `ai_name` | `str` | AI 名称（如 "零"） |
| `get_mod(name)` | `→ ModBase` | 获取另一个已加载的 Mod 实例 |
| `get_mod_status(name)` | `→ ModStatus` | 获取指定 Mod 的状态快照 |
| `get_all_mod_statuses()` | `→ Dict[str, ModStatus]` | 获取所有 Mod 的状态快照 |

---

## 6. 核心服务详解

### 6.1 EventBus（事件总线）

**文件：** `core/event.py` | **实例：** `services.event_bus`

```python
# 订阅事件
event_bus.subscribe("PlayerMessage", my_handler)

# 取消订阅
event_bus.unsubscribe("PlayerMessage", my_handler)

# 列出所有已注册事件类型
event_names = event_bus.list_events()
```

**处理器签名：**
```python
async def my_handler(event_data: dict) -> None:
    body      = event_data.get("body", {})
    sender    = body.get("sender", "")         # 玩家名
    message   = body.get("message", "")        # 聊天内容
    conn      = event_data.get("connection")    # MinecraftWSConnection 实例
    evt_name  = event_data.get("event_name")    # 事件名
```

> 每个 handler 以独立 `asyncio.create_task` 后台运行，不会阻塞 WebSocket 接收循环。单个 handler 异常被记录到 error log，不影响其他 handler。

### 6.2 Scheduler（调度器）

**文件：** `core/scheduler.py` | **实例：** `services.scheduler`

```python
# 周期性任务（每60秒执行一次）
await scheduler.schedule_periodic(
    name="auto_save",
    interval_seconds=60,
    coro_func=my_periodic_task,
    *args, **kwargs
)

# 一次性延迟任务（5分钟后执行）
await scheduler.schedule_once(
    delay_seconds=300,
    coro_func=my_one_off_task
)

# 取消任务
scheduler.cancel("auto_save")
```

### 6.3 AIClient（AI 客户端）

**文件：** `core/ai_client.py` | **实例：** `services.ai_client`

```python
reply = await ai_client.chat(messages=[
    {"role": "system", "content": "你是一个助手"},
    {"role": "user",   "content": "你好"}
])
# 返回纯文本字符串
```

### 6.4 WebSocket 连接

**类：** `MinecraftWSConnection` | **文件：** `core/websocket.py`

```python
conn: MinecraftWSConnection = event_data["connection"]

# 发送指令并异步等待响应（默认 5 秒超时）
resp = await conn.send_command("clear @p diamond 0 0")

# 发送指令但不等待响应
await conn.send_command_fire_and_forget("say Hello")

# 订阅额外事件
conn.subscribe_event("PlayerLeave")
```

---

## 7. 游戏事件类型

| 事件名 | 触发时机 | body 关键字段 |
|--------|---------|---------------|
| `PlayerMessage` | 玩家发送聊天消息 | `sender`, `message` |
| `PlayerJoin` | 玩家加入服务器 | `player.name` |
| `PlayerLeave` | 玩家离开服务器 | `player.name` |
| `PlayerDied` | 玩家死亡 | `player.name`, `cause` |
| `PlayerTravelled` | 玩家移动 | `player.name`, `position` |
| `PlayerTransform` | 玩家切换维度 | `player.name`, `dimension` |
| `BlockPlaced` | 方块放置 | `player.name`, `block` |
| `BlockBroken` | 方块破坏 | `player.name`, `block` |
| `ItemAcquired` | 物品获得 | `player.name`, `item` |
| `ItemUsed` | 物品使用 | `player.name`, `item` |

---

## 8. Mod 间通信与依赖

### 8.1 获取已加载的 Mod

```python
memory_mod = self.services.get_mod("memory_system")
if memory_mod:
    memory_mod.save_message(player_name, content, role="user")
```

### 8.2 声明强依赖

```python
class MyMod(ModBase):

    @property
    def mod_dependencies(self) -> list:
        return ["memory_system", "security"]
```

### 8.3 依赖验证与拓扑排序

加载阶段，ModLoader 会**自动验证**所有 Mod 的依赖，并使用**拓扑排序**（Topological Sort）决定启用顺序。

**拓扑排序规则：**
- 若 Mod A 依赖 Mod B，则 B 的 `on_enable` 先于 A 执行
- 未声明依赖的 Mod 优先启用
- 缺失依赖的 Mod 排在最后（允许加载但告警）
- 检测到循环依赖时自动打破并记录告警

**示例：**
```
chat_handler 依赖 → [memory_system, security, time_system]
memory_system 无依赖
security 无依赖
time_system 无依赖

启用顺序: security → time_system → memory_system → chat_handler
停用顺序: chat_handler → memory_system → time_system → security（反向）
```

**验证行为：**
- 依赖均存在 → 静默通过
- 存在缺失依赖 → 写入 error log 和 server log，记录到 `ModStatus.missing_deps`
- 存在循环依赖 → 记录 error log 并包含循环路径，然后按任意顺序打破循环继续启用

---

## 9. Mod 状态查询 API

> **v3.0 新增。** 提供多层级 Mod 状态查询能力，便于排查依赖问题和运行时错误。

### 9.1 在代码中查询

```python
# 获取单个 Mod 状态
status = services.get_mod_status("memory_system")
if status:
    print(f"{status.name} v{status.version}: "
          f"启用={status.enabled}, 缺依赖={status.missing_deps}")

# 获取所有 Mod 状态
all_statuses = services.get_all_mod_statuses()
for name, st in all_statuses.items():
    if st.error:
        print(f"❌ {name}: {st.error}")
    elif st.missing_deps:
        print(f"⚠ {name}: 缺少依赖 {st.missing_deps}")
    else:
        print(f"✓ {name} v{st.version}")
```

### 9.2 ModStatus 数据结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | Mod 唯一标识名 |
| `version` | `str` | 语义化版本号 |
| `description` | `str` | 简介 |
| `dependencies` | `List[str]` | 依赖列表 |
| `enabled` | `bool` | 是否已启用 |
| `missing_deps` | `List[str]` | 缺失的依赖 |
| `loaded_at` | `str` | 加载时间（ISO格式） |
| `error` | `Optional[str]` | 错误信息（无错误则为 None） |

### 9.3 在终端中查询

**方式一：管理命令**
```bash
mc-ai mod-status       # 发送 SIGUSR2 信号，状态输出到日志
mc-ai log-tail 40      # 查看最近日志（含状态摘要）
```

**方式二：直接信号**
```bash
sudo kill -USR2 $(systemctl show -p MainPID modular-mc-ai | cut -d= -f2)
sudo journalctl -u modular-mc-ai --since '10 seconds ago' --no-pager
```

**方式三：mcctl 客户端**
```
python mcctl.py "/mod-status"
```

状态输出示例：
```
======================================================================
Mod 名称              版本       状态     依赖                 备注
----------------------------------------------------------------------
chat_handler          1.0.0      ✓ 启用    memory_system, security
command_executor      1.0.0      ✓ 启用    无
memory_system         1.0.0      ✓ 启用    无
security              1.0.0      ✓ 启用    无
terminal_control      1.1.0      ✓ 启用    无
time_system           1.0.0      ✓ 启用    无
----------------------------------------------------------------------
总计: 6 个 Mod | 已启用: 6 | 异常: 0
======================================================================
```

---

## 10. 热重载机制

> **v3.0 新增。** 当有 mod 文件被添加、删除、修改、启用或禁用时，可触发热重载而无需重启整个服务。

### 10.1 触发方式

| 方式 | 命令 |
|------|------|
| 管理命令 | `mc-ai reload` |
| 直接信号 | `sudo kill -USR1 $(systemctl show -p MainPID modular-mc-ai \| cut -d= -f2)` |

### 10.2 热重载流程（完整）

```
1. 反向拓扑顺序停用所有 Mod（依赖者先停用，被依赖者后停用）
2. 【防幽灵对象】主动清空 EventBus 所有订阅 + 停止 Scheduler 所有任务
   — 即使个别 Mod 的 on_disable 没清理干净，全局清空也能兜底
   — 杜绝 "双重响应" 问题：旧 Mod 的 handler 不可能在重载后继续响应
3. 清除 sys.modules 中的 Mod 模块缓存
4. 重新扫描 mods/ 目录
5. 实例化 + 元信息验证
6. 拓扑排序（被依赖者排在前）
7. 按拓扑顺序依次启用
```

### 10.3 防幽灵对象（Ghost Object）机制

> 这是热重载最关键的底层安全机制，解决 Python 异步框架下的引用泄漏问题。

**问题场景（修复前）：**
如果 core 或未重载的组件（EventBus 闭包、Scheduler 的正在运行的协程）持有旧 Mod 实例的引用，即使清空了 `sys.modules`，旧实例不会被垃圾回收，导致：
- 新旧两个 Mod 实例同时响应同一个事件
- Scheduler 中旧任务继续运行

**解决方案（三层防御）：**

| 层级 | 机制 | 说明 |
|------|------|------|
| 第一层 | `on_disable` 清理 | 每个 Mod 应自行取消订阅和任务（正常清理） |
| 第二层 | `EventBus.clear_all()` | 热重载时全局清空所有事件订阅（兜底） |
| 第三层 | `Scheduler.stop()` + 重启 | 热重载时停止所有活跃/待激活任务然后恢复运行状态 |

**日志示例：**
```
[ModLoader] 🧹 热重载清理：EventBus 清除了 3 个旧 handler（事件类型: ['PlayerMessage', 'PlayerJoin']）
[ModLoader] 🧹 热重载清理：Scheduler 清除了 0 个活跃任务 + 0 个待激活任务
```

### 10.4 安全保证

- **隔离异常：** 单个 Mod 的加载/启用失败不会影响其他 Mod 或全局服务
- **原子清理：** 停用阶段即使异常也会被捕获记录
- **幽灵防御：** 三层清理确保旧实例不可能在热重载后继续响应
- **拓扑排序：** 保证依赖 Mod 先于被依赖 Mod 启用，反向停用
- **状态追踪：** 每个 Mod 的状态在热重载前后均被更新

---

## 11. 日志系统

> **v3.0 增强。** 双日志系统提供细颗粒度的管理入口。

### 11.1 日志文件

| 文件 | 内容 | 查看命令 |
|------|------|---------|
| `logs/server.log` | 服务器运行日志 | `mc-ai log` |
| `logs/server_error.log` | 错误/警告日志 | `mc-ai log-error` |
| systemd journal | 标准输出/标准错误 | `mc-ai log-journal` |

### 11.2 快捷查看方式

```bash
mc-ai log              # tail -f 实时跟踪运行日志
mc-ai log-error        # tail -f 实时跟踪错误日志
mc-ai log-all          # 同时跟踪两个日志文件
mc-ai log-journal      # 查看 systemd 日志
mc-ai log-tail 100     # 查看最近 100 行运行日志
```

### 11.3 Logger 名称约定

| Logger 名 | 用途 |
|-----------|------|
| `"server"` | 一般运行信息（INFO 级别） |
| `"error"` | 错误和警告（WARNING+ 级别） |

---

## 12. 配置说明

`config.json` 结构：

```jsonc
{
    "websocket": {
        "port": 8000,
        "host": "0.0.0.0"
    },
    "ai": {
        "name": "零",
        "api_url": "https://api.deepseek.com/v1/chat/completions",
        "api_key": "sk-...",
        "model": "deepseek-chat",
        "temperature": 0.4,
        "max_tokens": 300
    },
    "security": {
        "scan_threshold": 5,
        "scan_window_seconds": 60,
        "ban_duration_hours": 24
    },
    "memory": {
        "max_history_per_player": 50,
        "server_memory_path": "data/memory/server.json",
        "players_dir": "data/memory/players",
        "summary_path": "data/memory/summary.json"
    },
    "logging": {
        "server_log": "logs/server.log",
        "error_log": "logs/server_error.log"
    }
}
```

---

## 13. 参考实现

| Mod | 功能 | 关键模式 |
|-----|------|---------|
| `mods/chat_handler/mod.py` | AI 对话处理 | 事件订阅、跨 Mod 调用、AI 调用 |
| `mods/memory_system/mod.py` | 记忆&上下文管理 | 公共 API 设计、数据持久化 |
| `mods/security/mod.py` | 安全防护 | IP 检测、持久化封禁列表 |
| `mods/time_system/mod.py` | 时间服务 | 静态工具方法 |
| `mods/command_executor/mod.py` | 指令封装 | 消息格式化、tellraw 构造 |
| `mods/terminal_control/mod.py` | 终端控制 | Unix 套接字、跨连接管理 |

### 添加新 Mod 的检查清单

- [ ] 在 `mods/` 下创建目录
- [ ] 创建 `mod.py`，继承 `ModBase`
- [ ] 实现 `mod_name` / `mod_version` / `mod_description`（**必须非空字符串**）
- [ ] 覆盖 `mod_dependencies`，无依赖时返回 `[]`
- [ ] 在 `on_enable` 中注册事件 / 启动定时任务
- [ ] 在 `on_disable` 中清理资源
- [ ] 与其他 Mod 交互时用 `services.get_mod()`，做 None 检查
- [ ] 不直接 import 其他 Mod 的内部文件
- [ ] 添加/修改后执行 `mc-ai reload` 热重载验证
