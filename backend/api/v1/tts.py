"""
TTS API（文本转语音 / 声音克隆）
音色管理 + 音频下载；语音合成走 /v1/tts/submit 异步任务（见 api/v1/tasks.py）
"""
import os
import uuid
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from core.database import get_db
from core.config import get_settings
from services import tts_service

router = APIRouter(prefix="/v1/tts", tags=["文本转语音"])
settings = get_settings()

# 音频格式白名单（按扩展名校验，防止上传任意文件）
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".webm"}


async def _save_upload_file_streaming(
    upload: UploadFile,
    dst_path: Path,
    max_bytes: int | None = None,
    chunk_size: int = 1024 * 1024,
):
    """流式保存上传文件；超过 max_bytes 时删除临时文件并抛 413"""
    total = 0
    with open(dst_path, "wb") as out:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes and total > max_bytes:
                out.close()
                os.remove(dst_path)
                raise HTTPException(
                    413,
                    f"文件过大：最大支持 {max_bytes // (1024 * 1024)}MB",
                )
            out.write(chunk)
    await upload.close()


def _check_audio_ext(filename: str) -> str:
    """校验上传文件扩展名，返回小写扩展名（含点）；不合法抛 400"""
    ext = (Path(filename).suffix or "").lower()
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(
            400,
            f"不支持的音频格式「{ext or '未知'}」，支持: {', '.join(sorted(ALLOWED_AUDIO_EXTS))}",
        )
    return ext


# ── 音色管理 ─────────────────────────────────────────────────────────────────

@router.get("/voices")
async def get_voices(
    db: AsyncSession = Depends(get_db),
):
    """获取已保存的音色列表"""
    voices = await tts_service.list_voices(db)
    return {"voices": voices}


@router.post("/voices")
async def upload_voice(
    ref_audio: UploadFile = File(...),
    ref_text: str = Form(""),
    voice_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    上传参考音频，保存音色。

    - **ref_audio**: 参考音频文件（建议 3-30 秒，支持 wav/mp3/flac）
    - **ref_text**: 参考音频的文字内容
    - **voice_name**: 音色名称（如：主播小美）
    """
    tmp_path = None
    try:
        # 保存上传文件（校验格式与大小）
        ext = _check_audio_ext(ref_audio.filename or "")
        tmp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}{ext}")
        await _save_upload_file_streaming(
            ref_audio,
            Path(tmp_path),
            max_bytes=settings.max_upload_mb * 1024 * 1024,
        )

        # save_voice 内部需要与推理 worker 进程同步交互（最长可达 120s），
        # 必须在线程池中执行，避免阻塞事件循环导致其他接口无响应。
        voice = await run_in_threadpool(
            tts_service.save_voice,
            ref_audio_path=tmp_path,
            ref_text=ref_text,
            voice_name=voice_name,
        )
        await tts_service.save_voice_to_db(voice, db)
        return {"message": f"音色「{voice_name}」保存成功", "voice": voice}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.delete("/voices/{voice_name}")
async def remove_voice(
    voice_name: str,
    db: AsyncSession = Depends(get_db),
):
    """删除指定音色"""
    try:
        await tts_service.delete_voice(voice_name, db)
    except tts_service.VoiceNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"message": f"音色「{voice_name}」已删除"}


@router.get("/voices/{voice_name}/audio")
async def get_voice_audio(
    voice_name: str,
    db: AsyncSession = Depends(get_db),
):
    """获取音色的参考音频文件，用于前端试听"""
    from sqlalchemy import select
    from models.voice import Voice

    r = await db.execute(select(Voice).where(Voice.name == voice_name))
    voice = r.scalar_one_or_none()
    if not voice:
        raise HTTPException(404, f"音色「{voice_name}」不存在")

    audio_path = tts_service._voice_audio_path(voice)
    if not os.path.exists(audio_path):
        raise HTTPException(404, "音频文件不存在")

    return FileResponse(
        path=audio_path,
        filename=f"{voice_name}.wav",
        media_type="audio/wav",
    )


# ── 语音合成 ─────────────────────────────────────────────────────────────────

@router.get("/download/{filename}")
async def download_audio(
    filename: str,
):
    """下载合成的音频文件"""
    # 安全检查：只允许下载 tts_outputs 目录下的文件
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    safe_dir = os.path.normpath(os.path.join(backend_dir, "tts_outputs"))

    # 拒绝绝对路径与路径穿越（旧实现用 startswith 前缀匹配，
    # 可被 tts_outputs_evil 之类的同前缀目录绕过，改用 commonpath 精确校验）
    if os.path.isabs(filename) or ".." in filename.replace("/", os.sep).split(os.sep):
        raise HTTPException(403, "禁止访问该文件")
    file_path = os.path.normpath(os.path.join(safe_dir, filename))
    if os.path.commonpath([safe_dir, file_path]) != safe_dir:
        raise HTTPException(403, "禁止访问该文件")
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise HTTPException(404, "文件不存在")

    return FileResponse(
        path=file_path,
        filename=os.path.basename(filename),
        media_type="audio/wav",
    )
