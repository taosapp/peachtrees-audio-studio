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

# ── 跨平台能力统一走 core.platform ─────────────────────────────────────────────
# 通过将 backend 目录加入 sys.path，让 manage.py 也能复用 backend 内的平台抽象
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.join(_SCRIPT_DIR, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from core.platform import (
    IS_WINDOWS,
    IS_MACOS,
    IS_LINUX,
    is_port_in_use,
    get_pids_by_port,
    kill_process_by_port,
    has_fastapi,
    resolve_python,
    no_window_flag,
)

BACKEND_PORT = 8000
# 阶段2起前端由后端静态托管，FRONTEND_PORT 仅在开发模式下使用
FRONTEND_PORT = 5173

# ANSI 颜色定义（Windows 10+ 默认支持）
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"

def log_info(msg):
    print(f"{BLUE}[信息]{RESET} {msg}")

def log_success(msg):
    print(f"{GREEN}[成功]{RESET} {msg}")

def log_warning(msg):
    print(f"{YELLOW}[警告]{RESET} {msg}")

def log_error(msg):
    print(f"{RED}[错误]{RESET} {msg}")


def _open_service_log(name: str):
    """打开服务日志文件（追加模式），供后台进程写入输出"""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{name}.log")
    return open(log_path, "a", encoding="utf-8", buffering=1)


def _resolve_python_with_log():
    """resolve_python 的日志包装：保留原有的用户提示"""
    # 1) 环境变量显式指定
    override = os.environ.get("PEACHTREES_PYTHON", "").strip().strip('"')
    if override:
        if os.path.isfile(override) and has_fastapi(override):
            log_success(f"使用 PEACHTREES_PYTHON 指定环境: {override}")
            return override
        log_warning(
            f"PEACHTREES_PYTHON 指定的解释器无效或缺少后端依赖: {override}"
        )

    python_exe = resolve_python()
    # 兜底报错提示（与原逻辑一致）
    if not has_fastapi(python_exe):
        log_error(
            "未找到带 fastapi 依赖的 Python 环境！请先运行 install_deps.* 安装依赖，"
            "或激活 conda 环境后重试（如: conda activate fastapi）"
        )
    elif python_exe != sys.executable:
        log_success(f"已自动切换到后端环境: {python_exe}")
    return python_exe


def start_services():
    """启动后端服务（后台运行，不打开新终端窗口，日志写入 logs/ 目录）

    阶段2 改造：前端已由后端静态托管，不再需要独立的 Vite 进程。
    开发模式下若需前端热更新，可手动在 frontend/ 运行 `npm run dev`。
    """
    # 1. 检查端口占用情况并清理
    backend_running = is_port_in_use(BACKEND_PORT)

    if backend_running:
        log_warning("检测到后端端口已被占用！")
        log_warning(f"端口 {BACKEND_PORT} (后端) 已被占用")
        log_info("正在尝试清理已有服务进程...")
        stop_services()
        time.sleep(1.5)

    log_info("正在启动后端服务 (FastAPI / Uvicorn)...")
    # 自动探测带依赖的 Python 解释器（PATH 中的默认 python 可能缺少 fastapi）
    python_exe = _resolve_python_with_log()
    log_info(f"后端解释器: {python_exe}")
    # 生产模式不启用 --reload：reload 的重载器在重启时会直接杀死进程树，
    # 导致 TTS 推理 worker 子进程变成孤儿进程，持续占用 GPU 显存。
    backend_cmd = f'"{python_exe}" -m uvicorn main:app --host 0.0.0.0 --port {BACKEND_PORT}'
    backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")

    try:
        # 后台启动（无新窗口）：输出重定向到日志文件，便于排查问题
        backend_log = _open_service_log("backend")
        # 强制 UTF-8 输出：日志文件重定向下 Python 默认用系统 GBK 编码，
        # 遇到 emoji（如 ✅）会抛 UnicodeEncodeError 导致启动失败，
        # 注入 PYTHONIOENCODING/PYTHONUTF8 后输出统一为 UTF-8。
        _backend_env = dict(os.environ)
        _backend_env["PYTHONIOENCODING"] = "utf-8"
        _backend_env["PYTHONUTF8"] = "1"
        subprocess.Popen(
            backend_cmd,
            cwd=backend_dir,
            shell=True,
            env=_backend_env,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            creationflags=no_window_flag(),
        )
        log_success("后端服务已后台启动（日志: logs/backend.log）")
    except Exception as e:
        log_error(f"后端启动失败: {e}")
        return

    # 等待几秒检测服务是否正常起来
    log_info("正在等待服务就绪，检测端口占用中...")
    for _ in range(6):
        time.sleep(1)
        if is_port_in_use(BACKEND_PORT):
            break

    show_status()

def stop_services():
    """停止后端服务"""
    log_info("开始关闭后端服务...")
    backend_stopped = kill_process_by_port(BACKEND_PORT)

    if backend_stopped:
        log_success("后端服务已全部关闭。")
    else:
        log_warning("部分服务可能未完全关闭，请手动检查。")

def build_frontend():
    """构建前端到 backend/static（阶段2：前端静态托管）

    需先在 frontend/ 安装依赖：`npm install`
    """
    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
    if not os.path.isdir(frontend_dir):
        log_error(f"前端目录不存在: {frontend_dir}")
        return

    node_modules = os.path.join(frontend_dir, "node_modules")
    if not os.path.isdir(node_modules):
        log_info("前端依赖未安装，正在执行 npm install...")
        try:
            subprocess.run(
                "npm install", cwd=frontend_dir, shell=True, check=True,
                creationflags=no_window_flag(),
            )
        except subprocess.CalledProcessError as e:
            log_error(f"npm install 失败: {e}")
            return

    log_info("正在构建前端到 backend/static/...")
    try:
        subprocess.run(
            "npm run build", cwd=frontend_dir, shell=True, check=True,
            creationflags=no_window_flag(),
        )
        log_success("前端构建完成，访问 http://localhost:8000 查看界面")
    except subprocess.CalledProcessError as e:
        log_error(f"前端构建失败: {e}")


def show_status():
    """查看服务状态"""
    print("\n" + "="*45)
    print("         PeachTrees 服务运行状态        ")
    print("="*45)

    backend_pids = get_pids_by_port(BACKEND_PORT)

    if backend_pids:
        print(f"后端服务 (端口 {BACKEND_PORT}): {GREEN}● 运行中{RESET} (PID: {backend_pids})")
        print(f"  └─ 访问地址: {BLUE}http://localhost:{BACKEND_PORT}{RESET}")
        print(f"  └─ API 文档: {BLUE}http://localhost:{BACKEND_PORT}/docs{RESET}")
    else:
        print(f"后端服务 (端口 {BACKEND_PORT}): {RED}○ 已停止{RESET}")
    print("="*45 + "\n")
    print(f"服务日志目录: {BLUE}logs/{RESET}（backend.log，可随时查看服务输出）\n")

def main():
    # 修复 Windows 控制台颜色输出支持
    if IS_WINDOWS:
        os.system('color')

    if len(sys.argv) < 2:
        print("用法: python manage.py [start|stop|restart|status|build]")
        print("  - start:   启动后端服务（前端已由后端静态托管）")
        print("  - stop:    关闭后端服务")
        print("  - restart: 重启后端服务")
        print("  - status:  查看服务运行状态")
        print("  - build:   构建前端到 backend/static（需先安装 frontend 依赖）")
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
    elif action == "build":
        build_frontend()
    else:
        log_error(f"未知指令: {action}")
        print("支持指令: start, stop, restart, status, build")

if __name__ == "__main__":
    main()
