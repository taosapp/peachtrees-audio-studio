import sys
import os

# 修复 Windows 上 getpass.getuser() 的兼容性问题
# Python 3.12 在 Windows 上可能错误地调用 os.getuid()（Unix 专用）
import getpass
_orig_getuser = getpass.getuser
def _patched_getuser():
    # 优先使用环境变量（Windows: USERNAME, Unix: USER）
    name = os.getenv("USERNAME") or os.getenv("USER") or "user"
    return name
getpass.getuser = _patched_getuser

# Windows 兼容：防止 aiomysql/pymysql 触发 pwd 模块导入（Unix 专用）
# 注入假的 pwd 模块作为最后防线
import types
_pwd_module = types.ModuleType("pwd")
class _FakePwdEntry:
    pw_name = os.getenv("USERNAME", "user")
    def __getitem__(self, idx):
        if idx == 0:
            return self.pw_name
        return ""
_pwd_module.getpwuid = lambda uid: _FakePwdEntry()
sys.modules["pwd"] = _pwd_module

from contextlib import asynccontextmanager

from api.v1 import tts, tasks, models
from core.config import get_settings
from core.database import Base, engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from init_voices import init_system_voices

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_system_voices()
    yield
    await engine.dispose()


app = FastAPI(
    title="PeachTrees Media Studio API",
    version="2.1.0",
    description="基于 CosyVoice3 的本地声音克隆与语音合成平台",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router, prefix="/api")
app.include_router(tts.router, prefix="/api")
app.include_router(models.router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "PeachTrees Media Studio API", "version": "2.1.0", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
