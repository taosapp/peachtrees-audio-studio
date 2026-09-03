#!/usr/bin/env bash
# PeachTrees Media Studio - Linux/macOS 服务管理脚本
# 用法：./manage.sh [start|stop|restart|status]

set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
MANAGE_PY="$SCRIPT_DIR/manage.py"

if [ ! -f "$MANAGE_PY" ]; then
    echo "[错误] 未找到 manage.py：$MANAGE_PY" >&2
    exit 1
fi

# 优先使用当前环境中的 python；否则使用 python3。
PYTHON_BIN=""
if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "[错误] 未找到 python 或 python3，请先安装 Python 3。" >&2
    exit 1
fi

# 使用脚本目录作为工作目录，确保 backend/frontend 的相对路径稳定。
cd "$SCRIPT_DIR" || exit 1

case "${1:-}" in
    start|stop|restart|status)
        exec "$PYTHON_BIN" "$MANAGE_PY" "$1"
        ;;
    "")
        echo "用法: $0 [start|stop|restart|status]"
        echo "  start:   启动前后端服务"
        echo "  stop:    关闭前后端服务"
        echo "  restart: 重启前后端服务"
        echo "  status:  查看服务运行状态"
        echo
        printf "请输入操作 [start/stop/restart/status]: "
        read -r action
        case "$action" in
            start|stop|restart|status)
                exec "$PYTHON_BIN" "$MANAGE_PY" "$action"
                ;;
            *)
                echo "[错误] 未知操作：$action" >&2
                exit 2
                ;;
        esac
        ;;
    -h|--help|help)
        echo "用法: $0 [start|stop|restart|status]"
        ;;
    *)
        echo "[错误] 未知操作：$1" >&2
        echo "支持操作: start, stop, restart, status" >&2
        exit 2
        ;;
esac
