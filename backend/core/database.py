"""
数据库连接（仅 SQLite）
──────────────────────────────────────────────────
v2.3 起仅支持 SQLite，零配置启动：
数据库文件默认位于 backend/data/pt_media_studio.db（自动创建），
路径可通过 .env 的 DATABASE_URL 修改（必须是 sqlite+aiosqlite:/// 前缀）。
"""

import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

_db_url = settings.database_url

# 仅支持 SQLite：强制校验前缀，避免误配 MySQL URL 后产生难排查的错误
if not _db_url.startswith("sqlite"):
    raise RuntimeError(
        f"当前版本仅支持 SQLite 数据库，请检查 .env 中 DATABASE_URL 是否为 "
        f"sqlite+aiosqlite:/// 开头（当前值: {_db_url[:60]}...）"
    )

# Windows 路径归一化（反斜杠 → 正斜杠，SQLAlchemy URL 需要）
_db_url = _db_url.replace("\\", "/")
prefix = "sqlite+aiosqlite:///"
if _db_url.startswith(prefix):
    db_file = _db_url[len(prefix):]
    db_dir = os.path.dirname(db_file)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

engine = create_async_engine(
    _db_url,
    connect_args={"check_same_thread": False},  # aiosqlite 跨线程访问必需
)

@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    # WAL 模式：读写不互斥，显著提升并发性能
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def ensure_schema():
    """轻量迁移：为已存在的 SQLite 库补充新增列（create_all 不会修改已有表）"""
    from sqlalchemy import text

    async with engine.begin() as conn:
        # task_records.elapsed_sec：合成过程耗时（秒）
        rows = await conn.execute(text("PRAGMA table_info(task_records)"))
        cols = {r[1] for r in rows}
        if "elapsed_sec" not in cols:
            await conn.execute(text("ALTER TABLE task_records ADD COLUMN elapsed_sec FLOAT"))
        # task_records.seed：TTS 推理随机种子，用于复现生成结果
        if "seed" not in cols:
            await conn.execute(text("ALTER TABLE task_records ADD COLUMN seed INTEGER"))
        # task_records.progress：分片合成进度（0-100）
        if "progress" not in cols:
            await conn.execute(text("ALTER TABLE task_records ADD COLUMN progress INTEGER"))


# 关键：在此处导入所有模型，确保 relationship 字符串引用能正确解析
# （SQLAlchemy 需要在 mapper 配置前看到所有关联的类）
from models.task       import TaskRecord  # noqa: F401, E402
from models.voice      import Voice      # noqa: F401, E402
