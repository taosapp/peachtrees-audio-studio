#!/usr/bin/env bash
# PeachTrees Media Studio - Linux/macOS 依赖自动安装脚本
# 用法：
#   chmod +x install_deps.sh
#   ./install_deps.sh
set -e

# ── 颜色输出 ────────────────────────────────────────────────────────────────────
GREEN='\033[92m'
YELLOW='\033[93m'
RED='\033[91m'
BLUE='\033[94m'
RESET='\033[0m'

info()    { echo -e "${BLUE}[信息]${RESET} $1"; }
success() { echo -e "${GREEN}[成功]${RESET} $1"; }
warn()    { echo -e "${YELLOW}[警告]${RESET} $1"; }
error()   { echo -e "${RED}[错误]${RESET} $1"; }

# ── 平台检测 ────────────────────────────────────────────────────────────────────
OS_TYPE="$(uname -s)"
ARCH="$(uname -m)"

if [ "$OS_TYPE" = "Darwin" ]; then
    PLATFORM="macos"
elif [ "$OS_TYPE" = "Linux" ]; then
    PLATFORM="linux"
else
    error "不支持的操作系统: $OS_TYPE"
    exit 1
fi

info "检测到平台: $PLATFORM ($ARCH)"

# ── Python 检测 ─────────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v $cmd &>/dev/null; then
        PYTHON=$cmd
        break
    fi
done

if [ -z "$PYTHON" ]; then
    error "未找到 Python，请先安装 Python 3.10-3.12"
    if [ "$PLATFORM" = "macos" ]; then
        echo "  建议: brew install python@3.11"
    else
        echo "  建议: sudo apt install python3 python3-pip python3-venv"
    fi
    exit 1
fi

info "使用 Python: $($PYTHON --version)"

# ── FFmpeg 安装 ──────────────────────────────────────────────────────────────────
install_ffmpeg() {
    if command -v ffmpeg &>/dev/null; then
        success "FFmpeg 已安装: $(ffmpeg -version | head -1)"
        return 0
    fi

    info "正在安装 FFmpeg..."
    if [ "$PLATFORM" = "macos" ]; then
        if command -v brew &>/dev/null; then
            brew install ffmpeg
        else
            error "未找到 Homebrew，请先安装: https://brew.sh"
            return 1
        fi
    else
        # Linux: 检测包管理器
        if command -v apt-get &>/dev/null; then
            sudo apt-get update && sudo apt-get install -y ffmpeg
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y ffmpeg
        elif command -v yum &>/dev/null; then
            sudo yum install -y ffmpeg
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm ffmpeg
        else
            error "未识别的包管理器，请手动安装 FFmpeg"
            return 1
        fi
    fi

    if command -v ffmpeg &>/dev/null; then
        success "FFmpeg 安装完成"
    else
        error "FFmpeg 安装失败"
        return 1
    fi
}

install_ffmpeg

# ── 硬件模式选择 ────────────────────────────────────────────────────────────────
echo ""
echo "================================================="
echo "请选择运行硬件："
echo " [1] GPU (NVIDIA CUDA，支持极速推理 - 推荐)"
echo " [2] CPU (普通处理器，运行较慢)"
if [ "$PLATFORM" = "macos" ]; then
    echo " [3] MPS (Apple Silicon GPU，性能介于 CPU 和 CUDA 之间)"
fi
echo "================================================="
read -p "请输入选项序号 [1-3] 并按回车: " mode

INSTALL_TORCH_CUDA=false
INSTALL_TORCH_MPS=false
INSTALL_TORCH_CPU=false

case $mode in
    1)
        if [ "$PLATFORM" = "macos" ]; then
            warn "macOS 不支持 CUDA，将使用 MPS 模式"
            INSTALL_TORCH_MPS=true
        else
            INSTALL_TORCH_CUDA=true
        fi
        ;;
    2)
        INSTALL_TORCH_CPU=true
        ;;
    3)
        if [ "$PLATFORM" = "macos" ]; then
            INSTALL_TORCH_MPS=true
        else
            error "MPS 模式仅在 macOS 上可用"
            exit 1
        fi
        ;;
    *)
        error "无效选项: $mode"
        exit 1
        ;;
esac

# ── PyTorch 安装 ────────────────────────────────────────────────────────────────
if [ "$INSTALL_TORCH_CUDA" = "true" ]; then
    info "正在安装 PyTorch 2.6.0 (CUDA 12.6 GPU 版本)..."
    $PYTHON -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
elif [ "$INSTALL_TORCH_MPS" = "true" ]; then
    info "正在安装 PyTorch 2.6.0 (macOS MPS 版本)..."
    # macOS 上 PyPI 默认提供的 wheel 已包含 MPS 支持
    $PYTHON -m pip install torch==2.6.0 torchaudio==2.6.0
else
    info "跳过 PyTorch CUDA/MPS 版本，将安装标准 CPU 版..."
fi

# ── 业务依赖安装 ─────────────────────────────────────────────────────────────────
info "正在安装后端及 CosyVoice3 依赖..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIREMENTS="$SCRIPT_DIR/backend/requirements.txt"

if [ ! -f "$REQUIREMENTS" ]; then
    error "未找到 requirements.txt: $REQUIREMENTS"
    exit 1
fi

# 使用国内镜像加速（可通过 PIP_INDEX_URL 环境变量覆盖）
PIP_INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
$PYTHON -m pip install -r "$REQUIREMENTS" -i "$PIP_INDEX"

success "所有依赖安装完成！"
echo ""
echo "================================================="
echo "  🎉 PeachTrees 所有运行依赖已成功安装！"
echo "  现在可以运行: python manage.py start"
echo "  然后访问: http://localhost:8000"
echo "================================================="
