"""
跨平台抽象层
──────────────────────────────────────────────────
统一封装 Windows / macOS / Linux 的平台差异：
- 平台标识
- FFmpeg 查找
- 端口进程管理
- Python 解释器探测
- 子进程窗口标志

所有平台相关逻辑应收敛到此处，业务代码只调用本模块。
"""

import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# ── 平台标识 ──────────────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
IS_UNIX_LIKE = not IS_WINDOWS  # macOS + Linux + 其他 Unix

# macOS 架构：Apple Silicon (arm64) vs Intel (x86_64)
IS_APPLE_SILICON = IS_MACOS and sys.platform == "darwin" and os.uname().machine == "arm64"


def no_window_flag() -> int:
    """Windows 下禁止子进程创建新控制台窗口；其他平台返回 0"""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ── FFmpeg 查找 ────────────────────────────────────────────────────────────────

def find_ffmpeg():
    """
    按优先级查找 ffmpeg 可执行文件（返回完整路径，找不到返回 None）。

    查找顺序：
    1. imageio-ffmpeg 内置二进制（跨平台）
    2. Windows: WinGet 包 / macOS: Homebrew / Linux: 系统包管理器路径
    3. PATH 中的 ffmpeg（shutil.which）
    """
    # 1. imageio-ffmpeg（跨平台，最可靠）
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe and os.path.isfile(ffmpeg_exe):
            try:
                result = subprocess.run(
                    [ffmpeg_exe, "-version"],
                    capture_output=True, text=True, timeout=5,
                )
                if "ffmpeg version" in result.stdout:
                    return ffmpeg_exe
            except Exception:
                pass
    except ImportError:
        pass

    # 2. 平台专用路径
    platform_candidates = _platform_ffmpeg_candidates()
    for ffmpeg_exe in platform_candidates:
        if ffmpeg_exe and os.path.isfile(ffmpeg_exe):
            try:
                result = subprocess.run(
                    [ffmpeg_exe, "-version"],
                    capture_output=True, text=True, timeout=5,
                )
                if "ffmpeg version" in result.stdout:
                    return ffmpeg_exe
            except Exception:
                pass

    # 3. PATH 中的 ffmpeg（排除 ImageMagick 误匹配）
    ff = shutil.which("ffmpeg")
    if ff and "ImageMagick" not in ff and os.path.isfile(ff):
        try:
            result = subprocess.run(
                [ff, "-version"],
                capture_output=True, text=True, timeout=5,
            )
            if "ffmpeg version" in result.stdout:
                return ff
        except Exception:
            pass

    return None


def _platform_ffmpeg_candidates():
    """返回当前平台下的 FFmpeg 候选路径列表"""
    candidates = []

    if IS_WINDOWS:
        # WinGet 安装的 Gyan.FFmpeg
        winget_base = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"
        )
        if os.path.isdir(winget_base):
            for entry in os.listdir(winget_base):
                if entry.startswith("Gyan.FFmpeg"):
                    for sub in os.listdir(os.path.join(winget_base, entry)):
                        bin_dir = os.path.join(winget_base, entry, sub, "bin")
                        candidates.append(os.path.join(bin_dir, "ffmpeg.exe"))
    elif IS_MACOS:
        # Homebrew 安装路径（Apple Silicon 和 Intel 不同）
        candidates.extend([
            "/opt/homebrew/bin/ffmpeg",       # Apple Silicon
            "/usr/local/bin/ffmpeg",          # Intel
        ])
    elif IS_LINUX:
        # 常见系统包管理器安装路径
        candidates.extend([
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/snap/bin/ffmpeg",              # Snap 包
        ])

    return candidates


def register_ffmpeg_path(ffmpeg_bin):
    """
    将 FFmpeg 所在目录注册到 DLL 搜索路径和 PATH（Windows 专用 add_dll_directory）。

    参数：find_ffmpeg() 返回的可执行文件路径
    """
    if not ffmpeg_bin:
        return None

    ffmpeg_dir = os.path.dirname(ffmpeg_bin)
    if not ffmpeg_dir:
        return None

    # Windows 专用：注册 DLL 搜索路径
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(ffmpeg_dir)
        except Exception:
            pass

    # 所有平台：加入 PATH
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    return ffmpeg_dir


# ── 端口进程管理 ────────────────────────────────────────────────────────────────

def is_port_in_use(port):
    """检测端口是否被监听"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except socket.error:
            return True


def get_pids_by_port(port):
    """
    查询监听指定端口的进程 PID 列表（仅统计 LISTENING 状态）。

    只认 LISTENING：TIME_WAIT / CLOSE_WAIT / ESTABLISHED 等残留连接
    不代表服务仍在运行，避免"已停止却显示运行中"的误报。
    """
    pids = set()
    try:
        if IS_WINDOWS:
            output = subprocess.check_output(
                f"netstat -ano", shell=True
            ).decode("utf-8", errors="ignore")
            pattern = re.compile(
                r"\s+TCP\s+\S+:" + str(port) + r"\s+\S+\s+LISTENING\s+(\d+)"
            )
            for line in output.splitlines():
                match = pattern.search(line)
                if match:
                    pid = int(match.group(1))
                    if pid != 0:
                        pids.add(pid)
        else:
            # Unix-like (lsof)：只看 TCP 监听状态的进程
            output = subprocess.check_output(
                f"lsof -t -iTCP:{port} -sTCP:LISTEN", shell=True
            ).decode("utf-8", errors="ignore")
            for line in output.splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
    except Exception:
        pass
    return list(pids)


def kill_process_by_port(port):
    """强行关闭占用指定端口的进程，返回是否成功"""
    pids = get_pids_by_port(port)
    if not pids:
        return True

    success = True
    for pid in pids:
        if pid == 0:
            continue
        try:
            if IS_WINDOWS:
                subprocess.run(
                    f"taskkill /F /T /PID {pid}", shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.run(f"kill -9 {pid}", shell=True)
        except Exception:
            success = False
    return success


# ── Python 解释器探测 ────────────────────────────────────────────────────────────

def has_fastapi(python_exe):
    """检测指定 Python 解释器是否安装后端运行依赖"""
    try:
        r = subprocess.run(
            [python_exe, "-c", "import fastapi, uvicorn, sqlalchemy, aiosqlite"],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def resolve_python():
    """
    返回可用的后端 Python 解释器：
    1. PEACHTREES_PYTHON 环境变量（显式指定，优先）
    2. 当前运行解释器（若已有依赖）
    3. 探测常见 conda / venv 环境（静默切换）
    4. 兜底返回当前解释器
    """
    # 1) 环境变量显式指定
    override = os.environ.get("PEACHTREES_PYTHON", "").strip().strip('"')
    if override:
        if os.path.isfile(override) and has_fastapi(override):
            return override

    # 2) 当前解释器已有依赖
    if has_fastapi(sys.executable):
        return sys.executable

    # 3) 常见 conda / venv 环境探测（跨平台路径）
    script_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidates = []

    if IS_WINDOWS:
        cur_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.extend([
            os.path.join(cur_dir, "envs", "fastapi", "python.exe"),
            os.path.join(os.path.dirname(cur_dir), "envs", "fastapi", "python.exe"),
            r"D:\miniconda3\envs\fastapi\python.exe",
            os.path.expanduser(r"~\miniconda3\envs\fastapi\python.exe"),
            os.path.expanduser(r"~\anaconda3\envs\fastapi\python.exe"),
            os.path.expanduser(r"~\anaconda3\envs\pytorch\python.exe"),
        ])
    else:
        # Unix-like: conda / venv 路径
        candidates.extend([
            os.path.expanduser("~/miniconda3/envs/fastapi/bin/python"),
            os.path.expanduser("~/anaconda3/envs/fastapi/bin/python"),
            os.path.expanduser("~/anaconda3/envs/pytorch/bin/python"),
            os.path.join(os.path.dirname(script_dir), "envs", "fastapi", "bin", "python"),
            os.path.join(os.path.dirname(os.path.dirname(script_dir)), "envs", "fastapi", "bin", "python"),
        ])

    # 项目内 venv
    project_root = Path(__file__).resolve().parent.parent.parent
    if IS_WINDOWS:
        candidates.append(str(project_root / ".venv" / "Scripts" / "python.exe"))
        candidates.append(str(project_root / "venv" / "Scripts" / "python.exe"))
    else:
        candidates.append(str(project_root / ".venv" / "bin" / "python"))
        candidates.append(str(project_root / "venv" / "bin" / "python"))

    seen = set()
    for c in candidates:
        c = os.path.normpath(c)
        if c in seen or not os.path.isfile(c):
            continue
        seen.add(c)
        if has_fastapi(c):
            return c

    # 4) 兜底
    return sys.executable
