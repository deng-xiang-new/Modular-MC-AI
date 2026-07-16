# 🏰 Modular-MC-AI

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/minecraft-bedrock-green.svg" alt="Bedrock">
  <img src="https://img.shields.io/badge/platform-ubuntu%20|%20debian-red.svg" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="License">
  <img src="https://img.shields.io/badge/version-3.1.0-brightgreen.svg" alt="Version">
</p>

<p align="center">
  <strong>🧩 模块化 · 🔥 热重载 · 🖥️ Web 面板 · 🚀 一键部署</strong>
</p>

---

## 📖 简介

**Modular-MC-AI** 是一个面向 Minecraft 基岩版服务器的 AI 智能助手。它通过 WebSocket 协议与游戏实时通信，让玩家在聊天栏中直接与 AI 对话——就像在服务器里内置了一个智能 NPC。

与同类项目不同，Modular-MC-AI 采用**三层模块化架构**：底层引擎（`core/`）保持稳定不动，所有业务逻辑以 **Mod（模块）**形式热插拔运行。这意味着你可以在不重启服务的情况下随时添加、删除、启用或禁用任何功能模块。

> **像搭积木一样构建你的 Minecraft AI 助手。** 每个功能都是一个独立 Mod，随需组合，即插即用。

---

## ✨ 项目亮点

| 亮点 | 说明 |
|------|------|
| 🧠 **AI 原生集成** | 支持 OpenAI 兼容 API（DeepSeek、GPT、Claude 等），在聊天栏输入 `@ai` 即可对话 |
| 📦 **真·模块化** | 每个功能都是独立 Mod 文件夹，移动/重命名即启用/禁用，无需改代码 |
| 🔥 **热重载** | 发送信号即可重载所有 Mod，服务不中断，玩家无感知 |
| 🛡️ **三层幽灵防御** | 热重载后自动全局清理事件订阅和定时任务，杜绝旧代码残留 |
| 🖥️ **独立 Web 面板** | 与主服务解耦运行，主进程崩溃也能照常访问，支持可视化 Mod 管理 |
| 🚀 **一键部署** | `sudo bash deploy.sh` 一条命令搞定所有环境配置，交互式引导，5 分钟上线 |
| 💻 **终端控制** | `mcctl.py` 提供交互式终端，可直接向游戏发送指令，支持脚本集成 |
| 🔗 **拓扑加载** | 自动解析 Mod 依赖关系并按正确顺序启用，循环依赖自动检测告警 |
| 📝 **玩家记忆** | 每个玩家独立维护对话历史与上下文，支持记忆上限与自动摘要 |
| 🔒 **安全防护** | IP 白/黑名单、端口扫描检测、自动封禁，持久化封禁列表 |

---

## 🏗️ 架构

```
Modular-MC-AI/
├── core/                   ← 底层引擎（稳定，不修改）
│   ├── event.py            → 事件总线（观察者模式）
│   ├── scheduler.py        → 异步定时调度器
│   ├── websocket.py        → 基岩版 WS 协议层
│   ├── ai_client.py        → AI API 客户端
│   ├── mod_api.py          → Mod 基类 + 服务容器
│   └── mod_loader.py       → Mod 发现/加载/热重载
│
├── mods/                   ← 业务逻辑（热插拔 Mod）
│   ├── chat_handler/       → @ai 对话处理
│   ├── memory_system/      → 玩家记忆系统
│   ├── security/           → 安全防护
│   ├── command_executor/   → MC 指令封装
│   ├── time_system/        → 时间服务
│   └── terminal_control/   → 终端 → 游戏指令转发
│
├── web_frontend/           ← Web 面板前端
├── web_admin.py            ← Web 面板后端（独立进程）
├── mcctl.py                ← 终端控制客户端
├── main.py                 ← 主服务入口
├── deploy.sh               ← 一键部署脚本
├── MOD_API.md              ← Mod 开发文档
└── config.json             ← 配置文件
```

**设计原则：** 核心层（`core/`）不应被用户修改。所有定制开发都在 `mods/` 目录下进行，通过 `ModBase` 基类提供的统一 API 与系统交互。

---

## 🚀 快速开始

### 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 20.04+ / Debian 11+ |
| 权限 | root 或 sudo |
| 系统依赖 | python3, python3-pip, python3-venv, ufw, curl, unzip |
| Python | 3.10+（部署脚本会自动创建 venv） |
| Minecraft | 基岩版服务器，开启 `allow-cheats` |
| 网络 | 服务器需开放 8000（WS）和自定义 Web 面板端口 |

### 方式一：一键部署（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/deng-xiang-new/Modular-MC-AI.git
cd Modular-MC-AI

# 2. 运行一键部署脚本
sudo bash deploy.sh
```

脚本会**交互式引导**你填写：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| API Key | AI 服务密钥（必填） | `sk-xxxxxxxx` |
| API URL | AI 接口地址 | `https://api.deepseek.com/v1/chat/completions` |
| 模型名称 | 使用的 AI 模型 | `deepseek-chat` |
| AI 名称 | 游戏里 AI 的名字 | `零` |
| Web 账号 | 管理面板登录用户名 | `admin` |
| Web 密码 | 管理面板登录密码 | `minecraft-admin` |
| Web 端口 | 管理面板访问端口 | `8080` |

部署完成后自动注册为 **双 systemd 服务**并配置防火墙：

```bash
# 查看主服务状态
systemctl status modular-mc-ai

# 查看 Web 面板状态
systemctl status modular-mc-web
```

### 方式二：手动部署

```bash
git clone https://github.com/deng-xiang-new/Modular-MC-AI.git
cd Modular-MC-AI

# 安装系统依赖
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ufw curl unzip

# 创建虚拟环境并安装 Python 依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 编辑配置（填入 API Key）
nano config.json

# 启动服务
python main.py
```

### 在 Minecraft 中连接

在游戏内打开聊天栏，输入：

```
/connect <服务器IP>:8000
```

连接成功后，在聊天栏输入 `@ai 你好！` 开始对话。

---

## 🖥️ Web 管理面板

独立于主服务运行，即使 AI 服务崩溃也能正常管理。

| 功能 | 说明 |
|------|------|
| 📊 系统状态 | 主服务进程存活、运行时间、systemd 状态 |
| 📦 Mod 管理 | 上传新 Mod、启用/禁用、物理删除、源码预览 |
| 🔧 服务控制 | 启动/停止/重启主服务、触发热重载 |
| 📋 日志查看 | 实时查看运行日志和错误日志 |

部署后访问 `http://<服务器IP>:<Web端口>` 即可使用。

---

## 💻 终端控制客户端

```bash
# 交互式模式
python mcctl.py

# 单条命令模式（适合脚本）
python mcctl.py "/mc say Hello"
python mcctl.py "/list"
python mcctl.py "/mod-status"
```

---

## 🧩 内置 Mod

| Mod | 功能描述 |
|-----|---------|
| `chat_handler` | 监听 `@ai` 前缀消息，调用 AI 并返回回复 |
| `memory_system` | 玩家独立对话记忆，支持历史限制与摘要 |
| `security` | IP 白/黑名单、端口扫描检测、自动封禁 |
| `command_executor` | Minecraft 指令发送封装，tellraw 格式化 |
| `time_system` | UTC+8 时间查询 |
| `terminal_control` | Unix 套接字终端 → 游戏指令转发 |

---

## 🔧 开发自己的 Mod

```python
# mods/my_mod/mod.py
from core.mod_api import ModBase, CoreServices

class MyMod(ModBase):

    @property
    def mod_name(self) -> str:
        return "my_mod"

    @property
    def mod_version(self) -> str:
        return "1.0.0"

    @property
    def mod_description(self) -> str:
        return "我的自定义功能"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        services.event_bus.subscribe("PlayerMessage", self._on_chat)
        self.log.info("[my_mod] 已就绪")

    def on_disable(self) -> None:
        self.event_bus.unsubscribe("PlayerMessage", self._on_chat)

    async def _on_chat(self, event_data: dict):
        body = event_data.get("body", {})
        player = body.get("sender", "")
        conn = event_data.get("connection")
        if conn:
            await conn.send_command(f'say §a欢迎 {player}！')
```

详细文档请参阅 [`MOD_API.md`](./MOD_API.md)。

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [`MOD_API.md`](./MOD_API.md) | Mod 开发完整参考（事件、调度器、AI 客户端、热重载、状态查询） |
| [`README.md`](./README.md) | English introduction file |
---

## 🤝 贡献

欢迎提交 Issue、PR，或开发新 Mod 分享给社区。

---

## 📄 许可证

MIT License © 2025 [deng-xiang-new](https://github.com/deng-xiang-new)

---

<p align="center">
  <sub>Made with ❤️ for the Minecraft community</sub>
</p>
