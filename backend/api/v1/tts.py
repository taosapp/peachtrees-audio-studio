"""
TTS API（文本转语音 / 声音克隆）
音色管理 + 语音合成
"""
import os
import uuid
import tempfile
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
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

@router.post("/synthesize")
async def synthesize_speech(
    ref_audio: UploadFile = File(...),
    ref_text: str = Form(""),
    gen_text: str = Form(...),
    speed: float = Form(1.0),
    nfe_steps: int = Form(32),
    cfg_strength: float = Form(2.5),
    remove_silence: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """
    上传参考音频 + 文本，直接合成克隆语音（同步返回音频文件）。

    - **ref_audio**: 参考音频文件（3-30 秒）
    - **ref_text**: 参考音频文字
    - **gen_text**: 要合成的文本内容
    - **speed**: 语速（0.5-2.0，默认 1.0）
    - **nfe_steps**: 推理步数（8-64，越大音质越好，默认 32）
    - **cfg_strength**: CFG 强度（1.0-5.0，默认 2.5）
    - **remove_silence**: 是否去除首尾静音
    """
    from sqlalchemy import select

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

        # 同步阻塞推理（最长 300s），放入线程池执行，避免卡死事件循环
        result = await run_in_threadpool(
            tts_service.generate_speech,
            ref_audio_path=tmp_path,
            ref_text=ref_text,
            gen_text=gen_text,
            speed=speed,
            nfe_steps=nfe_steps,
            cfg_strength=cfg_strength,
            remove_silence=remove_silence,
        )

        await db.commit()

        return {
            "output_path": result["output_path"],
            "duration_sec": result["duration_sec"],
            "sample_rate": result["sample_rate"],
            "info": result["info"],
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"合成失败: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.post("/synthesize/by_voice")
async def synthesize_by_saved_voice(
    voice_name: str = Form(...),
    gen_text: str = Form(...),
    speed: float = Form(1.0),
    nfe_steps: int = Form(32),
    cfg_strength: float = Form(2.5),
    remove_silence: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """
    使用已保存的音色合成语音（无需上传参考音频）。

    - **voice_name**: 音色名称（从 /tts/voices 获取）
    - **gen_text**: 要合成的文本内容
    - **speed / nfe_steps / cfg_strength / remove_silence**: 同上
    """
    import traceback
    from sqlalchemy import select
    import os
    from models.voice import Voice

    try:
        voices = await tts_service.list_voices(db)
        voice_info = next((v for v in voices if v["name"] == voice_name), None)
        if not voice_info:
            available = [v["name"] for v in voices]
            raise HTTPException(
                404,
                f"音色「{voice_name}」不存在！\n可用音色列表: {available if available else '（无）'}"
            )

        ref_audio_path = voice_info["ref_audio"]
        ref_text = voice_info.get("ref_text", "")  # 使用数据库中保存的参考文字，不清空
        ref_pt_path = voice_info.get("ref_pt")  # 音色特征文件（.pt），优先使用

        if not os.path.exists(ref_audio_path):
            available_files = tts_service._list_voice_files()
            raise HTTPException(
                500,
                f"音色「{voice_name}」的参考音频文件不存在！\n"
                f"尝试的路径: {ref_audio_path}\n"
                f"系统中的可用音频文件: {available_files}"
            )

        # 同步阻塞推理（最长 300s），放入线程池执行，避免卡死事件循环
        result = await run_in_threadpool(
            tts_service.generate_speech,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            gen_text=gen_text,
            speed=speed,
            nfe_steps=nfe_steps,
            cfg_strength=cfg_strength,
            remove_silence=remove_silence,
            ref_pt_path=ref_pt_path,
        )

        # 如果 worker 懒生成了 .pt 文件，更新数据库记录
        if result.get("generated_pt_path"):
            gen_pt = result["generated_pt_path"]
            gen_pt_rel = f"voices/{os.path.basename(gen_pt)}"
            print(f"[TTS API] 更新音色「{voice_name}」的 .pt 记录: {gen_pt_rel}", flush=True)
            r = await db.execute(select(Voice).where(Voice.name == voice_name))
            voice_rec = r.scalar_one_or_none()
            if voice_rec and not voice_rec.ref_pt:
                voice_rec.ref_pt = gen_pt_rel
                await db.commit()
                print(f"[TTS API] ✅ 数据库已更新", flush=True)

        return {
            "voice_name": voice_name,
            "output_path": result["output_path"],
            "duration_sec": result["duration_sec"],
            "sample_rate": result["sample_rate"],
            "info": result["info"],
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"合成失败: {type(e).__name__}: {e}")


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
