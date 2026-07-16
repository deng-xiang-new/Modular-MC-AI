# 🏰 Modular-MC-AI

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/minecraft-bedrock-green.svg" alt="Bedrock">
  <img src="https://img.shields.io/badge/platform-ubuntu%20|%20debian-red.svg" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="License">
  <img src="https://img.shields.io/badge/version-3.1.0-brightgreen.svg" alt="Version">
</p>

<p align="center">
  <strong>🧩 Modular · 🔥 Hot Reload · 🖥️ Web Panel · 🚀 One-Click Deploy</strong>
</p>

---

## 📖 Introduction

**Modular-MC-AI** is an intelligent AI assistant for Minecraft Bedrock Edition servers. It communicates with the game in real time via the WebSocket protocol, allowing players to chat with AI directly from the in-game chat bar — as if the server has a built-in intelligent NPC.

What sets it apart from similar projects is its **three-layer modular architecture**: the core engine (`core/`) remains stable and untouched, while all business logic runs as hot-swappable **Mods**. This means you can add, remove, enable, or disable any feature module without restarting the service.

> **Build your Minecraft AI assistant like building with blocks.** Every feature is an independent Mod — mix, match, and plug-and-play at will.

---

## ✨ Highlights

| Feature | Description |
|---------|-------------|
| 🧠 **Native AI Integration** | OpenAI-compatible API (DeepSeek, GPT, Claude, etc.). Chat by typing `@ai` in the game |
| 📦 **True Modularity** | Each feature is an independent Mod folder. Move/rename to enable/disable — no code changes needed |
| 🔥 **Hot Reload** | Reload all Mods on signal — zero downtime, players won't notice |
| 🛡️ **Ghost Defense** | Three-layer cleanup after hot reload: event subscriptions, scheduled tasks, and module cache all purged |
| 🖥️ **Standalone Web Panel** | Decoupled from the main service. Fully functional even when the main process crashes |
| 🚀 **One-Click Deploy** | `sudo bash deploy.sh` — a single command handles everything. Interactive guided setup, online in 5 minutes |
| 💻 **Terminal Control** | `mcctl.py` provides an interactive terminal to send commands to the game. Script-friendly |
| 🔗 **Topological Loading** | Auto-resolves Mod dependencies and loads in correct order. Circular dependency detection with warnings |
| 📝 **Player Memory** | Per-player conversation history and context. Configurable memory cap with auto-summarization |
| 🔒 **Security** | IP whitelist/blacklist, port scan detection, auto-ban with persistent ban list |

---

## 🏗️ Architecture

```
Modular-MC-AI/
├── core/                   ← Core engine (stable, do not modify)
│   ├── event.py            → Event bus (Observer pattern)
│   ├── scheduler.py        → Async periodic task scheduler
│   ├── websocket.py        → Bedrock WS protocol layer
│   ├── ai_client.py        → AI API client
│   ├── mod_api.py          → Mod base class + service container
│   └── mod_loader.py       → Mod discovery / loading / hot reload
│
├── mods/                   ← Business logic (hot-swappable Mods)
│   ├── chat_handler/       → @ai conversation handler
│   ├── memory_system/      → Player memory system
│   ├── security/           → Security protection
│   ├── command_executor/   → MC command wrapper
│   ├── time_system/        → Time service
│   └── terminal_control/   → Terminal → game command bridge
│
├── web_frontend/           ← Web panel frontend
├── web_admin.py            ← Web panel backend (standalone process)
├── mcctl.py                ← Terminal control client
├── main.py                 ← Main service entry point
├── deploy.sh               ← One-click deployment script
├── MOD_API.md              ← Mod development documentation
└── config.json             ← Configuration file
```

**Design Principle:** The core layer (`core/`) should never be modified by users. All custom development happens inside `mods/`, interacting with the system through the unified `ModBase` API.

---

## 🚀 Quick Start

### Requirements

| Item | Requirement |
|------|-------------|
| OS | Ubuntu 20.04+ / Debian 11+ |
| Privileges | root or sudo |
| System Dependencies | python3, python3-pip, python3-venv, ufw, curl, unzip |
| Python | 3.10+ (deploy script auto-creates venv) |
| Minecraft | Bedrock server with `allow-cheats` enabled |
| Network | Ports 8000 (WS) and custom web panel port must be open |

### Option 1: One-Click Deploy (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/deng-xiang-new/Modular-MC-AI.git
cd Modular-MC-AI

# 2. Run the one-click deploy script
sudo bash deploy.sh
```

The script will **interactively guide you** through configuration:

| Setting | Description | Example |
|---------|-------------|---------|
| API Key | AI service key (required) | `sk-xxxxxxxx` |
| API URL | AI endpoint URL | `https://api.deepseek.com/v1/chat/completions` |
| Model | AI model to use | `deepseek-chat` |
| AI Name | The AI's in-game name | `Zero` |
| Web Username | Admin panel login username | `admin` |
| Web Password | Admin panel login password | `minecraft-admin` |
| Web Port | Admin panel access port | `8080` |

Once complete, the project is registered as **dual systemd services** with firewall configured:

```bash
# Check main service status
systemctl status modular-mc-ai

# Check web panel status
systemctl status modular-mc-web
```

### Option 2: Manual Deploy

```bash
git clone https://github.com/deng-xiang-new/Modular-MC-AI.git
cd Modular-MC-AI

# Install system dependencies
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ufw curl unzip

# Create venv and install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Edit config (fill in your API Key)
nano config.json

# Start the service
python main.py
```

### Connect from Minecraft

Open the chat bar in-game and type:

```
/connect <Server IP>:8000
```

Once connected, type `@ai Hello!` in chat to start a conversation.

---

## 🖥️ Web Admin Panel

Runs independently from the main service — fully functional even if the AI service crashes.

| Feature | Description |
|---------|-------------|
| 📊 System Status | Main process liveness, uptime, systemd status |
| 📦 Mod Management | Upload new Mods, enable/disable, delete, source preview |
| 🔧 Service Control | Start/stop/restart main service, trigger hot reload |
| 📋 Log Viewer | Real-time server log and error log viewing |

After deployment, visit `http://<Server IP>:<Web Port>` to access.

---

## 💻 Terminal Control Client

```bash
# Interactive mode
python mcctl.py

# Single-command mode (great for scripts)
python mcctl.py "/mc say Hello"
python mcctl.py "/list"
python mcctl.py "/mod-status"
```

---

## 🧩 Built-in Mods

| Mod | Description |
|-----|-------------|
| `chat_handler` | Listens for `@ai` prefixed messages, calls AI, returns response |
| `memory_system` | Per-player conversation memory with history limit and summarization |
| `security` | IP whitelist/blacklist, port scan detection, auto-ban |
| `command_executor` | Minecraft command wrapping with tellraw formatting |
| `time_system` | UTC+8 time queries |
| `terminal_control` | Unix socket terminal → game command bridge |

---

## 🔧 Develop Your Own Mod

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
        return "My custom feature"

    @property
    def mod_dependencies(self) -> list:
        return []

    def on_enable(self, services: CoreServices) -> None:
        services.event_bus.subscribe("PlayerMessage", self._on_chat)
        self.log.info("[my_mod] Ready")

    def on_disable(self) -> None:
        self.event_bus.unsubscribe("PlayerMessage", self._on_chat)

    async def _on_chat(self, event_data: dict):
        body = event_data.get("body", {})
        player = body.get("sender", "")
        conn = event_data.get("connection")
        if conn:
            await conn.send_command(f'say §aWelcome {player}!')
```

Full documentation in [`MOD_API.md`](./MOD_API.md).

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [`MOD_API.md`](./MOD_API.md) | Complete Mod development reference (events, scheduler, AI client, hot reload, status query) |
| [`README_CN.md`](./README_CN.md) | 中文介绍文档 |

---

## 🤝 Contributing

Issues, PRs, and new Mod submissions are welcome!

---

## 📄 License

MIT License © 2025 [deng-xiang-new](https://github.com/deng-xiang-new)

---

<p align="center">
  <sub>Made with ❤️ for the Minecraft community</sub>
</p>
