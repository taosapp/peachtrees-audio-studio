"""
统一配置（v2.3）
──────────────────────────────────────────────────
合并了旧版根目录 config.py（路径常量）与 core/config.py（pydantic-settings）。
所有路径/数据库/限制项统一从这里读取，均可通过 backend/.env 覆盖。

注意：当前版本仅支持 SQLite 零配置启动（数据库文件位于 backend/data/pt_media_studio.db）。
"""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings

# backend 目录绝对路径（以本文件位置推导，不依赖进程 cwd）
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)


class Settings(BaseSettings):
    # ── 环境 ──
    app_name: str = "PeachTrees Media Studio"
    app_env: str = "development"

    # ── 数据库 ──
    # 仅支持 SQLite（零配置，文件位于 backend/data/pt_media_studio.db）
    database_url: str = f"sqlite+aiosqlite:///{_BACKEND_DIR}/data/pt_media_studio.db"

    # ── 模型/源码路径 ──
    cosyvoice_src_dir: str = f"{_BACKEND_DIR}/third_party/cosyvoice"
    matcha_src_dir: str = f"{_BACKEND_DIR}/third_party/matcha-tts"
    cosyvoice_model_dir: str = f"{_BACKEND_DIR}/models/CosyVoice"

    # ── 运行时数据路径 ──
    data_dir: str = f"{_BACKEND_DIR}/data"
    voices_dir: str = f"{_BACKEND_DIR}/voices"
    tts_outputs_dir: str = f"{_BACKEND_DIR}/tts_outputs"

    # ── 业务限制 ──
    # 上传参考音频大小上限（MB）
    max_upload_mb: int = 50
    # 参考音频最大时长（秒）：CosyVoice 底层 30s 限制，超出自动截断
    max_ref_seconds: float = 15.0
    # 合成输出目录最多保留文件数，超出删除最旧文件
    max_output_files: int = 500
    # 推理线程数（CPU 模式并行度；0 = torch 默认）
    tts_num_threads: int = 4

    class Config:
        # 固定使用 backend/.env（不依赖进程 cwd）
        env_file = f"{_BACKEND_DIR}/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# ── 兼容导出（旧代码从根 config.py 导入这些名字，现统一走这里）──────────
COSYVOICE_SRC_DIR = settings.cosyvoice_src_dir
MATCHA_SRC_DIR = settings.matcha_src_dir
COSYVOICE_MODEL_DIR = settings.cosyvoice_model_dir
VOICES_DIR = settings.voices_dir
TTS_OUTPUTS_DIR = settings.tts_outputs_dir
MAX_REF_SECONDS = settings.max_ref_seconds
MAX_OUTPUT_FILES = settings.max_output_files
