"""
TTS 推理子进程 Worker (CosyVoice3)
在独立进程中加载模型和执行合成，避免模型加载崩溃影响主服务。
只使用本地模型文件，禁止任何 HuggingFace 远程下载。
"""

import json
import os
import sys
import warnings
import types

# ── PyTorch 2.6 兼容：禁用 weights_only 默认行为 ──
# PyTorch 2.6 将 torch.load 默认改为 weights_only=True，
# 导致 transformers/lightning 内部反序列化 Qwen2ForCausalLM 等类时报错
os.environ.setdefault("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0")

import torch

# 推理线程数可配置（CPU 推理时提高并行度；GPU 场景影响很小）
# 默认 4，可通过 .env 的 TTS_NUM_THREADS 调整；设为 0 表示使用 torch 默认值
from core.config import settings as _settings
_tts_threads = int(_settings.tts_num_threads or 0)
if _tts_threads > 0:
    torch.set_num_threads(_tts_threads)

# ── triton monkey-patch（Windows 不支持 triton）────────────────────────────
if sys.platform == "win32":
    def _make_triton_mock():
        import importlib.machinery
        m = types.ModuleType("triton")
        m.__version__ = "3.0.0"
        m.__spec__ = importlib.machinery.ModuleSpec("triton", None)
        m.__spec__.origin = "mock"
        m.jit = lambda **kw: lambda fn: fn
        m.cdiv = lambda a, b: (a + b - 1) // b
        m.runtime = types.ModuleType("triton.runtime")
        tl = types.ModuleType("triton.language")
        for _name in ("program_id", "arange", "load", "store", "where", "cdiv", 
                      "constexpr", "float32", "int32", "int64", "dot", "exp", 
                      "cos", "sin", "sqrt", "abs", "min", "max", "log", "reshape", 
                      "trans", "contiguous", "view", "reduce", "softmax"):
            setattr(tl, _name, lambda *a, **k: None)
        m.language = tl
        m.testing = types.ModuleType("triton.testing")
        return m

    _triton_mock = _make_triton_mock()
    sys.modules["triton"] = _triton_mock
    sys.modules["triton.language"] = _triton_mock.language
    sys.modules["triton.runtime"] = _triton_mock.runtime
    sys.modules["triton.testing"] = _triton_mock.testing
    print("[Worker] Windows triton mock installed", flush=True)


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
                    print(f"[Worker] 使用 imageio-ffmpeg: {ffmpeg_exe}", flush=True)
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
                                print(f"[Worker] 使用 Gyan FFmpeg: {ffmpeg_exe}", flush=True)
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
                print(f"[Worker] 使用系统 FFmpeg: {ff}", flush=True)
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
    print(f"[Worker] FFmpeg DLL path registered: {_ffmpeg_dir}", flush=True)

# 修复 Windows 控制台编码（避免 emoji/中文在 GBK 下报错）
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

# 添加 backend 目录到 path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BACKEND_DIR)

# ── 路径配置（从 config.py 统一读取）──────────────────────────────────────
from core.config import COSYVOICE_SRC_DIR, MATCHA_SRC_DIR, COSYVOICE_MODEL_DIR

# 添加 CosyVoice 源码路径
if os.path.isdir(COSYVOICE_SRC_DIR):
    sys.path.insert(0, COSYVOICE_SRC_DIR)
    print(f"[Worker] CosyVoice source path added: {COSYVOICE_SRC_DIR}", flush=True)

# 添加 matcha-tts 源码路径
if os.path.isdir(MATCHA_SRC_DIR):
    sys.path.insert(0, MATCHA_SRC_DIR)
    print(f"[Worker] Matcha-TTS source path added: {MATCHA_SRC_DIR}", flush=True)

_REQUIRED_MODELS = {
    "CosyVoice 模型目录": os.path.join(COSYVOICE_MODEL_DIR),
}

# CosyVoice 模型实例（全局缓存）
_cosyvoice_model = None


def _load_cosyvoice_model():
    """加载 CosyVoice3 模型"""
    global _cosyvoice_model
    
    if _cosyvoice_model is not None:
        return _cosyvoice_model
    
    print(f"[Worker] 加载 CosyVoice3 模型: {COSYVOICE_MODEL_DIR}", flush=True)
    
    try:
        # CosyVoice 源码路径已在模块顶部通过 config 加入 sys.path
        from cosyvoice.cli.cosyvoice import AutoModel
        
        # 检查设备
        device = "cuda" if torch.cuda.is_available() else "cpu"
        precision = torch.bfloat16 if device == "cuda" else torch.float32
        print(f"[Worker] 使用设备: {device}, 精度: {precision}", flush=True)
        
        # 加载 CosyVoice3 模型
        _cosyvoice_model = AutoModel(
            model_dir=COSYVOICE_MODEL_DIR,
            fp16=precision == torch.bfloat16
        )
        
        print("[Worker] ✅ CosyVoice3 模型加载完成", flush=True)
        return _cosyvoice_model
        
    except Exception as e:
        import traceback
        print(f"[Worker] ❌ CosyVoice3 模型加载失败: {e}", flush=True)
        traceback.print_exc()
        raise


def check_models():
    """检查模型目录是否存在"""
    if not os.path.isdir(COSYVOICE_MODEL_DIR):
        msg = (
            "\n" + "=" * 60 + "\n"
            "❌ CosyVoice 模型目录不存在！\n\n"
            "📥 请手动下载模型：\n"
            "   1. 从 HuggingFace 下载 FunAudioLLM/Fun-CosyVoice3-0.5B\n"
            "      https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B\n"
            "   2. 或从 ModelScope 下载\n"
            "      https://modelscope.cn/models/FunAudioLLM/Fun-CosyVoice3-0.5B\n\n"
            f"💡 模型应放置于: {COSYVOICE_MODEL_DIR}\n" + "=" * 60
        )
        print(msg, file=sys.stderr)
        print(json.dumps({"error": "模型目录不存在，请查看 stderr 获取下载指引"}))
        sys.exit(1)
    
    # 检查必要的模型文件
    config_path = os.path.join(COSYVOICE_MODEL_DIR, "cosyvoice3.yaml")
    if not os.path.exists(config_path):
        print(f"[Worker] ⚠️ cosyvoice3.yaml 不存在，可能需要下载完整模型", flush=True)
    
    print(f"[Worker] ✅ CosyVoice 模型目录已就绪 ({COSYVOICE_MODEL_DIR})", flush=True)


def _inference_zero_shot_no_leak(
    cosyvoice,
    tts_text: str,
    prompt_text: str,
    prompt_wav: str,
    zero_shot_spk_id: str = '',
    stream: bool = False,
    speed: float = 1.0,
    text_frontend: bool = True,
):
    """
    自定义零样本推理：彻底避免 prompt_text 泄漏到合成语音中。

    采用 cross_lingual 模式策略：在 LLM 层删除 prompt_text 和
    llm_prompt_speech_token，只保留 flow 层需要的 flow_prompt_speech_token、
    prompt_speech_feat 和 embedding 来指导音色。这样 0.5B 模型就没有
    文本级的 prompt 可以"朗读"了，从根源上消除泄漏。

    同时使用更大的分片阈值（300 字而非原版 80 字）以减少分片数量。
    """
    from cosyvoice.utils.frontend_utils import (
        split_paragraph,
        is_only_punctuation,
        contains_chinese,
    )
    from functools import partial

    # 归一化 tts_text（不分割，得到完整的归一化文本）
    normalized = cosyvoice.frontend.text_normalize(
        tts_text, split=False, text_frontend=text_frontend
    )

    if not normalized:
        return

    # 对于超长文本，使用更大的分片阈值（300 而非 80）以减少分片数量
    if contains_chinese(normalized) and len(normalized) > 300:
        texts = list(split_paragraph(
            normalized,
            partial(
                cosyvoice.frontend.tokenizer.encode,
                allowed_special=cosyvoice.frontend.allowed_special,
            ),
            "zh",
            token_max_n=300,
            token_min_n=200,
            merge_len=50,
            comma_split=False,
        ))
        texts = [i for i in texts if not is_only_punctuation(i)]
    else:
        texts = [normalized]

    import torch as _torch

    # CosyVoice3LM 要求 token 序列里必须有 <|endofprompt|>（id=151646）。
    # 由于我们会删除 LLM 侧的 prompt_text，需要确保 gen_text 的 token 里有它。
    _eop_id = 151646
    _eop_prefix_token = None

    for i in texts:
        # 先用 frontend_zero_shot 获取完整 model_input（包含 prompt 字段）
        # 当 zero_shot_spk_id 为空时，需要 prompt_text 和 prompt_wav
        # 用于提取 embedding / speech_feat 等音色特征
        model_input = cosyvoice.frontend.frontend_zero_shot(
            i, prompt_text, prompt_wav,
            cosyvoice.sample_rate, zero_shot_spk_id,
        )

        # —— cross_lingual 风格：删除 LLM 层导致 prompt 泄漏的字段 ——
        for _key in (
            'prompt_text', 'prompt_text_len',
            'llm_prompt_speech_token', 'llm_prompt_speech_token_len',
        ):
            if _key in model_input:
                del model_input[_key]

        # —— 确保 gen_text token 序列包含 <|endofprompt|>（CosyVoice3LM 断言需要）——
        _text_tensor = model_input.get('text')
        if _text_tensor is not None:
            _text_tokens_flat = _text_tensor.flatten().tolist()
            if _eop_id not in _text_tokens_flat:
                if _eop_prefix_token is None:
                    # 延迟构造只含 <|endofprompt|> 的 token tensor（与原始 dtype/device 一致）
                    _eop_prefix_token = _torch.tensor(
                        [[_eop_id]], dtype=_text_tensor.dtype, device=_text_tensor.device
                    )
                model_input['text'] = _torch.cat(
                    [_eop_prefix_token, _text_tensor], dim=1
                )
                model_input['text_len'] = _torch.tensor(
                    [model_input['text'].shape[1]],
                    dtype=_text_tensor.dtype,
                    device=_text_tensor.device,
                )

        for model_output in cosyvoice.model.tts(
            **model_input, stream=stream, speed=speed
        ):
            yield model_output


def run_inference(
    ref_audio_path: str,
    ref_text: str,
    gen_text: str,
    speed: float,
    nfe_steps: int,
    cfg_strength: float,
    remove_silence: bool,
    output_path: str,
    ref_pt_path: str = None,
):
    """
    语音合成推理
    
    Args:
        ref_audio_path: 参考音频路径（可为空，如果使用 ref_pt_path）
        ref_text: 参考文字
        gen_text: 要合成的文本
        speed: 语速
        nfe_steps: 推理步数（已废弃）
        cfg_strength: CFG 强度（已废弃）
        remove_silence: 是否去除静音
        output_path: 输出路径
        ref_pt_path: 音色特征文件路径（.pt），如果提供则优先使用
    """
    try:
        # 延迟导入
        from services.tts_service import (
            _clean_text_for_tts,
            _convert_digits_to_chinese,
            validate_gen_text,
        )

        # 加载 CosyVoice3 模型
        print("[Worker] 加载 CosyVoice3 模型...", flush=True)
        cosyvoice = _load_cosyvoice_model()
        print("[Worker] ✅ CosyVoice3 加载完成", flush=True)

        # 处理文本（validate_gen_text 内部完成数字转中文 + 清理 + 短文本校验）
        gen_text_cleaned = validate_gen_text(gen_text)
        
        print(f"[Worker] gen_text={gen_text_cleaned!r}", flush=True)

        # 判断使用哪种方式合成
        use_pt_feature = ref_pt_path and os.path.exists(ref_pt_path)
        generated_pt_path = None  # 懒生成的 .pt 文件路径，用于回写数据库

        # ── 懒生成：如果 .pt 不存在但音频文件存在，自动提取音色特征 ──
        if not use_pt_feature and ref_audio_path and os.path.exists(ref_audio_path):
            derived_pt = os.path.splitext(ref_audio_path)[0] + ".pt"
            if os.path.exists(derived_pt):
                # .pt 文件已存在但没有通过 ref_pt_path 传入，直接使用
                ref_pt_path = derived_pt
                use_pt_feature = True
                print(f"[Worker] 发现已有音色特征文件: {derived_pt}", flush=True)
            else:
                # 懒生成 .pt
                try:
                    print(f"[Worker] 🔄 懒生成音色特征: {derived_pt} ...", flush=True)
                    cosyvoice_model = _load_cosyvoice_model()
                    spk_id = os.path.splitext(os.path.basename(ref_audio_path))[0]
                    # CosyVoice3 要求 prompt_text 含 <|endofprompt|>，否则 LLM 断言失败
                    llm_ref_text = (
                        ref_text
                        if "<|endofprompt|>" in ref_text
                        else f"You are a helpful assistant.<|endofprompt|>{ref_text}"
                    )
                    cosyvoice_model.add_zero_shot_spk(llm_ref_text, ref_audio_path, spk_id)
                    spk_info = cosyvoice_model.frontend.spk2info.get(spk_id)
                    if spk_info is not None:
                        # 显式搬回 CPU 再保存，避免 torch.save 隐式同步 + GPU→CPU 搬运
                        spk_info_cpu = {k: v.cpu() if hasattr(v, 'cpu') else v for k, v in spk_info.items()}
                        torch.save(spk_info_cpu, derived_pt)
                        generated_pt_path = derived_pt
                        ref_pt_path = derived_pt
                        use_pt_feature = True
                        print(f"[Worker] ✅ 懒生成音色特征完成: {derived_pt}", flush=True)
                except Exception as _e:
                    print(f"[Worker] ⚠️ 懒生成 .pt 失败（将回退到音频推理）: {_e}", flush=True)

        if use_pt_feature:
            # 使用 .pt 音色特征文件合成
            print(f"[Worker] 使用音色特征文件: {ref_pt_path}", flush=True)
            
            # 加载音色特征并注册到模型
            spk_id = os.path.splitext(os.path.basename(ref_pt_path))[0]
            spk_info = torch.load(ref_pt_path, map_location="cpu")
            
            # 兼容旧音色特征：CosyVoice3 的 LLM 要求 prompt_text 含 <|endofprompt|>
            # （token id 151646），旧特征文件缺失该标记会导致 LLM 直接断言失败、
            # 生成空 token，最终在声码器卷积层报
            # "Kernel size can't be greater than actual input size"。
            ptt = spk_info.get("prompt_text")
            if torch.is_tensor(ptt) and 151646 not in ptt.flatten().tolist():
                prefix_tokens = cosyvoice.frontend.tokenizer.encode(
                    "You are a helpful assistant.<|endofprompt|>", allowed_special="all"
                )
                if 151646 in prefix_tokens:
                    prefix_t = torch.tensor([prefix_tokens], dtype=torch.int32)
                    spk_info["prompt_text"] = torch.cat([prefix_t, ptt], dim=1)
                    spk_info["prompt_text_len"] = torch.tensor(
                        [spk_info["prompt_text"].shape[1]], dtype=torch.int32
                    )
                    print("[Worker] 已修复旧音色特征的 prompt_text（补充 <|endofprompt|>）", flush=True)
                    # 写回磁盘，下次直接使用修复后的特征
                    try:
                        spk_cpu = {k: v.cpu() if hasattr(v, 'cpu') else v for k, v in spk_info.items()}
                        torch.save(spk_cpu, ref_pt_path)
                        print("[Worker] 修复后的特征已写回磁盘", flush=True)
                    except Exception as _we:
                        print(f"[Worker] 特征写回失败（不影响本次合成）: {_we}", flush=True)
                else:
                    print("[Worker] ⚠️ tokenizer 无法生成 <|endofprompt|>，继续尝试合成", flush=True)
            
            # 将音色特征添加到模型
            cosyvoice.frontend.spk2info[spk_id] = spk_info
            
            # 使用 zero_shot_spk_id 进行合成（不需要 ref_audio 和 ref_text）
            # 注意：使用 _inference_zero_shot_no_leak 替代 inference_zero_shot，
            # 避免文本分割导致 prompt_text 语音多次泄漏
            audio_chunks = []
            for chunk in _inference_zero_shot_no_leak(
                cosyvoice,
                gen_text_cleaned,
                "",  # instruct_text 为空
                "",  # ref_audio 为空
                zero_shot_spk_id=spk_id,
                stream=False,
                speed=speed,
                text_frontend=True,
            ):
                audio_chunks.append(chunk['tts_speech'])
        else:
            # 使用传统方式：参考音频 + 参考文字
            # 检查参考音频
            if not ref_audio_path or not os.path.exists(ref_audio_path):
                raise FileNotFoundError(f"参考音频文件不存在: {ref_audio_path}")

            # 参考文字必须提供（Whisper 自动转录已移除，占位文字会导致克隆音色失真）
            if not ref_text or not ref_text.strip():
                raise ValueError(
                    "参考文字为空：请提供与参考音频内容完全一致的参考文字（参考文字必须手动填写）"
                )

            ref_text_cleaned = _clean_text_for_tts(_convert_digits_to_chinese(ref_text))
            
            print(f"[Worker] ref_text={ref_text_cleaned!r}", flush=True)
            print(f"[Worker] ref_audio={ref_audio_path}", flush=True)
            print("[Worker] 开始推理合成...", flush=True)

            # CosyVoice3 推理（零样本语音克隆）
            # 构建 instruct 文本格式
            instruct_text = f"You are a helpful assistant.<|endofprompt|>{ref_text_cleaned}"

            # 注意：使用 _inference_zero_shot_no_leak 替代 inference_zero_shot，
            # 避免文本分割导致 prompt_text 语音多次泄漏
            audio_chunks = []
            for chunk in _inference_zero_shot_no_leak(
                cosyvoice,
                gen_text_cleaned,
                instruct_text,
                ref_audio_path,
                stream=False,
                speed=speed,
                text_frontend=True,
            ):
                audio_chunks.append(chunk['tts_speech'])

        # 合并音频块
        import numpy as np
        import soundfile as sf
        
        # 合并所有音频张量
        audio_out = torch.cat([chunk.squeeze(0) for chunk in audio_chunks], dim=-1).cpu().numpy()
        sample_rate = cosyvoice.sample_rate

        # 去除静音
        if remove_silence:
            try:
                import tempfile
                from pydub import AudioSegment
                from pydub import silence as pydub_silence
                from io import BytesIO

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as _tmp:
                    sf.write(_tmp.name, audio_out, sample_rate)
                    seg = AudioSegment.from_file(_tmp.name)
                    nonsilent_ranges = pydub_silence.detect_nonsilent(
                        seg, min_silence_len=300, silence_thresh=-40
                    )
                os.unlink(_tmp.name)

                if nonsilent_ranges:
                    start_ms, end_ms = nonsilent_ranges[0][0], nonsilent_ranges[-1][1]
                    seg_trimmed = seg[start_ms:end_ms]
                    buf = BytesIO()
                    seg_trimmed.export(buf, format="wav")
                    buf.seek(0)
                    audio_out, sample_rate = sf.read(buf)
                    sample_rate = int(sample_rate)
            except Exception as e:
                print(f"[去静音] 警告: {e}", file=sys.stderr)

        # 保存输出
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        sf.write(output_path, audio_out, sample_rate)

        duration_sec = len(audio_out) / sample_rate
        print(
            f"[Worker] ✅ 合成完成: {output_path} (时长={duration_sec:.2f}s)",
            flush=True,
        )
        print(
            f"[Worker] DEBUG: gen_text={gen_text!r}, ref_text={ref_text!r}",
            flush=True,
        )

        # 输出结果 JSON（主进程通过 stdout 读取）
        result = {
            "output_path": output_path,
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
        }
        # 如果懒生成了 .pt 文件，返回路径以便主进程更新数据库
        if generated_pt_path:
            result["generated_pt_path"] = generated_pt_path
        return result

    except Exception as e:
        raise RuntimeError(f"{type(e).__name__}: {e}") from e


def save_voice_feature(
    ref_audio_path: str,
    ref_text: str,
    output_pt_path: str,
):
    """
    保存音色特征到 .pt 文件
    
    Args:
        ref_audio_path: 参考音频路径
        ref_text: 参考文字
        output_pt_path: 输出的 .pt 文件路径
    """
    # 加载 CosyVoice3 模型
    cosyvoice = _load_cosyvoice_model()
    
    # 使用 CosyVoice 的 add_zero_shot_spk 方法提取音色特征
    spk_id = os.path.splitext(os.path.basename(output_pt_path))[0]
    cosyvoice.add_zero_shot_spk(ref_text, ref_audio_path, spk_id)
    
    # 获取该音色的特征
    spk_info = cosyvoice.frontend.spk2info.get(spk_id)
    if spk_info is None:
        raise RuntimeError(f"音色特征提取失败: {spk_id}")
    
    # 保存为单独的 .pt 文件（显式搬回 CPU 避免隐式同步）
    os.makedirs(os.path.dirname(output_pt_path), exist_ok=True)
    spk_info_cpu = {k: v.cpu() if hasattr(v, 'cpu') else v for k, v in spk_info.items()}
    torch.save(spk_info_cpu, output_pt_path)
    print(f"[Worker] 音色特征已保存: {output_pt_path}", flush=True)
    
    return {
        "output_pt_path": output_pt_path,
        "spk_id": spk_id,
    }


def run_server_mode():
    """常驻模式：一次加载模型，循环处理 stdin JSON 请求。"""
    check_models()
    print("[Worker] server-ready", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.lower() == "__exit__":
            print(json.dumps({"ok": True, "message": "worker exiting"}), flush=True)
            break
        try:
            req = json.loads(line)
            
            # 检查是否是保存音色特征的请求
            if req.get("action") == "save_voice_feature":
                result = save_voice_feature(
                    ref_audio_path=req["ref_audio_path"],
                    ref_text=req.get("ref_text", ""),
                    output_pt_path=req["output_pt_path"],
                )
                print(json.dumps(result), flush=True)
                continue
            
            # 普通语音合成请求
            result = run_inference(
                ref_audio_path=req.get("ref_audio_path", ""),
                ref_text=req.get("ref_text", ""),
                gen_text=req["gen_text"],
                speed=float(req.get("speed", 1.0)),
                nfe_steps=int(req.get("nfe_steps", 32)),
                cfg_strength=float(req.get("cfg_strength", 2.5)),
                remove_silence=bool(req.get("remove_silence", True)),
                output_path=req["output_path"],
                ref_pt_path=req.get("ref_pt_path"),
            )
            print(json.dumps(result), flush=True)
        except Exception as e:
            print(json.dumps({"error": f"{type(e).__name__}: {e}"}), flush=True)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--server":
        run_server_mode()
        return

    if len(sys.argv) < 9:
        print(
            json.dumps(
                {
                    "error": "参数不足: ref_audio ref_text gen_text speed nfe_steps cfg_strength remove_silence output_path"
                }
            )
        )
        sys.exit(1)

    # 先检查模型文件
    check_models()
    ref_audio_path = sys.argv[1]
    ref_text = sys.argv[2]
    gen_text = sys.argv[3]
    speed = float(sys.argv[4])
    nfe_steps = int(sys.argv[5])
    cfg_strength = float(sys.argv[6])
    remove_silence = sys.argv[7].lower() == "true"
    output_path = sys.argv[8]
    try:
        result = run_inference(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            gen_text=gen_text,
            speed=speed,
            nfe_steps=nfe_steps,
            cfg_strength=cfg_strength,
            remove_silence=remove_silence,
            output_path=output_path,
        )
        print(json.dumps(result))
    except Exception as e:
        import traceback

        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
