import asyncio
import os
import uuid
import tempfile
import shutil

from fastapi import APIRouter, Depends, HTTPException, Form, BackgroundTasks
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
    remove_silence: bool,
    ref_pt_path: str = None,
    seed: int = 20260812,
):
    """异步处理TTS合成（供 BackgroundTasks 调用）"""
    # 强制禁用 libtorchcodec（子进程 worker 已独立处理，此处双重保险）
    import os as _os_proc3
    _os_proc3.environ["TORCHAUDIO_DISABLE_TORCHCODEC"] = "1"
    import time as _time_proc

    from services import tts_service
    from services.task_lock import is_tts_running

    _started = _time_proc.monotonic()

    # 分片合成进度（worker 回调线程只做内存写入，由下方协程定期落库）
    _progress = {"done": 0, "total": 0, "dirty": False}

    def _on_progress(p):
        try:
            done, total = int(p.get("done", 0)), int(p.get("total", 0))
        except Exception:
            return
        if total > 0 and (done != _progress["done"] or total != _progress["total"]):
            _progress.update(done=done, total=total, dirty=True)

    try:
        async def _update_status(status: str, message: str = "", **kwargs):
            async with AsyncSessionLocal() as db:
                values = {"status": status, "message": message, **kwargs}
                stmt = update(TaskRecord).where(TaskRecord.id == task_db_id).values(**values)
                await db.execute(stmt)
                await db.commit()

        # 并发兜底：submit 接口已有 429 预检，但两个提交可能同时通过预检。
        # 后执行的任务在此排队等待锁释放（而不是直接失败），最长等 20 分钟
        # （单任务 worker 超时 900s + 模型加载，一般足够）。
        if is_tts_running():
            await _update_status("pending", "排队等待中：有其他语音合成任务正在进行...")
            waited = 0
            while is_tts_running() and waited < 1200:
                await asyncio.sleep(2)
                waited += 2
            if is_tts_running():
                raise RuntimeError("排队超时（20分钟）：其他合成任务占用过久，请稍后重试")

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

        # 进度落库协程：每 1.5s 检查内存进度，有变化才写库（多片长文本才有进度）
        async def _progress_writer():
            last = (0, 0)
            while True:
                await asyncio.sleep(1.5)
                if not _progress["dirty"]:
                    continue
                _progress["dirty"] = False
                cur = (_progress["done"], _progress["total"])
                if cur == last or cur[1] <= 1:
                    continue
                last = cur
                pct = min(99, round(cur[0] * 100 / cur[1]))
                await _update_status(
                    "processing",
                    f"正在合成语音（第 {cur[0]}/{cur[1]} 段）...",
                    progress=pct,
                )

        writer_task = asyncio.create_task(_progress_writer())

        # 关键修复：generate_speech 是同步阻塞调用（内部轮询等待 worker 子进程结果，
        # 最长 300s）。若直接在事件循环中执行会阻塞整个 FastAPI 事件循环，
        # 导致合成期间所有 API（任务列表/状态查询等）都无法响应，
        # 前端表现为任务记录页一直 loading。必须放入线程池执行。
        try:
            result = None
            for _attempt in range(2):
                try:
                    result = await asyncio.to_thread(
                        tts_service.generate_speech,
                        ref_audio_path=ref_audio_path,
                        ref_text=ref_text,
                        gen_text=gen_text,
                        speed=speed,
                        remove_silence=remove_silence,
                        ref_pt_path=ref_pt_path,
                        seed=seed,
                        progress_cb=_on_progress,
                    )
                    break
                except RuntimeError as e:
                    # 等待期间音色保存等操作抢先占用 TTS 锁的小窗口竞态：
                    # 等锁释放后重试一次
                    if "正在进行" in str(e) and _attempt == 0:
                        await _update_status("pending", "检测到并发任务，排队等待中...")
                        while is_tts_running():
                            await asyncio.sleep(2)
                        continue
                    raise
        finally:
            # 先彻底停掉进度协程再写最终状态，避免 done 之后被进度写入覆盖回 processing
            writer_task.cancel()
            try:
                await writer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        await _update_status(
            "done",
            "语音合成完成",
            result_path=result["output_path"],
            tts_duration_sec=result["duration_sec"],
            sample_rate=result["sample_rate"],
            seed=seed,
            elapsed_sec=round(_time_proc.monotonic() - _started, 2),
            progress=100,
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
        # 音频是临时拷贝，若 worker 懒生成了同名 .pt 一并清理（临时文件无保留价值）
        if ref_audio_path:
            try:
                _sibling_pt = os.path.splitext(ref_audio_path)[0] + ".pt"
                if os.path.exists(_sibling_pt):
                    os.remove(_sibling_pt)
            except Exception:
                pass


# ── API 路由 ─────────────────────────────────────────────────────────────────────


@router.post("/tts/submit", status_code=202)
async def submit_tts(
    background_tasks: BackgroundTasks,
    voice_name: str = Form(...),
    gen_text: str = Form(...),
    speed: float = Form(1.2),
    remove_silence: bool = Form(True),
    seed: int = Form(20260812),
    db: AsyncSession = Depends(get_db),
):
    """提交TTS合成异步任务（使用已保存音色）"""
    from services import tts_service
    from services.task_lock import is_tts_running

    # 检查 TTS 是否有任务正在运行（后台任务执行时还会做排队兜底）
    if is_tts_running():
        raise HTTPException(429, "语音合成任务正在进行中，请等待完成后继续")

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
    # 显式传递持久化音色特征，避免临时参考音频路径无法匹配 .pt 文件。
    ref_pt_path = voice_info.get("ref_pt")
    if not ref_pt_path or not os.path.isfile(ref_pt_path):
        try:
            if os.path.exists(tmp_ref):
                os.remove(tmp_ref)
        except OSError:
            pass
        raise HTTPException(
            409,
            f"音色「{voice_name}」的音色特征文件缺失，请重新保存该音色后再合成",
        )

    task_id = uuid.uuid4().hex
    task = TaskRecord(
        task_id=task_id,
        task_type="tts",
        filename=f"{voice_name}合成",
        voice_name=voice_name,
        gen_text=gen_text,
        status="pending",
        message="等待合成...",
        seed=seed,
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
        remove_silence,
        ref_pt_path,
        seed,
    )

    return {
        "task_id": task_id,
        "task_type": "tts",
        "message": "TTS任务已提交，正在合成中...",
    }


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

    result = {
        "id": task.id,
        "task_id": task.task_id,
        "task_type": task.task_type,
        "filename": task.filename,
        "status": task.status,
        "message": task.message,
        "created_at": str(task.created_at),
        "updated_at": str(task.updated_at),
    }

    # 按任务类型附加结果字段（当前仅保留 tts 类型）
    if task.task_type == "tts":
        result["voice_name"] = task.voice_name
        result["gen_text"] = task.gen_text
        result["elapsed_sec"] = task.elapsed_sec
        result["seed"] = task.seed
        result["progress"] = task.progress
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

    return {
        "total": total,
        "items": [
            {
                "id": t.id,
                "task_id": t.task_id,
                "task_type": t.task_type,
                "filename": t.filename,
                "status": t.status,
                "message": t.message,
                "voice_name": t.voice_name,
                "gen_text": t.gen_text[:50] + "..." if t.gen_text and len(t.gen_text) > 50 else t.gen_text,
                "created_at": str(t.created_at),
                "tts_duration_sec": t.tts_duration_sec,
                "elapsed_sec": t.elapsed_sec,
                "seed": t.seed,
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
