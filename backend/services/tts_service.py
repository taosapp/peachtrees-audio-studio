"""
TTS 服务（文本转语音 / 声音克隆）
基于 CosyVoice3，支持音色保存和语音合成。
模型路径：backend/models/CosyVoice/
"""

import datetime as dt
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import atexit
import threading
from pathlib import Path
from typing import Optional

# ── triton monkey-patch（Windows 不支持 triton，flash_attn 2.7.4 + transformers 4.51.3 需要）──
# 详细说明见 tts_infer_worker.py 同名段落
if sys.platform == "win32":
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

# ── FFmpeg DLL 搜索路径 ────────────────────────────────────────────────────────


def _find_ffmpeg():
    """按优先级查找 ffmpeg.exe（返回完整可执行文件路径）"""
    import shutil
    import subprocess

    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe and os.path.isfile(ffmpeg_exe):
            try:
                result = subprocess.run(
                    [ffmpeg_exe, "-version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "ffmpeg version" in result.stdout:
                    print(f"[TTS] 使用 imageio-ffmpeg: {ffmpeg_exe}")
                    return ffmpeg_exe
            except Exception:
                pass
    except ImportError:
        pass

    winget_base = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"
    )
    if os.path.isdir(winget_base):
        for entry in os.listdir(winget_base):
            if entry.startswith("Gyan.FFmpeg"):
                for sub in os.listdir(os.path.join(winget_base, entry)):
                    bin_dir = os.path.join(winget_base, entry, sub, "bin")
                    ffmpeg_exe = os.path.join(bin_dir, "ffmpeg.exe")
                    if os.path.isfile(ffmpeg_exe):
                        try:
                            result = subprocess.run(
                                [ffmpeg_exe, "-version"],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )
                            if "ffmpeg version" in result.stdout:
                                print(f"[TTS] 使用 Gyan FFmpeg: {ffmpeg_exe}")
                                return ffmpeg_exe
                        except Exception:
                            pass

    ff = shutil.which("ffmpeg")
    if ff and "ImageMagick" not in ff and os.path.isfile(ff):
        try:
            result = subprocess.run(
                [ff, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "ffmpeg version" in result.stdout:
                print(f"[TTS] 使用系统 FFmpeg: {ff}")
                return ff
        except Exception:
            pass

    return None


_ffmpeg_bin = _find_ffmpeg()
_ffmpeg_dir = os.path.dirname(_ffmpeg_bin) if _ffmpeg_bin else None
if _ffmpeg_dir and hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(_ffmpeg_dir)
    except Exception:
        pass
if _ffmpeg_dir:
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

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


def _get_cosyvoice_model():
    """获取 CosyVoice 模型（实际加载在 worker 进程中）"""
    # 模型加载已移至 tts_infer_worker.py
    # 此函数保留用于兼容性，实际不使用
    return None


# ── 音色管理（基于数据库）────────────────────────────────────────────────


def _list_voice_files() -> list[str]:
    """列出 voices 目录下所有可用的音频文件"""
    voice_files = []
    for directory in [VOICES_DIR, os.path.join(os.path.dirname(_BACKEND_DIR), "voices")]:
        if os.path.isdir(directory):
            for f in os.listdir(directory):
                if f.endswith(".wav") or f.endswith(".mp3") or f.endswith(".flac"):
                    voice_files.append(f)
    return sorted(set(voice_files))


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


def validate_voice_audio_path(v: "Voice") -> str:
    """验证音色音频文件是否存在，不存在则抛出详细错误"""
    ref_audio = v.ref_audio
    filename = os.path.basename(ref_audio) if ref_audio else f"{v.name}.wav"

    canonical = os.path.join(VOICES_DIR, filename)
    if os.path.exists(canonical):
        return canonical

    legacy_dir = os.path.join(os.path.dirname(_BACKEND_DIR), "voices")
    legacy_path = os.path.join(legacy_dir, filename)
    if os.path.exists(legacy_path):
        return legacy_path

    available = _list_voice_files()
    raise FileNotFoundError(
        f"音色「{v.name}」的参考音频文件不存在！\n"
        f"尝试的路径: {canonical}\n"
        f"数据库中的路径: {ref_audio}\n"
        f"系统中的可用音色: {available if available else '（无）'}"
    )


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


async def list_voices(db=None) -> list[dict]:
    """列出所有已保存的音色（异步版本，接受 DB session）"""
    from models.voice import Voice
    from sqlalchemy import select

    if db is None:
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            return await _list_from_db(session)
    return await _list_from_db(db)


async def _list_from_db(session) -> list[dict]:
    """从数据库查询音色列表"""
    from models.voice import Voice
    from sqlalchemy import select

    result = await session.execute(select(Voice).order_by(Voice.created_at.desc()))
    voices = result.scalars().all()
    ret = []
    for v in voices:
        ref_path = _voice_audio_path(v)
        
        # 构建 ref_pt 绝对路径
        ref_pt_path = None
        if v.ref_pt:
            if os.path.isabs(v.ref_pt):
                ref_pt_path = v.ref_pt
            else:
                ref_pt_path = os.path.join(VOICES_DIR, os.path.basename(v.ref_pt))
        
        # ffprobe 是同步子进程调用，放入线程池避免阻塞事件循环
        duration = await asyncio.to_thread(_get_audio_duration, ref_path)
        
        ret.append(
            {
                "id": v.id,
                "uuid": v.uuid,
                "name": v.name,
                "ref_audio": ref_path,
                "ref_text": v.ref_text,
                "ref_pt": ref_pt_path,
                "ref_duration": duration,
                "is_system": v.is_system,
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


def _save_voice_feature_with_worker(
    ref_audio_path: str,
    ref_text: str,
    output_pt_path: str,
    timeout_sec: int = 120,
) -> dict:
    """
    通过 worker 进程保存音色特征到 .pt 文件
    
    Args:
        ref_audio_path: 参考音频路径
        ref_text: 参考文字
        output_pt_path: 输出的 .pt 文件路径
        timeout_sec: 超时时间
    
    Returns:
        {"output_pt_path": "...", "spk_id": "..."}
    """
    import time
    import threading
    import queue

    payload = {
        "action": "save_voice_feature",
        "ref_audio_path": ref_audio_path,
        "ref_text": ref_text,
        "output_pt_path": output_pt_path,
    }

    from services.task_lock import acquire_tts_lock, release_tts_lock
    
    if not acquire_tts_lock(description="音色特征保存"):
        raise RuntimeError("有其他语音合成任务正在进行中，请稍后重试")
    
    try:
        with _worker_lock:
            proc = _ensure_worker()
            if not proc.stdin or not proc.stdout:
                raise RuntimeError("TTS worker 管道不可用")

            start_time = time.time()
        result_queue = queue.Queue(maxsize=1)
        stop_event = threading.Event()

        def read_results():
            try:
                while not stop_event.is_set():
                    proc.stdout.flush()
                    line = proc.stdout.readline()
                    if not line:
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                        continue
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            # 在 reader 线程内完成 JSON 解析，解析失败不会影响主线程
                            result_queue.put(json.loads(line), timeout=1.0)
                        except (json.JSONDecodeError, queue.Full):
                            pass
            except Exception as e:
                print(f"[音色特征保存] Reader error: {e}", flush=True)

        reader = threading.Thread(target=read_results)
        reader.daemon = True
        reader.start()

        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()

            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout_sec:
                    # 超时大概率是 worker 内部卡死（模型死锁/音频异常），
                    # 直接杀掉进程让下次请求重建，避免卡死请求持续堆积
                    _kill_worker(proc)
                    raise RuntimeError(f"音色特征保存超时（{timeout_sec}s），worker 已重启")

                try:
                    result = result_queue.get(timeout=0.5)
                    if "error" in result:
                        raise RuntimeError(f"音色特征保存失败: {result['error']}")
                    return result
                except queue.Empty:
                    if proc.poll() is not None:
                        raise RuntimeError("TTS worker 进程已退出")
        finally:
            stop_event.set()
            reader.join(timeout=2.0)
    finally:
        release_tts_lock()


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
        # 先尝试直接读取（wav 格式）
        try:
            orig_audio, orig_sr = sf.read(ref_audio_path)
        except Exception:
            # 非 wav 格式，用 ffmpeg 转换
            converted_path = _convert_to_wav(ref_audio_path)
            orig_audio, orig_sr = sf.read(converted_path)

        # 截断音频到最大 15 秒以防超过 CosyVoice 30秒限制
        max_duration = MAX_REF_SECONDS
        max_samples = int(max_duration * orig_sr)
        if len(orig_audio) > max_samples:
            orig_audio = orig_audio[:max_samples]
            print(f"[音色] 参考音频过长，已自动截断至前 {max_duration} 秒")

        # 保存为系统音色文件
        sf.write(voice_wav_path, orig_audio, orig_sr)
    finally:
        if converted_path and os.path.exists(converted_path):
            os.remove(converted_path)

    # 参考文字处理
    if not ref_text or not ref_text.strip():
        raise ValueError("语音识别模型已移除，请务必手动提供参考文字（必须与参考音频中的说话内容完全一致）")
    else:
        ref_text_converted = _convert_digits_to_chinese(ref_text)
        ref_text_cleaned = _clean_text_for_tts(ref_text_converted)

    # 保存音色特征 .pt 文件
    # 注意：CosyVoice3 的 LLM 要求 prompt_text 含 <|endofprompt|>（token 151646），
    # 否则 LLM 断言失败导致合成崩溃。特征里保存的是 LLM prompt 格式文本，
    # 数据库里仍保存用户可读的原始参考文字。
    ref_text_llm = f"You are a helpful assistant.<|endofprompt|>{ref_text_cleaned}"
    print(f"[音色] 正在保存音色特征: {voice_pt_path}")
    try:
        _save_voice_feature_with_worker(voice_wav_path, ref_text_llm, voice_pt_path)
        print(f"[音色] ✅ 音色特征保存成功")
    except Exception as e:
        print(f"[音色] ⚠️ 音色特征保存失败: {e}", file=sys.stderr)
        voice_pt_path = None

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
            is_system=False,
        )
        db.add(voice)
    await db.commit()


class VoiceNotFoundError(Exception):
    """音色不存在"""

    pass



async def delete_voice(voice_name: str, db=None):
    """
    删除音色（异步版本，接受 DB session）。

    Raises:
        VoiceNotFoundError: 音色不存在
    """
    from models.voice import Voice
    from sqlalchemy import select

    if db is None:
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            return await _delete_from_db(voice_name, session)
    return await _delete_from_db(voice_name, db)


async def _delete_from_db(voice_name: str, session) -> None:
    """从数据库删除音色，并同步清理对应的 .wav / .pt 文件"""
    from models.voice import Voice
    from sqlalchemy import select

    r = await session.execute(select(Voice).where(Voice.name == voice_name))
    voice = r.scalar_one_or_none()
    if not voice:
        raise VoiceNotFoundError(f"音色「{voice_name}」不存在")

    # 系统音色保护（当前版本未预置系统音色，保留保护逻辑）
    if voice.is_system:
        raise ValueError(f"音色「{voice_name}」为系统音色，不可删除")

    file_uuid = voice.uuid
    await session.delete(voice)
    await session.commit()
    if file_uuid:
        _delete_voice_files(file_uuid)


# ── TTS 克隆推理 ─────────────────────────────────────────────────────────────


def _check_duration(audio_path: str) -> str:
    """检查参考音频时长，返回警告信息"""
    try:
        from pydub import AudioSegment

        seg = AudioSegment.from_file(audio_path)
        dur = len(seg) / 1000.0
        if dur < 3.0:
            return f"⚠️ 参考音频仅 {dur:.1f}s，短于推荐时长 3s，克隆质量可能不佳"
        if dur > 30.0:
            return f"⚠️ 参考音频长达 {dur:.1f}s，超过推荐时长 30s"
        return ""
    except Exception:
        return ""


def generate_speech(
    ref_audio_path: str,
    ref_text: str,
    gen_text: str,
    speed: float = 1.0,
    nfe_steps: int = 32,
    cfg_strength: float = 2.5,
    remove_silence: bool = True,
    ref_pt_path: str = None,
) -> dict:
    """
    使用参考音频或预保存的音色特征文件合成任意文本。
    在独立子进程中加载模型和执行推理，避免模型加载崩溃影响主服务。
    基于 CosyVoice3，零样本语音克隆，原生支持多语言。

    Args:
        ref_audio_path: 参考音频路径（如果提供了 ref_pt_path，则可为空）
        ref_text: 参考音频的文字（需与音频内容匹配）
        gen_text: 要合成的文本
        speed: 语速（0.5-2.0，默认 1.0，CosyVoice3 支持）
        nfe_steps: (已废弃，保留兼容) 原 F5-TTS 推理步数
        cfg_strength: (已废弃，保留兼容) 原 F5-TTS CFG 强度
        remove_silence: 是否去除首尾静音
        ref_pt_path: 预保存的音色特征文件路径（.pt），如果提供则优先使用

    Returns:
        {
            "output_path": "D:/.../xxx.wav",
            "duration_sec": 3.5,
            "sample_rate": 22050,
            "info": "...",
        }
    """
    import soundfile as sf

    # 合成文本校验：过短/纯标点会在模型内触发底层卷积崩溃，提前拦截
    validate_gen_text(gen_text)

    temp_truncated_audio = None
    if ref_audio_path and os.path.exists(ref_audio_path) and not ref_pt_path:
        try:
            info = sf.info(ref_audio_path)
            if info.duration > MAX_REF_SECONDS:
                print(f"[TTS] 参考音频时长为 {info.duration:.1f}s，超过{MAX_REF_SECONDS:.0f}秒限制。正在自动截断至前{MAX_REF_SECONDS:.0f}秒以避免 CosyVoice 报错...", flush=True)
                orig_audio, orig_sr = sf.read(ref_audio_path)
                max_samples = int(MAX_REF_SECONDS * orig_sr)
                truncated_audio = orig_audio[:max_samples]
                
                # 创建临时截断音频文件
                temp_truncated_audio = tempfile.mktemp(suffix=".wav", prefix="ref_truncated_")
                sf.write(temp_truncated_audio, truncated_audio, orig_sr)
                ref_audio_path = temp_truncated_audio
        except Exception as e:
            print(f"[TTS] 自动截断参考音频出错: {e}", flush=True)

    try:
        # 如果提供了 .pt 文件路径，跳过音频时长检查
        if ref_pt_path:
            duration_warn = ""
        else:
            duration_warn = _check_duration(ref_audio_path)

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
            nfe_steps=nfe_steps,
            cfg_strength=cfg_strength,
            remove_silence=remove_silence,
            out_wav=out_wav,
            ref_pt_path=ref_pt_path,
        )

        if "error" in result:
            raise RuntimeError(f"TTS 合成失败: {result['error']}")

        duration_sec = result.get("duration_sec", 0)
        sample_rate = result.get("sample_rate", 24000)

        info = f"✅ 合成完成 | 时长={duration_sec:.2f}s | 采样率={sample_rate}Hz"
        if duration_warn:
            info = duration_warn + "\n\n" + info

        ret = {
            "output_path": result["output_path"],
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
            "info": info,
        }

        # 如果 worker 懒生成了 .pt 文件，传递路径给调用方（用于回写数据库）
        if result.get("generated_pt_path"):
            ret["generated_pt_path"] = result["generated_pt_path"]

        return ret
    finally:
        if temp_truncated_audio and os.path.exists(temp_truncated_audio):
            try:
                os.remove(temp_truncated_audio)
            except Exception:
                pass


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

    return proc


def _ensure_worker():
    global _worker_proc
    if _worker_proc is None or _worker_proc.poll() is not None:
        _worker_proc = _start_tts_worker()
    return _worker_proc


def _kill_worker(proc):
    """强制终止卡死的 worker 进程并清空全局引用（下次请求自动重启）"""
    global _worker_proc
    try:
        proc.kill()
    except Exception:
        pass
    if _worker_proc is proc:
        _worker_proc = None
    print("[TTS] ⚠️ worker 进程已强制终止，将在下次请求时自动重启", flush=True)


def _run_tts_with_persistent_worker(
    ref_audio_path: str,
    ref_text: str,
    gen_text: str,
    speed: float,
    nfe_steps: int,
    cfg_strength: float,
    remove_silence: bool,
    out_wav: str,
    timeout_sec: int = 300,
    ref_pt_path: str = None,
) -> dict:
    import time
    import threading
    import queue

    payload = {
        "ref_audio_path": ref_audio_path,
        "ref_text": ref_text,
        "gen_text": gen_text,
        "speed": speed,
        "nfe_steps": int(nfe_steps),
        "cfg_strength": cfg_strength,
        "remove_silence": remove_silence,
        "output_path": out_wav,
    }
    
    # 如果提供了 .pt 音色特征文件路径，则添加到 payload
    if ref_pt_path:
        payload["ref_pt_path"] = ref_pt_path

    # 获取 TTS 锁
    from services.task_lock import acquire_tts_lock, release_tts_lock
    
    if not acquire_tts_lock(description="语音合成"):
        raise RuntimeError("有其他语音合成任务正在进行中，请稍后重试")
    
    try:
        with _worker_lock:
            proc = _ensure_worker()
            if not proc.stdin or not proc.stdout:
                raise RuntimeError("TTS worker 管道不可用")

            start_time = time.time()
        result_queue = queue.Queue(maxsize=1)
        stop_event = threading.Event()

        def read_results():
            try:
                while not stop_event.is_set():
                    proc.stdout.flush()
                    line = proc.stdout.readline()
                    if not line:
                        if proc.poll() is not None:
                            break
                        time.sleep(0.1)
                        continue
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            # 在 reader 线程内完成 JSON 解析，解析失败不会影响主线程
                            result_queue.put(json.loads(line), timeout=1.0)
                        except (json.JSONDecodeError, queue.Full):
                            pass
            except Exception as e:
                print(f"[TTS] Reader error: {e}", flush=True)

        # Start reader thread
        reader = threading.Thread(target=read_results)
        reader.daemon = True
        reader.start()

        try:
            # Send request
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()

            # Wait for result with timeout
            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout_sec:
                    # 超时大概率是 worker 内部卡死（模型死锁/音频异常），
                    # 直接杀掉进程让下次请求重建，避免卡死请求持续堆积
                    _kill_worker(proc)
                    raise RuntimeError(f"TTS 合成超时（{timeout_sec}s），worker 已重启，请尝试减少文本长度")

                try:
                    result = result_queue.get(timeout=0.5)
                    if "error" in result:
                        raise RuntimeError(f"TTS 合成失败: {result['error']}")
                    return result
                except queue.Empty:
                    if proc.poll() is not None:
                        raise RuntimeError("TTS worker 进程已退出")
        finally:
            # Signal reader to stop
            stop_event.set()
            # Give reader thread a moment to clean up
            reader.join(timeout=2.0)
    finally:
        # 释放 TTS 锁
        release_tts_lock()


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
