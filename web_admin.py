# -*- coding: utf-8 -*-
"""
Modular-MC-AI 独立图形化运维面板（Backend）
与主服务完全解耦，独立运行，支持在主服务崩溃时进行抢修、管理和重启。
"""

import os
import sys
import json
import signal
import subprocess
import uuid
import shutil
import re
from aiohttp import web

# 确保能读取到项目根目录下的 config.json
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
MODS_DIR = os.path.join(PROJECT_ROOT, "mods")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        # 默认配置模板，防止文件丢失导致面板也打不开
        return {
            "web_panel": {"username": "admin", "password": "admin123", "port": 8080, "host": "0.0.0.0"},
            "logging": {"server_log": "logs/server.log", "error_log": "logs/server_error.log"}
        }
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)

# 全局认证 Token 缓存
SESSIONS = set()

# --- 辅助函数 ---
def get_main_pid():
    """获取主服务的 PID (通过 ps 过滤 main.py)"""
    try:
        # 查找运行 main.py 且不包含本脚本 web_admin.py 的进程
        cmd = "ps aux | grep 'python.*main.py' | grep -v 'grep' | grep -v 'web_admin.py'"
        output = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
        if output:
            for line in output.split('\n'):
                parts = line.split()
                if len(parts) > 1:
                    return int(parts[1])
    except Exception:
        pass
    return None

def trigger_hot_reload():
    """给主服务发送 SIGUSR1 信号触发热重载"""
    pid = get_main_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGUSR1)
            return True, "已成功向主进程发送热重载信号 (SIGUSR1)"
        except Exception as e:
            return False, f"发送热重载信号失败: {e}"
    return False, "主进程未运行，无法触发热重载。请先启动主服务。"

# --- 中间件：登录拦截 ---
@web.middleware
async def auth_middleware(request, handler):
    if request.path.startswith('/api/') and request.path != '/api/login':
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if token not in SESSIONS:
            return web.json_response({"error": "Unauthorized"}, status=401)
    return await handler(request)

# --- 路由处理器 ---
async def api_login(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "无效的请求格式"}, status=400)
    
    cfg = load_config()
    web_cfg = cfg.get("web_panel", {})
    username = web_cfg.get("username", "admin")
    password = web_cfg.get("password", "admin123")
    
    if data.get("username") == username and data.get("password") == password:
        token = str(uuid.uuid4())
        SESSIONS.add(token)
        return web.json_response({"token": token})
    return web.json_response({"error": "账号或密码错误"}, status=401)

async def api_system_status(request):
    """获取主服务状态及面板基础信息"""
    pid = get_main_pid()
    is_running = pid is not None
    
    # 尝试获取主服务的运行时间等信息
    systemd_info = "未知"
    try:
        systemd_info = subprocess.check_output(
            "systemctl status modular-mc-ai.service | grep 'Active:'", 
            shell=True
        ).decode('utf-8').strip()
    except Exception:
        pass

    return web.json_response({
        "main_service": {
            "status": "running" if is_running else "stopped",
            "pid": pid,
            "systemd_info": systemd_info
        },
        "system_info": {
            "platform": sys.platform,
            "python_version": sys.version.split()[0]
        }
    })

async def api_control_service(request):
    """控制主服务启动/停止/重启"""
    data = await request.json()
    action = data.get("action")
    if action not in ["start", "stop", "restart", "reload"]:
        return web.json_response({"error": "无效的操作"}, status=400)

    try:
        if action == "reload":
            success, msg = trigger_hot_reload()
            return web.json_response({"success": success, "message": msg})
        
        if action == "start":
            subprocess.run(["systemctl", "start", "modular-mc-ai"], check=True)
        elif action == "stop":
            subprocess.run(["systemctl", "stop", "modular-mc-ai"], check=True)
        elif action == "restart":
            subprocess.run(["systemctl", "restart", "modular-mc-ai"], check=True)
            
        return web.json_response({"success": True, "message": f"服务已执行 {action} 操作"})
    except Exception as e:
        return web.json_response({"success": False, "error": f"执行失败: {e}"}, status=500)

async def api_list_mods(request):
    """物理扫描 mods 文件夹获取模块列表（即使主进程崩溃也能准确读取）"""
    if not os.path.exists(MODS_DIR):
        return web.json_response({"mods": []})
        
    mods = []
    for entry in os.listdir(MODS_DIR):
        entry_path = os.path.join(MODS_DIR, entry)
        
        # 过滤掉非目录、隐藏文件夹以及 __pycache__
        if not os.path.isdir(entry_path) or entry == "__pycache__" or (entry.startswith('.') and len(entry) <= 1):
            continue
            
        is_disabled = entry.startswith('.')
        mod_dir_name = entry[1:] if is_disabled else entry
        
        # 尝试读取 mod.py 里的元数据
        mod_file = os.path.join(entry_path, "mod.py")
        version, description = "未知", "无描述信息"
        
        if os.path.exists(mod_file):
            try:
                with open(mod_file, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # 使用正则表达式精准跨行提取 return 里的字符串
                v_match = re.search(r'def\s+mod_version.*?return\s+[\'"]([^\'"]+)[\'"]', content, re.DOTALL)
                if v_match:
                    version = v_match.group(1)
                    
                d_match = re.search(r'def\s+mod_description.*?return\s+[\'"]([^\'"]+)[\'"]', content, re.DOTALL)
                if d_match:
                    description = d_match.group(1)
            except Exception:
                description = "⚠️ 无法解析该模块的 mod.py"

        mods.append({
            "name": mod_dir_name,
            "version": version,
            "description": description,
            "dependencies": [],
            "enabled": not is_disabled
        })
    return web.json_response({"mods": mods})

async def api_upload_mod(request):
    """上传模块"""
    data = await request.post()
    mod_name = data.get('mod_name')
    file = data.get('file')
    if not mod_name or not file: 
        return web.json_response({"error": "缺少 mod_name 或 file 参数"}, status=400)
    
    # 过滤不安全字符
    mod_name = "".join([c for c in mod_name if c.isalnum() or c in ('_', '-')])
    if not mod_name:
        return web.json_response({"error": "非法的模块名称"}, status=400)

    mod_path = os.path.join(MODS_DIR, mod_name)
    os.makedirs(mod_path, exist_ok=True)
    
    with open(os.path.join(mod_path, "mod.py"), "wb") as f:
        f.write(file.file.read())
        
    trigger_hot_reload()
    return web.json_response({"message": "上传成功！若主服务在运行，已触发热重载。"})

async def api_toggle_mod(request):
    """通过修改文件夹前缀（添加/删除 '.'）实现物理禁用/启用"""
    name = request.match_info['name']
    name = "".join([c for c in name if c.isalnum() or c in ('_', '-')])
    
    active_path = os.path.join(MODS_DIR, name)
    disabled_path = os.path.join(MODS_DIR, f".{name}")

    if os.path.exists(active_path): # 禁用
        os.rename(active_path, disabled_path)
        msg = f"已禁用模块 {name}"
    elif os.path.exists(disabled_path): # 启用
        os.rename(disabled_path, active_path)
        msg = f"已启用模块 {name}"
    else:
        return web.json_response({"error": f"找不到模块: {name}"}, status=404)
    
    trigger_hot_reload()
    return web.json_response({"message": f"{msg}。若主服务在运行，已触发热重载。"})

async def api_delete_mod(request):
    """物理删除 Mod"""
    name = request.match_info['name']
    name = "".join([c for c in name if c.isalnum() or c in ('_', '-')])
    
    active_path = os.path.join(MODS_DIR, name)
    disabled_path = os.path.join(MODS_DIR, f".{name}")
    
    target = active_path if os.path.exists(active_path) else (disabled_path if os.path.exists(disabled_path) else None)
    if target:
        shutil.rmtree(target)
        trigger_hot_reload()
        return web.json_response({"message": "物理删除模块成功"})
    return web.json_response({"error": "找不到该模块"}, status=404)

async def api_preview_mod(request):
    """直接读取 mod.py 文件内容预览"""
    name = request.match_info['name']
    name = "".join([c for c in name if c.isalnum() or c in ('_', '-')])
    
    path = os.path.join(MODS_DIR, name, "mod.py")
    if not os.path.exists(path):
        path = os.path.join(MODS_DIR, f".{name}", "mod.py")
        
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/plain")
    return web.json_response({"error": "未找到 mod.py 源码"}, status=404)

async def api_get_logs(request):
    """读取日志文件"""
    log_type = request.match_info['type']
    cfg = load_config()
    log_cfg = cfg.get("logging", {})
    
    file_key = "server_log" if log_type == "server" else "error_log"
    log_path = log_cfg.get(file_key, f"logs/server.log" if log_type == "server" else "logs/server_error.log")
    if not os.path.isabs(log_path):
        log_path = os.path.join(PROJECT_ROOT, log_path)
        
    lines_to_read = int(request.query.get("lines", 100))
    
    if not os.path.exists(log_path): 
        return web.json_response({"logs": f"暂无日志文件。路径：{log_path}"})
        
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()[-lines_to_read:]
        return web.json_response({"logs": "".join(content)})
    except Exception as e:
        return web.json_response({"logs": f"读取日志失败: {e}"})

# --- 初始化 APP 与 静态文件托管 ---
app = web.Application(middlewares=[auth_middleware])

# API 注册
app.router.add_post('/api/login', api_login)
app.router.add_get('/api/status', api_system_status)
app.router.add_post('/api/control', api_control_service)
app.router.add_get('/api/mods', api_list_mods)
app.router.add_post('/api/mods/upload', api_upload_mod)
app.router.add_post('/api/mods/{name}/toggle', api_toggle_mod)
app.router.add_delete('/api/mods/{name}', api_delete_mod)
app.router.add_get('/api/mods/{name}/preview', api_preview_mod)
app.router.add_get('/api/logs/{type}', api_get_logs)

# 静态资源处理
frontend_path = os.path.join(PROJECT_ROOT, "web_frontend")
if os.path.exists(frontend_path):
    # 注释掉了这行以防止目录不存在导致的崩溃
    # app.router.add_static('/static/', os.path.join(frontend_path, 'static'), name='static', show_index=True)
    
    async def handle_index(request):
        return web.FileResponse(os.path.join(frontend_path, 'index.html'))
        
    app.router.add_get('/', handle_index)
    app.router.add_get('/index.html', handle_index)

if __name__ == '__main__':
    config = load_config()
    web_cfg = config.get("web_panel", {})
    host = web_cfg.get("host", "0.0.0.0")
    port = web_cfg.get("port", 8080)
    
    print("=" * 50)
    print(f"Modular-MC-AI 独立图形化运维面板已启动")
    print(f"访问地址: http://{host}:{port}")
    print("=" * 50)
    
    web.run_app(app, host=host, port=port)