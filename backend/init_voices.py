"""
音色库初始化脚本
所有音色由用户上传生成，不再预置系统音色。
"""
from pathlib import Path


async def init_system_voices():
    """初始化音色库（确保 voices 目录存在）"""
    voices_dir = Path(__file__).parent / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Voice Init] OK voices 目录已就绪: {voices_dir}")

    # 真实检测数据库音色数量，避免误报"为空"
    try:
        from sqlalchemy import select, func
        from core.database import AsyncSessionLocal
        from models.voice import Voice

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(func.count()).select_from(Voice))
            count = r.scalar() or 0
    except Exception as e:
        print(f"[Voice Init] WARN 音色数量检测失败: {e}")
        return

    if count:
        print(f"[Voice Init] OK 音色库已就绪，当前共有 {count} 个音色")
    else:
        print("[Voice Init] 音色库为空，等待用户上传...")


if __name__ == "__main__":
    import asyncio
    asyncio.run(init_system_voices())
