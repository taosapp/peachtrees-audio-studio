"""
全局 TTS 任务锁：单机单 worker，同一时间只允许一个
合成/音色特征提取任务占用推理进程。
"""
import threading
from typing import Optional

_tts_lock = threading.Lock()

# 当前正在运行的任务信息（供状态接口查询展示）
_current_task: Optional[dict] = None


def acquire_tts_lock(task_type: str = "tts", description: str = "") -> bool:
    """尝试获取 TTS 锁（线程安全），成功后记录当前任务供状态接口查询"""
    global _current_task
    if not _tts_lock.acquire(blocking=False):
        return False
    _current_task = {
        "task_type": task_type,
        "task_id": None,
        "description": description,
    }
    return True


def release_tts_lock():
    """释放 TTS 锁并清除当前任务记录"""
    global _current_task
    try:
        _tts_lock.release()
    except RuntimeError:
        pass  # 锁未持有
    _current_task = None


def is_tts_running() -> bool:
    """检查是否有合成任务正在运行"""
    return _tts_lock.locked()


def get_current_task() -> Optional[dict]:
    """获取当前正在运行的任务信息"""
    return _current_task


def get_all_task_status() -> dict:
    """获取任务状态汇总（供 /v1/models/* 状态接口使用）"""
    return {
        "tts_running": is_tts_running(),
        "current_task": get_current_task(),
    }
