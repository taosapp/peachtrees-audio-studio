"""
全局任务锁 - 确保同一时间只有一个任务在执行
"""
import asyncio
from typing import Optional

# 异步任务锁（用于 ASR/字幕任务）
_task_lock = asyncio.Lock()

# 当前正在运行的任务信息
_current_task: Optional[dict] = None


async def acquire_task(task_type: str, task_id: str, description: str = "") -> bool:
    """
    尝试获取任务锁
    Returns: True 表示获取成功，False 表示有其他任务正在运行
    """
    global _current_task
    
    if _task_lock.locked():
        return False
    
    await _task_lock.acquire()
    _current_task = {
        "task_type": task_type,
        "task_id": task_id,
        "description": description,
    }
    return True


def release_task():
    """释放任务锁"""
    global _current_task
    try:
        _task_lock.release()
    except RuntimeError:
        pass  # 锁未持有
    _current_task = None


def get_current_task() -> Optional[dict]:
    """获取当前正在运行的任务信息"""
    return _current_task


def is_task_running() -> bool:
    """检查是否有任务正在运行"""
    return _task_lock.locked()


# TTS 使用线程锁（同步代码）
import threading
_tts_lock = threading.Lock()

def acquire_tts_lock(task_type: str = "tts", description: str = "") -> bool:
    """尝试获取 TTS 锁（线程安全），成功后同步记录当前任务供状态接口查询"""
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
        pass
    _current_task = None

def is_tts_running() -> bool:
    """检查 TTS 是否正在运行"""
    return _tts_lock.locked()


def get_all_task_status() -> dict:
    """获取所有任务状态（用于 API 查询）"""
    return {
        "asr_running": is_task_running(),
        "tts_running": is_tts_running(),
        "current_task": get_current_task(),
    }