import sys
import os

# Windows 兼容性补丁：仅在 Windows 上执行
# macOS/Linux 原生支持 getpass.getuser() 和 pwd 模块，无需 patch
if sys.platform == "win32":
    # 修复 Windows 上 getpass.getuser() 的兼容性问题
    # Python 3.12 在 Windows 上可能错误地调用 os.getuid()（Unix 专用）
    import getpass
    _orig_getuser = getpass.getuser
    def _patched_getuser():
        # 优先使用环境变量（Windows: USERNAME, Unix: USER）
        name = os.getenv("USERNAME") or os.getenv("USER") or "user"
        return name
    getpass.getuser = _patched_getuser

    # 防止 aiomysql/pymysql 触发 pwd 模块导入（Unix 专用）
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
from pathlib import Path

from api.v1 import tts, tasks, models
from core.config import get_settings
from core.database import Base, engine, ensure_schema
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from init_voices import init_system_voices

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema()
    await init_system_voices()
    # 后台预加载 TTS 模型（不阻塞 API 启动；失败时首次合成自动加载兜底）
    try:
        import threading
        from services import tts_service

        threading.Thread(target=tts_service.preload_worker, daemon=True).start()
        print("[Startup] 已在后台启动模型预加载（约 1-3 分钟）")
    except Exception as e:
        print(f"[Startup] ⚠️ 模型预加载启动失败: {e}")
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
    # 阶段2：前端已由后端静态托管，开发模式仍可能用 5173
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router, prefix="/api")
app.include_router(tts.router, prefix="/api")
app.include_router(models.router, prefix="/api")


@app.get("/api")
async def api_root():
    return {"name": "PeachTrees Media Studio API", "version": "2.1.0", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── 阶段2：前端静态托管（SPA）───────────────────────────────────────────────────
# 构建产物位于 backend/static/（由 frontend/ 的 `npm run build` 生成）
# 若 static 目录不存在（未构建），则保留 JSON 根路由作为兜底
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_index_html = _STATIC_DIR / "index.html"

if _index_html.is_file():
    # 挂载静态资源（js/css/图片等）
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    # SPA history 路由 fallback：所有未匹配的非 /api 路径都返回 index.html
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str, request: Request):
        # 排除 API 和文档路径
        if full_path.startswith(("api/", "docs", "openapi.json", "health")):
            return {"detail": "Not Found"}
        # 优先尝试返回匹配的静态文件
        candidate = _STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # 否则返回 index.html（Vue Router 接管）
        return FileResponse(_index_html)
else:
    # 未构建前端时的兜底：保留原始 JSON 根路由
    @app.get("/")
    async def root():
        return {"name": "PeachTrees Media Studio API", "version": "2.1.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
