"""挑选参考音片段：在词边界滑窗切出 9~12s 干净语音，再对裁剪片段单独 ASR 得到精确 ref_text。

⚠ 关键：参考音必须在语音自然停顿处收尾，且尾部补齐数字静音。
  若在字中间硬切（末采样幅度大），克隆结果会在每句开头多出半个字（"是""的是"）。
  官方示例 clone.wav 的末采样=0.0000，其克隆结果完全干净，是最直接的对照证据。

用法：
  python scripts/pick_ref.py assets/sep/vocals.wav assets/ref
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from faster_whisper import WhisperModel

SRC = Path(sys.argv[1])
OUTDIR = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("assets/ref")
OUTDIR.mkdir(parents=True, exist_ok=True)

TAIL_SILENCE_MS = 250      # 尾部补齐的静音
FADE_MS = 15               # 收尾淡出
PAD = 0.06                 # 词结束后的余量


def whisper_target():
    """Whisper 模型来源：WHISPER_DIR 指向本地快照目录（离线首选），否则用模型名联网下载。"""
    env = os.environ.get("WHISPER_DIR")
    if env:
        p = Path(env)
        if (p / "config.json").exists():
            return str(p)
        inner = list(p.glob("*/config.json"))
        if inner:
            return str(inner[0].parent)
    return os.environ.get("WHISPER_MODEL", "large-v3")


audio, sr = sf.read(str(SRC), dtype="float32", always_2d=True)
audio = audio.mean(axis=1)
a16 = soxr.resample(audio, sr, 16000).astype(np.float32) if sr != 16000 else audio

model = WhisperModel(whisper_target(), device="cuda", compute_type="float16")


def asr_text(clip: np.ndarray, sr_in: int) -> str:
    a = soxr.resample(clip, sr_in, 16000).astype(np.float32) if sr_in != 16000 else clip
    segs, _ = model.transcribe(a, language="zh", beam_size=5, vad_filter=False,
                               condition_on_previous_text=False,
                               initial_prompt="以下是普通话的句子。")
    return "".join(x.text for x in segs).strip()


words_file = OUTDIR / "_words.json"
if words_file.exists():
    words = json.loads(words_file.read_text(encoding="utf-8"))
    print(f"[pick] reuse {len(words)} words", flush=True)
else:
    print("[pick] pass 1: word timestamps", flush=True)
    segments, info = model.transcribe(
        a16, language="zh", beam_size=5, vad_filter=False, word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt="以下是普通话的句子，内容关于 App、小程序、逆向工程、AI、热点新闻。",
    )
    words = [{"w": w.word, "s": float(w.start), "e": float(w.end)}
             for seg in segments for w in (seg.words or [])]
    words_file.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[pick] {len(words)} words", flush=True)

# 词前 gap（越大越适合做起点）
def gap_before(i):
    return words[i]["s"] - words[i - 1]["e"] if i > 0 else 9.9


# 滑窗：每个起点向后续拼到 9~12s
cands = []
for i in range(len(words)):
    j = i
    while j + 1 < len(words) and words[j]["e"] - words[i]["s"] < 9.0:
        j += 1
    if j >= len(words):
        break
    dur = words[j]["e"] - words[i]["s"]
    if not (9.0 <= dur <= 12.5):
        continue
    txt = "".join(x["w"] for x in words[i:j + 1]).strip()
    # 前置/后置停顿越大越好，字符密度适中最好
    cands.append({
        "i": i, "j": j, "s": words[i]["s"], "e": words[j]["e"], "dur": dur,
        "text": txt, "chars": len(txt),
        "pre": gap_before(i),
        "post": (words[j + 1]["s"] - words[j]["e"]) if j + 1 < len(words) else 9.9,
    })

print(f"[pick] {len(cands)} sliding windows", flush=True)

# 打散：为了覆盖不同段落，按时间分段各取最优。
# 优先选 post_gap 大的（后面有停顿）——这样收尾才能落在语音自然结束处。
cands.sort(key=lambda c: (c["post"] > 0.10, c["pre"] + c["post"],
                          abs(c["dur"] - 10.5)), reverse=True)
picked, used_time = [], []
for c in cands:
    if any(abs(c["s"] - t) < 20 for t in used_time):
        continue
    picked.append(c)
    used_time.append(c["s"])
    if len(picked) >= 4:
        break


def clean_cut(end_sec):
    """在 end_sec 处收尾：淡出 + 补数字静音，杜绝半字残留。"""
    i0 = max(0, int((end_sec - 9.5) * sr))
    i1 = min(len(audio), int((end_sec + PAD) * sr))
    seg = audio[i0:i1].copy()
    n = int(FADE_MS / 1000 * sr)
    if 0 < n < len(seg):
        ramp = 0.5 * (1 + np.cos(np.linspace(0, np.pi, n)))
        seg[-n:] *= ramp.astype(np.float32)
    seg = np.concatenate([seg, np.zeros(int(TAIL_SILENCE_MS / 1000 * sr), dtype=np.float32)])
    peak = float(np.max(np.abs(seg))) or 1.0
    return (seg / peak * 0.7).astype(np.float32)


print("\n[pick] === 候选 ===", flush=True)
out = []
for n, c in enumerate(picked, 1):
    clip = clean_cut(c["e"])          # 用词结束点作收尾，不再往后多切
    fn = OUTDIR / f"ref_cand{n}.wav"
    sf.write(str(fn), clip, sr)

    txt = asr_text(clip, sr)
    (OUTDIR / f"ref_cand{n}.txt").write_text(txt, encoding="utf-8")
    speech_len = len(clip) / sr - TAIL_SILENCE_MS / 1000
    tail_peak = float(np.max(np.abs(clip[-int(0.2 * sr):])))
    print(f"\n[{n}] {fn.name}  {len(clip) / sr:.2f}s (语音 {speech_len:.2f}s + 静音 "
          f"{TAIL_SILENCE_MS}ms)  pre_gap={c['pre']:.2f} post_gap={c['post']:.2f}", flush=True)
    print(f"    尾部 200ms 峰值={tail_peak:.6f}  {'✅ 干净收尾' if tail_peak < 1e-6 else '⚠ 未清零'}", flush=True)
    print(f"    精文本: {txt}", flush=True)
    out.append({"n": n, "file": fn.name, "dur": round(len(clip) / sr, 2),
                "text": txt, "start": round(c["s"], 2), "end": round(c["e"], 2),
                "tail_peak": tail_peak})

OUTDIR.joinpath("_ref_candidates.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n[pick] done", flush=True)
