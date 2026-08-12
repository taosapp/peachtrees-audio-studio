import asyncio
import json
import os
import uuid
import tempfile
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from core.database import get_db, AsyncSessionLocal
from core.config import get_settings
from models.task import TaskRecord

router = APIRouter(prefix="/v1", tags=["声音克隆任务"])
settings = get_settings()


async def _process_tts_sync(
    task_db_id: int,
    ref_audio_path: str,
    ref_text: str,
    gen_text: str,
    speed: float,
    nfe_steps: int,
    cfg_strength: float,
    remove_silence: bool,
):
    """异步处理TTS合成（供 BackgroundTasks 调用）"""
    # 强制禁用 libtorchcodec（子进程 worker 已独立处理，此处双重保险）
    import os as _os_proc3
    _os_proc3.environ["TORCHAUDIO_DISABLE_TORCHCODEC"] = "1"
    import time as _time_proc

    from sqlalchemy import update as sa_update
    from services import tts_service

    _started = _time_proc.monotonic()

    try:
        async def _update_status(status: str, message: str = "", **kwargs):
            async with AsyncSessionLocal() as db:
                values = {"status": status, "message": message, **kwargs}
                stmt = sa_update(TaskRecord).where(TaskRecord.id == task_db_id).values(**values)
                await db.execute(stmt)
                await db.commit()

        # 区分首次加载与正常合成：worker 懒加载，首次合成需启动进程并加载模型
        _worker_loaded = False
        try:
            _proc = getattr(tts_service, "_worker_proc", None)
            _worker_loaded = (
                getattr(tts_service, "_worker_model_loaded", False)
                and _proc is not None and _proc.poll() is None
            )
        except Exception:
            pass
        if _worker_loaded:
            await _update_status("processing", "正在合成语音...")
        else:
            await _update_status("processing", "正在加载模型并合成（首次合成需 1-3 分钟）...")

        # 关键修复：generate_speech 是同步阻塞调用（内部轮询等待 worker 子进程结果，
        # 最长 300s）。若直接在事件循环中执行会阻塞整个 FastAPI 事件循环，
        # 导致合成期间所有 API（任务列表/状态查询等）都无法响应，
        # 前端表现为任务记录页一直 loading。必须放入线程池执行。
        result = await asyncio.to_thread(
            tts_service.generate_speech,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            gen_text=gen_text,
            speed=speed,
            nfe_steps=nfe_steps,
            cfg_strength=cfg_strength,
            remove_silence=remove_silence,
        )

        await _update_status(
            "done",
            "语音合成完成",
            result_path=result["output_path"],
            tts_duration_sec=result["duration_sec"],
            sample_rate=result["sample_rate"],
            elapsed_sec=round(_time_proc.monotonic() - _started, 2),
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        async with AsyncSessionLocal() as db:
            stmt = update(TaskRecord).where(TaskRecord.id == task_db_id).values(
                status="failed", message=str(e)[:400],
                elapsed_sec=round(_time_proc.monotonic() - _started, 2),
            )
            await db.execute(stmt)
            await db.commit()
    finally:
        if ref_audio_path and os.path.exists(ref_audio_path):
            try:
                os.remove(ref_audio_path)
            except Exception:
                pass


# ── API 路由 ─────────────────────────────────────────────────────────────────────


async def _save_upload_file_streaming(upload: UploadFile, dst_path: Path, chunk_size: int = 1024 * 1024):
    with open(dst_path, "wb") as out:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
    await upload.close()


@router.post("/tts/submit", status_code=202)
async def submit_tts(
    background_tasks: BackgroundTasks,
    voice_name: str = Form(...),
    gen_text: str = Form(...),
    speed: float = Form(1.2),
    nfe_steps: int = Form(32),
    cfg_strength: float = Form(2.5),
    remove_silence: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """提交TTS合成异步任务（使用已保存音色）"""
    from services import tts_service
    from services.task_lock import is_tts_running, get_current_task
    
    # 检查 TTS 是否有任务正在运行
    if is_tts_running():
        current = get_current_task()
        raise HTTPException(429, f"语音合成任务正在进行中，请等待完成后继续")

    # 校验音色
    voices = await tts_service.list_voices(db)
    voice_info = next((v for v in voices if v["name"] == voice_name), None)
    if not voice_info:
        available = [v["name"] for v in voices]
        raise HTTPException(404, f"音色「{voice_name}」不存在，可用音色: {available}")

    ref_audio_path = voice_info["ref_audio"]
    if not os.path.exists(ref_audio_path):
        raise HTTPException(500, f"音色「{voice_name}」的参考音频文件不存在: {ref_audio_path}")

    # 复制参考音频到临时位置（避免后台任务和主进程冲突）
    tmp_ref = tempfile.mktemp(suffix=".wav", prefix="ref_audio_")
    shutil.copy2(ref_audio_path, tmp_ref)

    ref_text = voice_info.get("ref_text", "")

    task_id = uuid.uuid4().hex
    task = TaskRecord(
        task_id=task_id,
        task_type="tts",
        filename=f"{voice_name}合成",
        voice_name=voice_name,
        gen_text=gen_text,
        language="zh",
        status="pending",
        message="等待合成...",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    background_tasks.add_task(
        _process_tts_sync,
        task.id,
        tmp_ref,
        ref_text,
        gen_text,
        speed,
        nfe_steps,
        cfg_strength,
        remove_silence,
    )

    queue_info = await _get_queue_info(db, task.id, "tts")

    return {
        "task_id": task_id,
        "task_type": "tts",
        "message": "TTS任务已提交，正在合成中...",
        "queue_position": queue_info["queue_position"],
        "total_pending": queue_info["total_pending"],
    }


async def _get_queue_info(db: AsyncSession, current_task_db_id: int, task_type: str) -> dict:
    """计算当前任务的排队位置和全局待处理数量"""
    # 全局 pending+processing 总数（所有用户，所有类型）
    total_r = await db.execute(
        select(func.count()).where(TaskRecord.status.in_(["pending", "processing"]))
    )
    total_pending = total_r.scalar() or 0

    # 当前任务在同类型队列中的位置（按创建时间排序）
    position_r = await db.execute(
        select(func.count()).where(
            TaskRecord.task_type == task_type,
            TaskRecord.status.in_(["pending", "processing"]),
            TaskRecord.id <= current_task_db_id,
        )
    )
    queue_position = position_r.scalar() or 1

    return {"total_pending": total_pending, "queue_position": queue_position}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """查询任务详情"""
    r = await db.execute(
        select(TaskRecord).where(TaskRecord.task_id == task_id)
    )
    task = r.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")

    # 如果任务还在排队/处理中，计算全局队列信息
    queue_info = {}
    if task.status in ("pending", "processing"):
        queue_info = await _get_queue_info(db, task.id, task.task_type)

    result = {
        "id": task.id,
        "task_id": task.task_id,
        "task_type": task.task_type,
        "filename": task.filename,
        "language": task.language,
        "status": task.status,
        "message": task.message,
        "created_at": str(task.created_at),
        "updated_at": str(task.updated_at),
        "queue_position": queue_info.get("queue_position"),
        "total_pending": queue_info.get("total_pending"),
    }

    # 按任务类型附加结果字段（当前仅保留 tts 类型）
    if task.task_type == "tts":
        result["voice_name"] = task.voice_name
        result["gen_text"] = task.gen_text
        result["elapsed_sec"] = task.elapsed_sec
        if task.status == "done" and task.result_path:
            result["result_filename"] = os.path.basename(task.result_path)
            result["tts_duration_sec"] = task.tts_duration_sec
            result["sample_rate"] = task.sample_rate

    return result


@router.get("/tasks")
async def list_tasks(
    page: int = 1,
    page_size: int = 10,
    task_type: str = "",
    status: str = "",
    keyword: str = "",
    db: AsyncSession = Depends(get_db),
):
    """查询任务列表，支持按类型/状态过滤"""
    query = select(TaskRecord)
    if task_type:
        query = query.where(TaskRecord.task_type == task_type)
    if status:
        query = query.where(TaskRecord.status == status)
    if keyword:
        query = query.where(TaskRecord.filename.contains(keyword))
    query = query.order_by(TaskRecord.created_at.desc())

    total_r = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_r.scalar()

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tasks = result.scalars().all()

    # 全局队列统计
    global_r = await db.execute(
        select(func.count()).where(TaskRecord.status.in_(["pending", "processing"]))
    )
    global_pending = global_r.scalar() or 0

    return {
        "total": total,
        "global_pending": global_pending,
        "items": [
            {
                "id": t.id,
                "task_id": t.task_id,
                "task_type": t.task_type,
                "filename": t.filename,
                "language": t.language,
                "status": t.status,
                "message": t.message,
                "voice_name": t.voice_name,
                "gen_text": t.gen_text[:50] + "..." if t.gen_text and len(t.gen_text) > 50 else t.gen_text,
                "created_at": str(t.created_at),
                "tts_duration_sec": t.tts_duration_sec,
                "elapsed_sec": t.elapsed_sec,
                "result_filename": os.path.basename(t.result_path) if t.status == "done" and t.result_path else None,
            }
            for t in tasks
        ],
    }


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除任务记录"""
    r = await db.execute(
        select(TaskRecord).where(TaskRecord.task_id == task_id)
    )
    task = r.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    await db.delete(task)
    await db.commit()
