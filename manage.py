#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PeachTrees Media Studio - 服务管理脚本
支持启动、停止、重启和查看前后端服务状态。
"""
import os
import sys
import subprocess
import time
import socket
import re

BACKEND_PORT = 8000
FRONTEND_PORT = 5173

# ANSI 颜色定义（Windows 10+ 默认支持）
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"

# 检查系统类型
IS_WINDOWS = sys.platform == "win32"

def log_info(msg):
    print(f"{BLUE}[信息]{RESET} {msg}")

def log_success(msg):
    print(f"{GREEN}[成功]{RESET} {msg}")

def log_warning(msg):
    print(f"{YELLOW}[警告]{RESET} {msg}")

def log_error(msg):
    print(f"{RED}[错误]{RESET} {msg}")

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except socket.error:
            return True


def _has_fastapi(python_exe):
    """检测指定 Python 解释器是否安装后端运行依赖"""
    try:
        r = subprocess.run(
            [python_exe, "-c", "import fastapi, uvicorn, sqlalchemy, aiosqlite"],
            capture_output=True,
            timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _resolve_python():
    """
    返回可用的后端 Python 解释器：
    1. 当前运行 manage.py 的解释器（若已有依赖）
    2. 探测常见 conda 环境（fastapi / pytorch）
    3. 兜底返回当前解释器（错误信息会明确提示）
    """
    if _has_fastapi(sys.executable):
        return sys.executable

    log_warning(
        f"当前解释器缺少后端依赖 (fastapi/uvicorn/sqlalchemy/aiosqlite): {sys.executable}"
    )

    # 常见 conda 环境探测（相对当前解释器 + 常见安装位置）
    cur_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        os.path.join(cur_dir, "envs", "fastapi", "python.exe"),
        os.path.join(os.path.dirname(cur_dir), "envs", "fastapi", "python.exe"),
        r"D:\miniconda3\envs\fastapi\python.exe",
        os.path.expanduser(r"~\miniconda3\envs\fastapi\python.exe"),
        os.path.expanduser(r"~\anaconda3\envs\fastapi\python.exe"),
        os.path.expanduser(r"~\anaconda3\envs\pytorch\python.exe"),
    ]
    seen = set()
    for c in candidates:
        c = os.path.normpath(c)
        if c in seen or not os.path.isfile(c):
            continue
        seen.add(c)
        if _has_fastapi(c):
            log_success(f"已自动切换到后端环境: {c}")
            return c

    log_error(
        "未找到带 fastapi 依赖的 Python 环境！请先运行 install_deps.bat 安装依赖，"
        "或激活 conda 环境后重试（如: conda activate fastapi）"
    )
    return sys.executable

def get_pids_by_port(port):
    """通过 netstat 查询占用指定端口的进程 PID 列表"""
    pids = set()
    try:
        if IS_WINDOWS:
            # 运行 netstat 命令
            output = subprocess.check_output(f"netstat -ano", shell=True).decode('utf-8', errors='ignore')
            # 匹配对应端口
            pattern = re.compile(r"\s+TCP\s+\S+:" + str(port) + r"\s+\S+\s+\S+\s+(\d+)")
            for line in output.splitlines():
                match = pattern.search(line)
                if match:
                    pid = int(match.group(1))
                    if pid != 0:
                        pids.add(pid)
        else:
            # Unix-like (lsof)
            output = subprocess.check_output(f"lsof -t -i:{port}", shell=True).decode('utf-8', errors='ignore')
            for line in output.splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
    except Exception as e:
        log_error(f"查询端口 {port} 进程失败: {e}")
    return list(pids)

def kill_process_by_port(port):
    """强行关闭占用指定端口的进程"""
    pids = get_pids_by_port(port)
    if not pids:
        log_info(f"端口 {port} 未被占用")
        return True
    
    log_info(f"发现端口 {port} 被进程 {pids} 占用，正在关闭...")
    success = True
    for pid in pids:
        if pid == 0:
            continue
        try:
            if IS_WINDOWS:
                # 使用 taskkill 强行结束进程及其子进程
                subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log_success(f"已强制结束 PID 为 {pid} 的进程及其整个子进程树")
            else:
                subprocess.run(f"kill -9 {pid}", shell=True)
                log_success(f"已结束 PID 为 {pid} 的进程")
        except Exception as e:
            log_error(f"结束 PID 为 {pid} 的进程失败: {e}")
            success = False
    return success

def start_services():
    """启动前后端服务"""
    # 1. 检查端口占用情况并清理
    backend_running = is_port_in_use(BACKEND_PORT)
    frontend_running = is_port_in_use(FRONTEND_PORT)

    if backend_running or frontend_running:
        log_warning("检测到部分服务端口已被占用！")
        if backend_running:
            log_warning(f"端口 {BACKEND_PORT} (后端) 已被占用")
        if frontend_running:
            log_warning(f"端口 {FRONTEND_PORT} (前端) 已被占用")
        log_info("正在尝试清理已有服务进程...")
        stop_services()
        time.sleep(1.5)

    log_info("正在启动后端服务 (FastAPI / Uvicorn)...")
    # 自动探测带依赖的 Python 解释器（PATH 中的默认 python 可能缺少 fastapi）
    python_exe = _resolve_python()
    log_info(f"后端解释器: {python_exe}")
    # 生产模式不启用 --reload：reload 的重载器在重启时会直接杀死进程树，
    # 导致 TTS 推理 worker 子进程变成孤儿进程，持续占用 GPU 显存。
    backend_cmd = f'"{python_exe}" -m uvicorn main:app --host 0.0.0.0 --port {BACKEND_PORT}'
    backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
    
    try:
        if IS_WINDOWS:
            # 在 Windows 上启动新独立 cmd 窗口，使用简单无嵌套外引号的写法，极其稳定
            subprocess.Popen(f'start "PeachTrees 后端 API 服务" cmd /k cd /d "{backend_dir}" ^&^& {backend_cmd}', shell=True)
        else:
            # Unix-like 运行后台进程
            subprocess.Popen(backend_cmd, cwd=backend_dir, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_success("后端服务启动指令已成功发送")
    except Exception as e:
        log_error(f"后端启动失败: {e}")
        return

    log_info("正在启动前端服务 (Vite)...")
    frontend_cmd = "npm run dev"
    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
    
    try:
        if IS_WINDOWS:
            # 在 Windows 上启动新独立 cmd 窗口，使用简单无嵌套外引号的写法，极其稳定
            subprocess.Popen(f'start "PeachTrees 前端 Dev 服务" cmd /k cd /d "{frontend_dir}" ^&^& {frontend_cmd}', shell=True)
        else:
            # Unix-like 运行后台进程
            subprocess.Popen(frontend_cmd, cwd=frontend_dir, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log_success("前端服务启动指令已成功发送")
    except Exception as e:
        log_error(f"前端启动失败: {e}")
        return

    # 等待几秒检测服务是否正常起来
    log_info("正在等待服务就绪，检测端口占用中...")
    for _ in range(6):
        time.sleep(1)
        if is_port_in_use(BACKEND_PORT) and is_port_in_use(FRONTEND_PORT):
            break

    show_status()

def stop_services():
    """停止前后端服务"""
    log_info("开始关闭前后端服务...")
    backend_stopped = kill_process_by_port(BACKEND_PORT)
    frontend_stopped = kill_process_by_port(FRONTEND_PORT)
    
    if backend_stopped and frontend_stopped:
        log_success("前后端服务已全部关闭。")
    else:
        log_warning("部分服务可能未完全关闭，请手动检查。")

def show_status():
    """查看服务状态"""
    print("\n" + "="*45)
    print("         PeachTrees 服务运行状态        ")
    print("="*45)
    
    backend_pids = get_pids_by_port(BACKEND_PORT)
    frontend_pids = get_pids_by_port(FRONTEND_PORT)
    
    if backend_pids:
        print(f"后端服务 (端口 {BACKEND_PORT}): {GREEN}● 运行中{RESET} (PID: {backend_pids})")
        print(f"  └─ API 接口文档: {BLUE}http://localhost:{BACKEND_PORT}/docs{RESET}")
    else:
        print(f"后端服务 (端口 {BACKEND_PORT}): {RED}○ 已停止{RESET}")
        
    if frontend_pids:
        print(f"前端服务 (端口 {FRONTEND_PORT}): {GREEN}● 运行中{RESET} (PID: {frontend_pids})")
        print(f"  └─ 前端访问地址: {BLUE}http://localhost:{FRONTEND_PORT}{RESET}")
    else:
        print(f"前端服务 (端口 {FRONTEND_PORT}): {RED}○ 已停止{RESET}")
    print("="*45 + "\n")

def main():
    # 修复 Windows 控制台颜色输出支持
    if IS_WINDOWS:
        os.system('color')

    if len(sys.argv) < 2:
        print("用法: python manage.py [start|stop|restart|status]")
        print("  - start:   启动前后端服务")
        print("  - stop:    关闭前后端服务")
        print("  - restart: 重启前后端服务")
        print("  - status:  查看服务运行状态")
        return

    action = sys.argv[1].lower()
    if action == "start":
        start_services()
    elif action == "stop":
        stop_services()
    elif action == "restart":
        log_info("正在重启服务...")
        stop_services()
        time.sleep(1.5)
        start_services()
    elif action == "status":
        show_status()
    else:
        log_error(f"未知指令: {action}")
        print("支持指令: start, stop, restart, status")

if __name__ == "__main__":
    main()
