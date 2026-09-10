"""
TTS 服务（文本转语音 / 声音克隆）
基于 CosyVoice3，支持音色保存和语音合成。
模型路径：backend/models/CosyVoice/
"""

import datetime as dt
import asyncio
import json
import os
import queue
import re
import subprocess
import sys
import uuid
import atexit
import threading
from pathlib import Path
from typing import Optional

# ── triton monkey-patch（Windows/macOS 不支持 triton，flash_attn 2.7.4 + transformers 4.51.3 需要）──
# 详细说明见 tts_infer_worker.py 同名段落
# Linux 原生支持 triton，无需 mock；macOS 与 Windows 同样需要
if sys.platform != "linux":
    import types

    def _make_triton_mock():
        import importlib.machinery
        m = types.ModuleType("triton")
        m.__version__ = "3.0.0"
        # 让 transformers 的 _is_package_available("triton") 返回 True
        m.__spec__ = importlib.machinery.ModuleSpec("triton", None)
        m.__spec__.origin = "mock"
        m.jit = lambda **kw: lambda fn: fn
        m.cdiv = lambda a, b: (a + b - 1) // b
        m.runtime = types.ModuleType("triton.runtime")
        m.runtime.driver = types.ModuleType("triton.runtime.driver")
        m.runtime.driver.active = types.ModuleType("triton.runtime.driver.active")
        tl = types.ModuleType("triton.language")
        for _name in (
            "program_id", "arange", "load", "store", "where",
            "cdiv", "constexpr", "float32", "int32", "int64",
            "dot", "exp", "cos", "sin", "sqrt", "abs", "min", "max",
            "log", "reshape", "trans", "contiguous", "view",
            "reduce", "softmax", "cross_entropy",
            "multiple_of", "next_power_of_2", "ceil_div",
            "libdevice", "math", "extra",
        ):
            setattr(tl, _name, lambda *a, **k: None)
        m.language = tl
        m.testing = types.ModuleType("triton.testing")
        return m

    _triton_mock = _make_triton_mock()
    sys.modules["triton"] = _triton_mock
    sys.modules["triton.language"] = _triton_mock.language
    sys.modules["triton.runtime"] = _triton_mock.runtime
    sys.modules["triton.runtime.driver"] = _triton_mock.runtime.driver
    sys.modules["triton.runtime.driver.active"] = _triton_mock.runtime.driver.active
    sys.modules["triton.testing"] = _triton_mock.testing

    _ops_triton_mod = types.ModuleType("flash_attn.ops.triton")
    _rotary_mod = types.ModuleType("flash_attn.ops.triton.rotary")
    exec(compile('''
def rotary_kernel(*args, **kwargs): pass
def apply_rotary(x, cos, sin, seqlen_offsets=0, cu_seqlens=None,
                 max_seqlen=None, interleaved=False, inplace=False,
                 conjugate=False):
    from flash_attn.layers.rotary import apply_rotary_emb_torch
    return apply_rotary_emb_torch(x, cos, sin, interleaved=interleaved)
''', "<triton_fallback>", "exec"), _rotary_mod.__dict__)
    sys.modules["flash_attn.ops.triton"] = _ops_triton_mod
    sys.modules["flash_attn.ops.triton.rotary"] = _rotary_mod

# ── 第1层：代理劫持修复（必须在所有其他 import 之前执行）────────────────────────
for _env in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_env, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

# ── FFmpeg 查找（跨平台，统一走 core.platform）────────────────────────────────
from core.platform import find_ffmpeg, register_ffmpeg_path

_ffmpeg_bin = find_ffmpeg()
if _ffmpeg_bin:
    print(f"[TTS] 使用 FFmpeg: {_ffmpeg_bin}")
    register_ffmpeg_path(_ffmpeg_bin)

# ── 路径配置（从 core.config 统一读取）──────────────────────────────────
from core.config import (
    COSYVOICE_MODEL_DIR,
    VOICES_DIR,
    TTS_OUTPUTS_DIR,
    _BACKEND_DIR,
    MAX_REF_SECONDS,
    MAX_OUTPUT_FILES,
    settings,
)

os.makedirs(VOICES_DIR, exist_ok=True)
os.makedirs(TTS_OUTPUTS_DIR, exist_ok=True)

# ── 数字转中文 ────────────────────────────────────────────────────────────────
from cn2an import an2cn

_YEAR_DIGIT_MAP = str.maketrans("0123456789", "零一二三四五六七八九")


def _convert_digits_to_chinese(text: str) -> str:
    """将阿拉伯数字转换为中文读音"""
    if not text:
        return text

    def replace_digit(match):
        try:
            return an2cn(match.group(0))
        except Exception:
            return match.group(0)

    # 年份逐字读
    result = re.sub(
        r"(?<!\d)(\d{4})年(?!\d)",
        lambda m: m.group(1).translate(_YEAR_DIGIT_MAP) + "年",
        text,
    )
    # 其他数字按数值读
    result = re.sub(r"\d+", replace_digit, result)
    return result


def _clean_text_for_tts(text: str) -> str:
    """清理文本，移除特殊字符"""
    if not text:
        return text
    cleaned = text.lstrip()
    while cleaned and cleaned[0] in '"\'""""':
        cleaned = cleaned[1:].lstrip()
    return cleaned.rstrip()


# 合成文本最短有效字符数：CosyVoice 声码器（HiFi-GAN 类）对极短输入
# 会报 "Kernel size can't be greater than actual input size"（底层卷积崩溃），
# 因此在进入模型前拦截，给出用户可读的错误信息。
MIN_GEN_CHARS = 4


def _effective_chars(text: str) -> int:
    """统计有效字符数（去除空白与标点，保留中文/英文/数字）"""
    if not text:
        return 0
    return len(re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE))


def validate_gen_text(gen_text: str) -> str:
    """
    校验并标准化合成文本：
    - 空文本 / 纯标点 / 有效字符过短时抛出 ValueError（用户可读错误）
    - 返回清理后的文本
    """
    cleaned = _clean_text_for_tts(_convert_digits_to_chinese(gen_text or ""))
    eff = _effective_chars(cleaned)
    if eff < MIN_GEN_CHARS:
        raise ValueError(
            f"合成文本过短：有效字符仅 {eff} 个，至少需要 {MIN_GEN_CHARS} 个字符"
            "（请勿只输入标点符号，建议至少输入一句话）"
        )
    return cleaned


# ── 全局模型实例（进程内复用）────────────────────────────────────────────────
_cosyvoice_model = None
_worker_lock = threading.Lock()
_worker_proc = None
# worker 是否已完成模型加载（预加载/合成成功后置 True；worker 重建后复位）
_worker_model_loaded = False
# 常驻 stdout reader 的路由槽位：请求经 task_lock 串行，同一时刻只有一个
# 请求在等待结果；请求开始时挂上队列与进度回调，结束时摘除（置 None）
_response_queue = None
_progress_cb = None


# ── 音色管理（基于数据库）────────────────────────────────────────────────


def _voice_audio_path(v: "Voice") -> str:
    """将数据库中存储的相对路径解析为绝对路径（不验证文件是否存在）"""
    ref_audio = v.ref_audio
    if ref_audio and os.path.isabs(ref_audio):
        return ref_audio

    filename = os.path.basename(ref_audio) if ref_audio else f"{v.name}.wav"

    canonical = os.path.join(VOICES_DIR, filename)
    if os.path.exists(canonical):
        return canonical

    legacy_dir = os.path.join(os.path.dirname(_BACKEND_DIR), "voices")
    legacy_path = os.path.join(legacy_dir, filename)
    if os.path.exists(legacy_path):
        return legacy_path

    return canonical


def _get_audio_duration(file_path: str) -> float:
    """用 ffprobe 获取音频时长，失败返回 0"""
    if not os.path.exists(file_path):
        return 0.0
    try:
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        probe_r = subprocess.run(probe_cmd, capture_output=True, text=True)
        if probe_r.returncode == 0:
            return float(probe_r.stdout.strip())
    except Exception:
        pass
    return 0.0


# 音频时长缓存 {绝对路径: (mtime, 时长)}：音色列表在页面加载、提交任务等
# 高频路径被查询，逐音色起 ffprobe 子进程开销大，按 mtime 失效直接复用结果
_audio_duration_cache: dict[str, tuple[float, float]] = {}


def _get_audio_duration_cached(file_path: str) -> float:
    """带缓存的音频时长查询（文件 mtime 变化时重新探测）"""
    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        return 0.0
    cached = _audio_duration_cache.get(file_path)
    if cached and cached[0] == mtime:
        return cached[1]
    duration = _get_audio_duration(file_path)
    _audio_duration_cache[file_path] = (mtime, duration)
    return duration


async def list_voices(db) -> list[dict]:
    """查询所有已保存的音色（含文件定位、特征文件与时长信息）"""
    from models.voice import Voice
    from sqlalchemy import select

    result = await db.execute(select(Voice).order_by(Voice.created_at.desc()))
    voices = result.scalars().all()
    ret = []
    for v in voices:
        ref_path = _voice_audio_path(v)

        # 构建 ref_pt 绝对路径：优先按 UUID 定位，兼容数据库历史路径。
        ref_pt_candidates = [os.path.join(VOICES_DIR, f"{v.uuid}.pt")]
        if v.ref_pt:
            ref_pt_candidates.append(
                v.ref_pt if os.path.isabs(v.ref_pt)
                else os.path.join(VOICES_DIR, os.path.basename(v.ref_pt))
            )
        ref_pt_path = next((p for p in ref_pt_candidates if os.path.isfile(p)), None)

        # ffprobe 是同步子进程调用，放入线程池避免阻塞事件循环（结果带缓存）
        duration = await asyncio.to_thread(_get_audio_duration_cached, ref_path)

        ret.append(
            {
                "id": v.id,
                "uuid": v.uuid,
                "name": v.name,
                "ref_audio": ref_path,
                "ref_text": v.ref_text,
                "ref_pt": ref_pt_path,
                "ref_pt_exists": bool(ref_pt_path),
                "ref_duration": duration,
            }
        )
    return ret


def _convert_to_wav(input_path: str, sample_rate: int = 24000) -> str:
    """将各种音频格式转换为指定采样率的 mono WAV（用于 soundfile 兼容读取）"""
    import shutil

    tmp_wav = input_path + "_conv.wav"
    ffmpeg_exe = _ffmpeg_bin or shutil.which("ffmpeg") or "ffmpeg"
    ffmpeg_dir = os.path.dirname(ffmpeg_exe) if ffmpeg_exe else ""

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i",
        input_path,
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        tmp_wav,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        stderr_msg = r.stderr[:500] if r.stderr else "(无 stderr 输出)"
        stdout_msg = r.stdout[:200] if r.stdout else ""
        raise RuntimeError(
            f"音频转换失败: {stderr_msg}\n"
            f"ffmpeg 路径: {ffmpeg_exe}\n"
            f"ffmpeg 搜索目录: {ffmpeg_dir}\n"
            f"输入文件: {input_path}\n"
            f"stdout: {stdout_msg}"
        )
    return tmp_wav


def _reader_loop(proc) -> None:
    """worker stdout 常驻读取线程：每个 worker 进程生命周期内只有一个。

    旧实现"每请求起 reader 线程 + join(2s) 后放弃"存在竞态：上一个请求的
    残留线程可能仍阻塞在 readline() 上并抢走下一请求的响应行，导致该请求
    一直等到超时。常驻线程 + 请求级路由槽位从根源上消除该问题。
    """
    global _response_queue
    while True:
        try:
            line = proc.stdout.readline()
        except Exception:
            line = ""
        if not line:
            break  # 进程退出 / 管道关闭
        line = line.strip()
        if not line.startswith("{"):
            continue  # 模型日志等非 JSON 输出
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "progress" in obj:
            cb = _progress_cb
            if cb is not None:
                try:
                    cb(obj["progress"])
                except Exception:
                    pass
            continue
        q = _response_queue
        if q is not None:
            try:
                q.put(obj, timeout=1.0)
            except queue.Full:
                pass


def _start_reader_thread(proc) -> None:
    threading.Thread(target=_reader_loop, args=(proc,), daemon=True).start()


def _worker_request(
    payload: dict,
    timeout_sec: int,
    label: str,
    raise_on_failure: bool = True,
    kill_on_timeout: bool = True,
    progress_cb=None,
) -> Optional[dict]:
    """
    向常驻 worker 发送一条 JSON 请求并等待结果（串行）。
    预加载 / 音色特征保存 / 语音合成三类请求共用此通道：
    获取 TTS 锁 → 挂载结果队列 → 写 payload → 轮询常驻 reader 路由的响应。

    Args:
        label: 任务名（用于日志与错误信息）
        raise_on_failure: False 时（预加载场景）失败只记日志并返回 None
        kill_on_timeout: True 时超时杀掉 worker 进程让下次请求重建
        progress_cb: 收到 {"progress": {...}} 进度行时回调（仅合成使用）

    Returns:
        worker 返回的 JSON dict；raise_on_failure=False 且失败时返回 None
    """
    import time

    global _worker_model_loaded, _response_queue, _progress_cb

    from services.task_lock import acquire_tts_lock, release_tts_lock

    # 锁外确保 worker 已就绪：模型加载（最长 180s）不占用 TTS 锁，
    # 避免首次加载期间前端误报"正在合成"、其他请求误报"任务进行中"。
    # worker 启动互斥由 _worker_lock 保证，两个并发请求不会重复启动进程。
    with _worker_lock:
        _ensure_worker()

    if not acquire_tts_lock(description=label):
        raise RuntimeError("有其他语音合成任务正在进行中，请稍后重试")

    try:
        with _worker_lock:
            proc = _ensure_worker()
            if not proc.stdin or not proc.stdout:
                raise RuntimeError("TTS worker 管道不可用")

            start_time = time.time()
            result_queue = queue.Queue(maxsize=1)
            # 挂上本请求的路由槽位后再写入（请求串行，槽位同一时刻只有一份）
            _response_queue = result_queue
            _progress_cb = progress_cb
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()

        try:
            while True:
                if time.time() - start_time > timeout_sec:
                    if kill_on_timeout:
                        # 超时大概率是 worker 内部卡死（模型死锁/音频异常），
                        # 直接杀掉进程让下次请求重建，避免卡死请求持续堆积
                        _kill_worker(proc)
                        raise RuntimeError(f"{label}超时（{timeout_sec}s），worker 已重启")
                    print(f"[TTS] ⚠️ {label}超时，将在首次合成时自动加载", flush=True)
                    return None
                try:
                    result = result_queue.get(timeout=0.5)
                except queue.Empty:
                    if proc.poll() is not None:
                        if raise_on_failure:
                            raise RuntimeError(f"{label}失败：TTS worker 进程已退出")
                        print(f"[TTS] ⚠️ worker 进程在{label}期间退出，将在首次合成时重建", flush=True)
                        return None
                    continue
                if "error" in result:
                    if raise_on_failure:
                        raise RuntimeError(f"{label}失败: {result['error']}")
                    print(f"[TTS] ⚠️ {label}失败: {result['error']}", flush=True)
                    return None
                _worker_model_loaded = True
                return result
        finally:
            # 摘除路由槽位：此后迟到的响应行由常驻 reader 直接丢弃
            _response_queue = None
            _progress_cb = None
    finally:
        release_tts_lock()


def _save_voice_feature_with_worker(
    ref_audio_path: str,
    ref_text: str,
    output_pt_path: str,
    timeout_sec: int = 120,
) -> dict:
    """通过 worker 进程保存音色特征到 .pt 文件"""
    return _worker_request(
        {
            "action": "save_voice_feature",
            "ref_audio_path": ref_audio_path,
            "ref_text": ref_text,
            "output_pt_path": output_pt_path,
        },
        timeout_sec=timeout_sec,
        label="音色特征保存",
    )


import uuid as uuid_module

def _delete_voice_files(file_uuid: str) -> None:
    """删除音色对应的 .wav / .pt 文件（不存在则忽略）"""
    for suffix in (".wav", ".pt"):
        p = os.path.join(VOICES_DIR, f"{file_uuid}{suffix}")
        try:
            if os.path.exists(p):
                os.remove(p)
                print(f"[音色] 已清理文件: {p}", flush=True)
        except Exception as e:
            print(f"[音色] 清理文件失败 {p}: {e}", file=sys.stderr)


def save_voice(
    ref_audio_path: str,
    ref_text: str,
    voice_name: str,
    voice_uuid: str = None,
) -> dict:
    """
    保存音色到文件系统（数据库保存由调用方处理）。

    Args:
        ref_audio_path: 参考音频文件路径（绝对路径）
        ref_text: 参考文字（必填，须与参考音频内容完全一致；Whisper 自动转录已移除）
        voice_name: 音色名称
        voice_uuid: 唯一标识符（可选，不提供则自动生成）

    Returns:
        {"name": "...", "uuid": "...", "ref_audio": "...", "ref_text": "...", "ref_pt": "..."}
    """
    if not voice_name or not voice_name.strip():
        raise ValueError("音色名称不能为空")
    if not ref_text or not ref_text.strip():
        raise ValueError("语音识别模型已移除，请务必手动提供参考文字（必须与参考音频中的说话内容完全一致）")
    ref_text_converted = _convert_digits_to_chinese(ref_text)
    ref_text_cleaned = _clean_text_for_tts(ref_text_converted)

    # 生成或使用提供的 UUID
    if voice_uuid:
        file_uuid = voice_uuid
    else:
        file_uuid = str(uuid_module.uuid4())
    
    vname = voice_name.strip()
    voice_wav_path = os.path.join(VOICES_DIR, f"{file_uuid}.wav")
    voice_pt_path = os.path.join(VOICES_DIR, f"{file_uuid}.pt")

    # 音频转换与保存（支持 mp3/flac/m4a 等格式）
    import soundfile as sf

    converted_path = None
    try:
        # 先探测采样率：仅在无法直接读取或采样率非 24 kHz 时才转换一次，
        # 避免 44.1k/48k 等 wav 输入触发两次 ffmpeg 转码 + 两次全量读取
        target_sr = 24000
        need_convert = True
        try:
            info = sf.info(ref_audio_path)
            need_convert = info.samplerate != target_sr
        except Exception:
            need_convert = True

        if need_convert:
            converted_path = _convert_to_wav(ref_audio_path, sample_rate=target_sr)
            orig_audio, orig_sr = sf.read(converted_path)
        else:
            orig_audio, orig_sr = sf.read(ref_audio_path)

        # 统一为单声道，避免不同声道数造成特征差异
        if getattr(orig_audio, "ndim", 1) > 1:
            orig_audio = orig_audio.mean(axis=1)

        # 截断音频到最大 15 秒以防超过 CosyVoice 30秒限制
        max_duration = MAX_REF_SECONDS
        max_samples = int(max_duration * orig_sr)
        if len(orig_audio) > max_samples:
            orig_audio = orig_audio[:max_samples]
            print(f"[音色] 参考音频过长，已自动截断至前 {max_duration} 秒")

        # 保存为系统音色文件
        sf.write(voice_wav_path, orig_audio, target_sr, subtype="PCM_16")
    finally:
        if converted_path and os.path.exists(converted_path):
            os.remove(converted_path)

    # 保存音色特征 .pt 文件
    # 注意：CosyVoice3 的 LLM 要求 prompt_text 含 <|endofprompt|>（token 151646），
    # 否则 LLM 断言失败导致合成崩溃。特征里保存的是 LLM prompt 格式文本，
    # 数据库里仍保存用户可读的原始参考文字。
    ref_text_llm = f"You are a helpful assistant.<|endofprompt|>{ref_text_cleaned}"
    print(f"[音色] 正在保存音色特征: {voice_pt_path}")
    try:
        _save_voice_feature_with_worker(voice_wav_path, ref_text_llm, voice_pt_path)
        if not os.path.isfile(voice_pt_path) or os.path.getsize(voice_pt_path) == 0:
            raise RuntimeError("音色特征文件未生成或为空")
        print(f"[音色] ✅ 音色特征保存成功")
    except Exception as e:
        # .pt 是已保存音色的必要条件，避免把半成品写入数据库。
        for path in (voice_wav_path, voice_pt_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        raise RuntimeError(f"音色特征提取失败，音色未保存: {e}") from e

    return {
        "name": vname,
        "uuid": file_uuid,
        "ref_audio": voice_wav_path,
        "ref_text": ref_text_cleaned.strip(),
        "ref_pt": voice_pt_path,
    }


async def save_voice_to_db(voice_data: dict, db) -> None:
    """将音色数据保存到数据库"""
    from models.voice import Voice
    from sqlalchemy import select

    name = voice_data["name"]
    voice_uuid = voice_data.get("uuid")
    ref_pt = voice_data.get("ref_pt")
    
    # 使用 UUID 作为文件名
    file_uuid = voice_uuid or str(uuid_module.uuid4())
    
    # 提取相对路径（如果存在）
    pt_path = None
    if ref_pt and os.path.isabs(ref_pt):
        pt_path = f"voices/{file_uuid}.pt"
    
    r = await db.execute(select(Voice).where(Voice.name == name))
    existing = r.scalar_one_or_none()
    if existing:
        # 同名音色被重新上传（UUID 变化）时，清理旧的 .wav/.pt 文件，避免孤儿文件累积
        if existing.uuid and existing.uuid != file_uuid:
            _delete_voice_files(existing.uuid)
        existing.uuid = file_uuid
        existing.ref_audio = f"voices/{file_uuid}.wav"
        existing.ref_text = voice_data["ref_text"]
        existing.ref_pt = pt_path
    else:
        voice = Voice(
            uuid=file_uuid,
            name=name,
            ref_audio=f"voices/{file_uuid}.wav",
            ref_text=voice_data["ref_text"],
            ref_pt=pt_path,
        )
        db.add(voice)
    await db.commit()


class VoiceNotFoundError(Exception):
    """音色不存在"""

    pass



async def delete_voice(voice_name: str, db):
    """
    从数据库删除音色，并同步清理对应的 .wav / .pt 文件。

    Raises:
        VoiceNotFoundError: 音色不存在
    """
    from models.voice import Voice
    from sqlalchemy import select

    r = await db.execute(select(Voice).where(Voice.name == voice_name))
    voice = r.scalar_one_or_none()
    if not voice:
        raise VoiceNotFoundError(f"音色「{voice_name}」不存在")

    file_uuid = voice.uuid
    await db.delete(voice)
    await db.commit()
    if file_uuid:
        _delete_voice_files(file_uuid)


# ── TTS 克隆推理 ─────────────────────────────────────────────────────────────


def generate_speech(
    ref_audio_path: str,
    ref_text: str,
    gen_text: str,
    speed: float = 1.0,
    remove_silence: bool = True,
    ref_pt_path: str = None,
    seed: int = 20260812,
    progress_cb=None,
) -> dict:
    """
    使用预保存的音色特征文件合成任意文本（唯一调用方为 TTS 异步任务，
    ref_pt_path 由任务提交方校验后传入；.pt 缺失时 worker 会回退用参考音频懒生成）。
    在独立子进程中加载模型和执行推理，避免模型加载崩溃影响主服务。

    Args:
        ref_audio_path: 参考音频路径（懒生成 .pt 的回退来源，可为空）
        ref_text: 参考音频的文字（需与音频内容匹配）
        gen_text: 要合成的文本
        speed: 语速（0.5-2.0，默认 1.0，CosyVoice3 支持）
        remove_silence: 是否去除首尾静音
        ref_pt_path: 预保存的音色特征文件路径（.pt），如果提供则优先使用
        progress_cb: 分片合成进度回调，形如 cb({"done": 2, "total": 5})，可为空

    Returns:
        {
            "output_path": "D:/.../xxx.wav",
            "duration_sec": 3.5,
            "sample_rate": 24000,
            "info": "...",
        }
    """
    # 合成文本校验：过短/纯标点会在模型内触发底层卷积崩溃，提前拦截
    validate_gen_text(gen_text)

    # 生成输出路径
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_wav = os.path.join(TTS_OUTPUTS_DIR, f"{ts}_{uuid.uuid4().hex[:8]}.wav")

    # 输出目录防膨胀：超过上限时清理最旧文件
    try:
        files = sorted(
            (os.path.join(TTS_OUTPUTS_DIR, f) for f in os.listdir(TTS_OUTPUTS_DIR) if f.endswith(".wav")),
            key=os.path.getmtime,
        )
        while len(files) > MAX_OUTPUT_FILES:
            old = files.pop(0)
            os.remove(old)
            print(f"[TTS] 已清理旧输出: {old}", flush=True)
    except Exception as e:
        print(f"[TTS] 输出目录清理跳过: {e}", flush=True)

    result = _run_tts_with_persistent_worker(
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
        gen_text=gen_text,
        speed=speed,
        remove_silence=remove_silence,
        out_wav=out_wav,
        ref_pt_path=ref_pt_path,
        seed=seed,
        progress_cb=progress_cb,
    )

    duration_sec = result.get("duration_sec", 0)
    sample_rate = result.get("sample_rate", 24000)

    ret = {
        "output_path": result["output_path"],
        "duration_sec": duration_sec,
        "sample_rate": sample_rate,
        "info": f"✅ 合成完成 | 时长={duration_sec:.2f}s | 采样率={sample_rate}Hz",
    }

    # 如果 worker 懒生成了 .pt 文件，传递路径给调用方（用于回写数据库）
    if result.get("generated_pt_path"):
        ret["generated_pt_path"] = result["generated_pt_path"]

    return ret


def _start_tts_worker():
    worker_script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tts_infer_worker.py"
    )
    if not os.path.exists(worker_script):
        raise RuntimeError(f"Worker script not found: {worker_script}")

    cmd = [sys.executable, worker_script, "--server"]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to start worker process: {e}")

    # Wait for server-ready with timeout (model loading takes 30s+)
    import time
    import threading
    start_time = time.time()
    ready_timeout = 180  # 3 minutes max for model loading

    result = [None]
    stderr_output = []

    def read_loop():
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                if "server-ready" in line:
                    result[0] = line
                    break
        except:
            pass

    def stderr_loop():
        try:
            while proc.poll() is None:
                line = proc.stderr.readline()
                if line:
                    stderr_output.append(line)
        except:
            pass

    # Start reader threads
    reader = threading.Thread(target=read_loop)
    reader.daemon = True
    reader.start()

    stderr_reader = threading.Thread(target=stderr_loop)
    stderr_reader.daemon = True
    stderr_reader.start()

    # Wait for result with timeout
    while result[0] is None:
        elapsed = time.time() - start_time
        if elapsed > ready_timeout:
            proc.kill()
            err_msg = "".join(stderr_output) if stderr_output else ""
            raise RuntimeError(f"TTS worker 启动超时（{ready_timeout}s），模型加载可能失败: {err_msg[:1000]}")

        if proc.poll() is not None:
            err_msg = "".join(stderr_output) if stderr_output else ""
            raise RuntimeError(f"TTS worker 启动失败: {err_msg or '进程意外退出'}")

        time.sleep(0.5)

    # server-ready 后由常驻 reader 线程接管 stdout（路由响应/进度到各请求）
    _start_reader_thread(proc)
    return proc


def _ensure_worker():
    global _worker_proc
    if _worker_proc is None or _worker_proc.poll() is not None:
        _worker_proc = _start_tts_worker()
    return _worker_proc


def _kill_worker(proc):
    """强制终止卡死的 worker 进程并清空全局引用（下次请求自动重启）"""
    global _worker_proc, _worker_model_loaded
    try:
        proc.kill()
    except Exception:
        pass
    if _worker_proc is proc:
        _worker_proc = None
    _worker_model_loaded = False
    print("[TTS] ⚠️ worker 进程已强制终止，将在下次请求时自动重启", flush=True)


def preload_worker(timeout_sec: int = 300):
    """
    预加载模型：启动 worker 并等待模型加载完成。
    由后端启动时在后台线程调用，不阻塞 API；失败时首次合成会自动加载兜底
    （不抛错、不杀进程），与合成/存音色请求经 task_lock 串行。
    """
    try:
        _worker_request(
            {"action": "preload"},
            timeout_sec=timeout_sec,
            label="模型预加载",
            raise_on_failure=False,
            kill_on_timeout=False,
        )
        if _worker_model_loaded:
            print("[TTS] ✅ 模型预加载完成，可直接开始合成", flush=True)
    except Exception as e:
        print(f"[TTS] ⚠️ 模型预加载异常（首次合成时自动加载）: {e}", flush=True)


def _run_tts_with_persistent_worker(
    ref_audio_path: str,
    ref_text: str,
    gen_text: str,
    speed: float,
    remove_silence: bool,
    out_wav: str,
    timeout_sec: int = 900,
    ref_pt_path: str = None,
    seed: int = 20260812,
    progress_cb=None,
) -> dict:
    """向 worker 发送语音合成请求并等待结果（进度行经 progress_cb 转发）"""
    payload = {
        "ref_audio_path": ref_audio_path,
        "ref_text": ref_text,
        "gen_text": gen_text,
        "speed": speed,
        "remove_silence": remove_silence,
        "output_path": out_wav,
        "seed": int(seed),
    }
    if ref_pt_path:
        payload["ref_pt_path"] = ref_pt_path

    result = _worker_request(
        payload,
        timeout_sec=timeout_sec,
        label="语音合成",
        progress_cb=progress_cb,
    )
    if result is None:
        raise RuntimeError("语音合成失败：worker 未返回结果")
    return result

@atexit.register
def _shutdown_worker():
    global _worker_proc
    if _worker_proc is None:
        return
    try:
        if _worker_proc.stdin:
            _worker_proc.stdin.write("__exit__\n")
            _worker_proc.stdin.flush()
    except Exception:
        pass
    try:
        _worker_proc.terminate()
    except Exception:
        pass
    _worker_proc = None
