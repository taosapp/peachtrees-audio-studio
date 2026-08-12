"""
外挂拼音纠正词典（CSV 格式）
──────────────────────────────────────────────
Windows 环境无 ttsfrd 文本前端，CosyVoice3 对多音字自行决策会读错
（如“著名”读成 zhuó míng）。通过外挂 CSV 词典 + [zhu4] 数字调号注音纠正。

CSV 格式（UTF-8 / UTF-8 BOM / GBK 均可，支持 # 注释行）：
    word,pronunciation
    著名,[zhu4]名
    重庆,重[chong2]庆

注意：注音必须【替换】汉字，不能与汉字并存（如 著[zhu4]名 会让模型把汉字和
注音各读一遍，读成“著+zhu”）；读音稳定的字可保留汉字（[zhu4]名），
也可全部拼音化（[zhu4][ming2]）。

路径：默认 backend/data/pinyin_fixes.csv，
      可用环境变量 PINYIN_FIXES_CSV 覆盖。
worker 每次合成前检查文件修改时间，改动自动热加载，无需重启。
"""
import os
import re

DEFAULT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "pinyin_fixes.csv"
)

# ── [zhu4] 数字调号 → CosyVoice 拼音 token（[zh][ù]）转换 ──────────────────
_PINYIN_INITIALS = ["zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w"]
_PINYIN_FINALS = ["a", "o", "e", "i", "u", "v", "ai", "ei", "ui", "ao", "ou", "iu", "ie", "ue", "ve", "er",
                  "an", "en", "in", "un", "vn", "ang", "eng", "ing", "ong",
                  "ia", "ian", "iang", "iao", "iong", "ua", "uai", "uan", "uang", "uo", "van"]
_PINYIN_TONE_MARKS = {
    "a": ["a", "ā", "á", "ǎ", "à"],
    "o": ["o", "ō", "ó", "ǒ", "ò"],
    "e": ["e", "ē", "é", "ě", "è"],
    "i": ["i", "ī", "í", "ǐ", "ì"],
    "u": ["u", "ū", "ú", "ǔ", "ù"],
    "v": ["v", "ǖ", "ǘ", "ǚ", "ǜ"],
}

_PINYIN_PATTERN = re.compile(r"\[([a-zA-Züv]+[0-5]?)\]")


def _pinyin_tone_final(final: str, tone: int) -> str:
    """给韵母标声调（汉语拼音标调规则：a>o>e>iu 标后>其他）"""
    if tone <= 0 or tone > 4:
        return final
    if "a" in final:
        idx = final.index("a")
    elif "o" in final:
        idx = final.index("o")
    elif "e" in final:
        idx = final.index("e")
    elif "iu" in final:
        idx = final.index("u")
    elif "ui" in final:
        idx = final.index("i")
    else:
        idx = -1
        for ch in "iuv":
            if ch in final:
                idx = final.index(ch)
                break
        if idx < 0:
            return final
    letter = final[idx]
    return final[:idx] + _PINYIN_TONE_MARKS[letter][tone] + final[idx + 1:]


def _split_pinyin_syllable(syl: str):
    """拆音节为 (声母, 韵母)，如 zhu -> (zh, u)"""
    for init in _PINYIN_INITIALS:
        if syl.startswith(init) and len(syl) > len(init):
            return init, syl[len(init):]
    return "", syl


def convert_numeric_pinyin(syl: str):
    """zhu4 -> [zh][ù]；返回 None 表示无法识别"""
    syl = syl.lower()
    tone = 0
    body = syl
    if syl and syl[-1] in "012345":
        tone = int(syl[-1])
        body = syl[:-1]
    if not body:
        return None
    init, final = _split_pinyin_syllable(body)
    if not final or final not in _PINYIN_FINALS:
        return None
    final = _pinyin_tone_final(final, tone)
    return (f"[{init}]" if init else "") + f"[{final}]"


def convert_text_pinyin_annotations(text: str, valid_tokens: set) -> str:
    """把文本中的 [zhu4] 转换为 [zh][ù]；生成的 token 不在词表时保留原文"""
    def _repl(m):
        converted = convert_numeric_pinyin(m.group(1))
        if converted is None:
            return m.group(0)
        toks = re.findall(r"\[([^\]]+)\]", converted)
        if any(f"[{t}]" not in valid_tokens for t in toks):
            return m.group(0)
        return converted
    return _PINYIN_PATTERN.sub(_repl, text)


def protect_pinyin_annotations(text: str):
    """归一化前把 [zhu4] 保护为纯字母占位符（数字调号会被数字转中文逻辑破坏）"""
    placeholders = {}
    counter = [0]

    def _ph(i: int) -> str:
        return f"[[[PY{chr(ord('A') + i // 26)}{chr(ord('A') + i % 26)}]]]"

    def _repl(m):
        ph = _ph(counter[0])
        counter[0] += 1
        placeholders[ph] = m.group(0)
        return ph

    text = _PINYIN_PATTERN.sub(_repl, text)
    return text, placeholders


# ── CSV 词典加载（mtime 缓存 + 热加载） ────────────────────────────────────
_cache = {"stamp": None, "fixes": {}}


def _resolve_path(path=None) -> str:
    return path or os.environ.get("PINYIN_FIXES_CSV") or DEFAULT_CSV_PATH


def _file_stamp(path: str):
    """文件变更指纹：mtime + size（Windows mtime 秒级精度，同秒修改靠 size 兜底）"""
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _read_csv_text(path: str):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def load_fixes(path=None) -> dict:
    """加载词典；文件变更后自动重载（按 mtime+size 指纹判断）"""
    path = _resolve_path(path)
    stamp = _file_stamp(path)
    if stamp is None:
        return {}
    if _cache["stamp"] == stamp:
        return _cache["fixes"]

    fixes = {}
    content = _read_csv_text(path)
    if content:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("word,") or line.startswith("词,"):
                continue  # 表头
            parts = line.split(",", 1)
            if len(parts) == 2:
                word = parts[0].strip()
                pron = parts[1].strip()
                if word:
                    fixes[word] = pron
    _cache["stamp"] = stamp
    _cache["fixes"] = fixes
    return fixes


def apply_pinyin_fixes(text: str, valid_tokens: set, path=None) -> str:
    """对文本应用词典纠正（词 → 注音，注音支持 [zhu4] 数字调号）"""
    if not text:
        return text
    fixes = load_fixes(path)
    for word, pron in fixes.items():
        if word in text:
            converted = convert_text_pinyin_annotations(pron, valid_tokens)
            if converted != pron:  # 注音被成功转换才替换
                text = text.replace(word, converted)
    return text
