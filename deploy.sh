#!/bin/bash
# ===================================================
# Modular-MC-AI - VPS 极简一键部署脚本 v4.1 (完整版)
# 适用于 Ubuntu/Debian 系统
# ===================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} Modular-MC-AI 部署脚本 v4.1 (修补版)${NC}"
echo -e "${GREEN}============================================${NC}"

# ---------- 1. 权限检测 ----------
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}请使用 root 权限运行: sudo bash deploy.sh${NC}"
    exit 1
fi

# ---------- 2. 读取当前目录 ----------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="/opt/modular-mc-ai"

if [ ! -f "$SCRIPT_DIR/main.py" ]; then
    echo -e "${RED}错误: 未在脚本同级目录下找到 main.py，请将项目文件放到脚本同级目录。${NC}"
    exit 1
fi

# ---------- 3. 交互式配置：AI 核心参数 ----------
echo ""
echo -e "${YELLOW}>>> 步骤 1/2：配置 AI 核心参数${NC}"

read -r -p "API Key (必填，如 sk-...): " USER_API_KEY
if [ -z "$USER_API_KEY" ]; then
    echo -e "${RED}错误：API Key 不能为空！${NC}"
    exit 1
fi

read -r -p "API URL [直接回车使用默认: https://api.deepseek.com/v1/chat/completions]: " USER_API_URL
USER_API_URL=${USER_API_URL:-"https://api.deepseek.com/v1/chat/completions"}

read -r -p "模型名称 [直接回车使用默认: deepseek-chat]: " USER_MODEL
USER_MODEL=${USER_MODEL:-"deepseek-chat"}

read -r -p "AI 在游戏里的名字 [直接回车使用默认: 零]: " AI_NAME_INPUT
AI_NAME_INPUT=${AI_NAME_INPUT:-"零"}

# ---------- 4. 交互式配置：Web 面板 ----------
echo ""
echo -e "${YELLOW}>>> 步骤 2/2：配置独立 Web 管理面板${NC}"

DEFAULT_WEB_PORT=8080
DEFAULT_WEB_USER="admin"
DEFAULT_WEB_PASS="minecraft-admin"

read -r -p "Web 面板管理账号 [$DEFAULT_WEB_USER]: " WEB_USER
WEB_USER=${WEB_USER:-$DEFAULT_WEB_USER}

read -r -p "Web 面板管理密码 [$DEFAULT_WEB_PASS]: " WEB_PASS
WEB_PASS=${WEB_PASS:-$DEFAULT_WEB_PASS}

read -r -p "Web 面板端口 [$DEFAULT_WEB_PORT]: " WEB_PORT
WEB_PORT=${WEB_PORT:-$DEFAULT_WEB_PORT}

# ---------- 5. 安装系统依赖 ----------
echo ""
echo -e "${YELLOW}[1/6] 正在安装系统依赖包...${NC}"
apt update -y
apt install -y python3 python3-pip python3-venv ufw curl unzip

# ---------- 6. 同步项目文件 ----------
echo -e "${YELLOW}[2/6] 正在同步项目至 ${APP_DIR}...${NC}"
mkdir -p "$APP_DIR"
cp -r "$SCRIPT_DIR"/* "$APP_DIR/"

# 确保数据与日志目录存在
mkdir -p "$APP_DIR/data/memory/players"
mkdir -p "$APP_DIR/data/security"
mkdir -p "$APP_DIR/logs"

# ---------- 7. 写入并同步 config.json ----------
echo -e "${YELLOW}[3/6] 正在写入配置...${NC}"
cd "$APP_DIR"
python3 -c "
import json, os
cfg = {}
if os.path.exists('config.json'):
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

# 写入 AI 配置
if 'ai' not in cfg: cfg['ai'] = {}
cfg['ai']['api_key'] = '${USER_API_KEY}'
cfg['ai']['api_url'] = '${USER_API_URL}'
cfg['ai']['model'] = '${USER_MODEL}'
cfg['ai']['name'] = '${AI_NAME_INPUT}'
        
# 确保基础结构存在
if 'websocket' not in cfg: cfg['websocket'] = {'port': 8000, 'host': '0.0.0.0'}
if 'logging' not in cfg: cfg['logging'] = {}

# 自动纠正日志路径为绝对路径
cfg['logging']['server_log'] = '${APP_DIR}/logs/server.log'
cfg['logging']['error_log'] = '${APP_DIR}/logs/server_error.log'

# 写入 Web 面板专属配置
cfg['web_panel'] = {
    'host': '0.0.0.0',
    'port': int('${WEB_PORT}'),
    'username': '${WEB_USER}',
    'password': '${WEB_PASS}'
}

with open('config.json', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=4)
"

# ---------- 8. 虚拟环境与依赖安装 ----------
echo -e "${YELLOW}[4/6] 正在创建 Python 虚拟环境并安装依赖...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    pip install websockets httpx aiofiles aiohttp
fi

# 补丁：Minecraft 基岩版 WebSocket 握手补丁
find "$APP_DIR/venv" -path "*/websockets/server.py" -exec sed -i \
  's/if not any(value\.lower() == "upgrade" for value in connection):/if connection and not any(value.lower() == "upgrade" for value in connection):/' {} \;
echo -e "${GREEN}  已成功应用 websockets 握手兼容性补丁${NC}"
deactivate

# ---------- 9. 配置 systemd 服务 (双服务守候) ----------
echo -e "${YELLOW}[5/6] 正在配置系统服务守候守护...${NC}"

cat > /etc/systemd/system/modular-mc-ai.service << 'SERVICE_EOF'
[Unit]
Description=Modular-MC-AI - Minecraft AI Companion Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/modular-mc-ai
ExecStart=/opt/modular-mc-ai/venv/bin/python /opt/modular-mc-ai/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF

cat > /etc/systemd/system/modular-mc-web.service << 'WEB_SERVICE_EOF'
[Unit]
Description=Modular-MC-AI - Independent Web Admin Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/modular-mc-ai
ExecStart=/opt/modular-mc-ai/venv/bin/python /opt/modular-mc-ai/web_admin.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
WEB_SERVICE_EOF

systemctl daemon-reload
systemctl enable modular-mc-ai
systemctl enable modular-mc-web
systemctl restart modular-mc-web
systemctl restart modular-mc-ai

# ---------- 10. 配置防火墙安全端口 ----------
echo -e "${YELLOW}[6/6] 正在配置 UFW 防火墙端口安全策略...${NC}"
ufw allow 22/tcp comment "SSH"
ufw allow 8000/tcp comment "MC WebSocket Port"
ufw allow ${WEB_PORT}/tcp comment "Web Panel Port"
ufw --force enable 2>/dev/null || ufw reload

# ---------- 部署完成输出 ----------
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN} 部署成功！系统双服务已在后台平稳运行。${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "项目部署根目录:   ${CYAN}${APP_DIR}${NC}"
echo -e "游戏 WS 连接端口:  ${GREEN}8000${NC} (在 MC 中输入 /connect <服务器IP>:8000)"
echo -e "Web 运维面板地址:  ${YELLOW}http://<你的服务器公网IP>:${WEB_PORT}${NC}"
echo -e "Web 面板管理账号:  ${CYAN}${WEB_USER}${NC}"
echo -e "Web 面板管理密码:  ${CYAN}${WEB_PASS}${NC}"
echo ""