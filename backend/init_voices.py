"""
音色库初始化脚本
所有音色由用户上传生成，不再预置系统音色。
"""
from pathlib import Path


async def init_system_voices():
    """初始化音色库（确保 voices 目录存在）"""
    voices_dir = Path(__file__).parent / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Voice Init] ✅ voices 目录已就绪: {voices_dir}")
    print("[Voice Init] 音色库为空，等待用户上传...")


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_system_voices())
