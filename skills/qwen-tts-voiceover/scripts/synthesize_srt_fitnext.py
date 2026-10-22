"""按 SRT 时间轴复刻合成（fit-next 增强版）：用克隆音色逐条合成，再按字幕时间轴对齐拼接成整轨。

本文件是路线 B 的合成驱动（tts_qwen 工程 synthesize_srt.py 的 fit-next 增强拷贝，
见 SKILL.md「路线 B」）。与路线 A 的 tts_voiceover.py 的区别：**不重建时间轴**，
让每条语音在「下一句起点前 0.10s」与「槽位 + max-overflow」之间取小的窗口内自然走，
只在会撞下一句时才 atempo 提速——配音优先保持自然速度，画面时间轴一动不动。

核心策略：
  1. 每条 cue 用克隆音色独立合成（避免长文本漂移）
  2. 测自然时长 vs 可用窗口
  3. 用 atempo（保持音高）微调：会撞下一句才加速（≤max-speedup），仍超才硬裁
  4. 按字幕起点绝对定位拼接，输出整轨 + manifest

用法：
  python synthesize_srt_fitnext.py --model 1.7b \
      --ref-audio assets/ref/ref_cand1.wav --ref-text "..." \
      --srt <字幕.srt> --out-dir output/ep01
"""
import os
import sys
import json
import argparse
import re
import time
import subprocess
from pathlib import Path

os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import numpy as np
import soundfile as sf
import soxr
import torch

# 运行时工程根：tts_cli.py 与模型权重都在 tts_qwen 工程里（不在本 skill 目录）。
# 优先环境变量 TTS_QWEN_DIR；未设置时回退到本脚本父目录的父目录（tts_qwen 原位使用场景）。
QWEN_ROOT = Path(os.environ.get("TTS_QWEN_DIR") or Path(__file__).resolve().parent.parent.parent)
ROOT = Path(__file__).resolve().parent.parent
for _p in (QWEN_ROOT / "scripts", ROOT / "scripts"):
    if (_p / "tts_cli.py").exists():
        sys.path.insert(0, str(_p))
        break
from tts_cli import parse_srt, normalize_text  # noqa: E402

MODELS = {
    "1.7b": QWEN_ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-Base",
    "0.6b": QWEN_ROOT / "models" / "Qwen3-TTS-12Hz-0.6B-Base",
}
# ffmpeg：默认取 PATH，可用 VIBE_FFMPEG 覆盖（项目私有 tools/ 目录等）
FFMPEG = Path(os.environ.get("VIBE_FFMPEG", "ffmpeg"))


def atempo_chain(factor: float) -> str:
    """ffmpeg atempo 单级上限 2.0，级联处理。"""
    f = float(factor)
    parts = []
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={f:.4f}")
    return ",".join(parts)


def time_stretch(wav: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """factor>1 = 变短（加速）。用 ffmpeg atempo 保音高。"""
    if abs(factor - 1.0) < 0.005:
        return wav
    tmp_in = QWEN_ROOT / "output" / "_tmp_in.wav"
    tmp_out = QWEN_ROOT / "output" / "_tmp_out.wav"
    tmp_in.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(tmp_in), wav.astype(np.float32), sr)
    cmd = [str(FFMPEG), "-y", "-loglevel", "error", "-i", str(tmp_in),
           "-filter:a", atempo_chain(factor), "-ar", str(sr), "-ac", "1", str(tmp_out)]
    subprocess.run(cmd, check=True)
    out, sr2 = sf.read(str(tmp_out), dtype="float32", always_2d=True)
    out = out.mean(axis=1)
    for f in (tmp_in, tmp_out):
        f.unlink(missing_ok=True)
    return out.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="1.7b", choices=list(MODELS))
    ap.add_argument("--ref-audio", required=True)
    ap.add_argument("--ref-text", required=True)
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--language", default="Chinese")
    ap.add_argument("--max-speedup", type=float, default=1.18, help="最大加速倍数")
    ap.add_argument("--max-slowdown", type=float, default=1.10, help="最大放慢倍数")
    ap.add_argument("--gap", type=float, default=0.06, help="每条后保留的最小静音")
    ap.add_argument("--seed", type=int, default=20261019)
    # ---- 抗失控参数 ----
    ap.add_argument("--repetition-penalty", type=float, default=1.05)
    ap.add_argument("--max-new-tokens", type=int, default=2048)
    ap.add_argument("--token-cap-ratio", type=float, default=1.7,
                    help="预估 token 上限倍数")
    ap.add_argument("--retries", type=int, default=4, help="单条最大采样次数")
    # ---- fit-next：允许语音自然溢入下一句前的空档（视频时间轴不动，见项目记忆 2026-10-22）----
    ap.add_argument("--fit-next", dest="fit_next", action="store_true", default=True,
                    help="可用窗口=下一句起点-0.10s（与槽位+max-overflow 取小），只在会撞下一句时提速；默认开")
    ap.add_argument("--no-fit-next", dest="fit_next", action="store_false",
                    help="回退旧行为：严格压回字幕槽位")
    ap.add_argument("--max-overflow", type=float, default=1.5, help="单条允许溢出的最大秒数")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else QWEN_ROOT / "output" / f"yjrj_{args.model}"
    out_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    from qwen_tts import Qwen3TTSModel
    print(f"[load] {MODELS[args.model].name}", flush=True)
    model = Qwen3TTSModel.from_pretrained(
        str(MODELS[args.model]), device_map="cuda:0",
        dtype=torch.bfloat16, attn_implementation="sdpa")

    t0 = time.time()
    prompt = model.create_voice_clone_prompt(
        ref_audio=args.ref_audio, ref_text=args.ref_text, x_vector_only_mode=False)
    print(f"[prompt] {time.time() - t0:.2f}s", flush=True)

    cues = parse_srt(Path(args.srt))
    print(f"[srt] {len(cues)} cues, span {cues[-1]['end'] - cues[0]['start']:.1f}s", flush=True)

    # 预计算每条到下一句起点的距离：fit-next 模式下一条语音最多占到下一句前 0.10s
    for i, cue in enumerate(cues):
        cue["_next_start"] = cues[i + 1]["start"] if i + 1 < len(cues) else float("inf")

    SR = None
    clips = []
    skipped = []
    t_all = time.time()
    TOK_PER_SEC = 12.5          # 12Hz tokenizer：12.5 token = 1 秒音频

    for n, cue in enumerate(cues, 1):
        text = normalize_text(cue["text"])
        slot = cue["end"] - cue["start"]
        # 可用窗口：fit-next 下允许溢到下一句起点前 0.10s，但总溢出不超过 max-overflow；
        # 最后一条不受下一句限制（片尾溢出由视频末帧延长消化）
        if args.fit_next:
            window = min(cue["_next_start"] - cue["start"] - 0.10, slot + args.max_overflow)
        else:
            window = slot
        chars = len(re.sub(r"\s", "", text))
        # 预估本次需要的 token：按参考语速 6 字/秒推，留 1.7x 余量
        est_sec = max(chars / 6.0, window * 0.8)
        tok_cap = min(args.max_new_tokens,
                      max(160, int(est_sec * TOK_PER_SEC * args.token_cap_ratio)))

        # 多次采样，挑最接近槽位的候选（采样有随机性，单次可能撞上重复循环）
        cands = []
        for attempt in range(args.retries):
            t1 = time.time()
            try:
                wavs, sr = model.generate_voice_clone(
                    text=text, language=args.language, voice_clone_prompt=prompt,
                    repetition_penalty=args.repetition_penalty,
                    max_new_tokens=tok_cap)
                cand = np.asarray(wavs[0], dtype=np.float32)
                SR = sr
                elapsed = time.time() - t1
                cd = len(cand) / sr
                # 截断检测：用满 token 上限 => 大概率是重复循环
                truncated = cd >= (tok_cap / TOK_PER_SEC) * 0.92
                if truncated and attempt < args.retries - 1:
                    print(f"    [warn] #{cue['idx']} 第{attempt + 1}次 {cd:.1f}s 触顶截断，重采样",
                          flush=True)
                    continue
                if truncated:
                    cand = cand[: int(slot * sr)]     # 最后一次仍截断就硬裁
                ratio = abs(cd - slot) / slot
                cands.append((ratio, cand, cd, elapsed))
                if ratio <= 0.22:                     # 已足够贴合，不必再采
                    break
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    torch.cuda.empty_cache()
                    print(f"    [warn] #{cue['idx']} OOM，重试", flush=True)
                    continue
                raise

        if not cands:
            print(f"  [skip] #{cue['idx']} 重试 {args.retries} 次仍失败: {text[:30]}", flush=True)
            skipped.append(cue["idx"])
            continue

        cands.sort(key=lambda x: x[0])
        _, wav, nat, gen_t = cands[0]

        # 时长适配：放不下窗口才加速（保音色自然，用户口径 2026-10-22）；
        # 明显偏短仍按字幕槽轻微放慢填充（字幕停之前声音别断）
        adjusted, note = wav, ""
        if nat > window - args.gap:                  # 窗口放不下 -> 加速
            factor = min(nat / max(window - args.gap, 0.3), args.max_speedup)
            if factor > 1.005:
                adjusted = time_stretch(wav, sr, factor)
                note = f"speedup x{factor:.2f}"
            if len(adjusted) / sr > window:          # 仍超 -> 硬裁
                adjusted = adjusted[: int(window * sr)]
                note += " +trim"
        elif nat < slot * 0.82:                      # 明显偏短 -> 轻微放慢
            factor = min(slot / nat, args.max_slowdown)
            if factor > 1.005:
                adjusted = time_stretch(wav, sr, 1.0 / factor)
                note = f"slow x{1 / factor:.2f}"

        final = len(adjusted) / sr
        fn = out_dir / f"cue_{cue['idx']:03d}.wav"
        sf.write(str(fn), adjusted, sr)
        clips.append({"idx": cue["idx"], "start": cue["start"], "slot": round(slot, 3),
                      "window": round(window, 3),
                      "natural": round(nat, 3), "final": round(final, 3),
                      "over_slot": round(final - slot, 3),
                      "cps": round(len(text) / max(final, 1e-6), 2),
                      "gen_sec": round(gen_t, 2), "note": note, "text": text})
        print(f"  [{n:>2}/{len(cues)}] #{cue['idx']:>2} slot={slot:5.2f} nat={nat:5.2f} "
              f"fin={final:5.2f} cps={clips[-1]['cps']:4.1f} {note:<18} {text[:24]}", flush=True)

    # ---- 按时间轴拼接 ----
    # 末条语音可能溢到 cues[-1]["end"] 之后（片尾溢出）：音轨长度要按实际最晚结束点算，
    # 多出来的尾巴由并轨时视频末帧延长消化（项目口径 2026-10-22）
    last_end = max((c["start"] + c["final"]) for c in clips) if clips else 0.0
    total_len = int((max(cues[-1]["end"], last_end) + 0.3) * SR)
    track = np.zeros(total_len, dtype=np.float32)
    for c in clips:
        w, _ = sf.read(str(out_dir / f"cue_{c['idx']:03d}.wav"), dtype="float32", always_2d=True)
        w = w.mean(axis=1)
        i0 = int(c["start"] * SR)
        i1 = min(i0 + len(w), total_len)
        track[i0:i1] = w[:i1 - i0]

    # 峰值归一化到 -1dBFS
    peak = float(np.max(np.abs(track))) or 1.0
    track = track / peak * 0.89

    full = out_dir / "full_raw.wav"
    sf.write(str(full), track, SR)

    nat_total = sum(c["final"] for c in clips)
    meta = {
        "model": args.model, "ref_audio": str(args.ref_audio),
        "srt": str(args.srt), "cue_count": len(clips),
        "sample_rate": SR, "duration_sec": round(total_len / SR, 2),
        "speech_sec": round(nat_total, 2),
        "avg_cps": round(sum(c["cps"] for c in clips) / len(clips), 2),
        "speedup_count": sum(1 for c in clips if "speedup" in c["note"]),
        "trim_count": sum(1 for c in clips if "trim" in c["note"]),
        "over_slot_count": sum(1 for c in clips if c["over_slot"] > 0.05),
        "voice_end_sec": round(last_end, 2),
        "wall_sec": round(time.time() - t_all, 2),
        "rtf": round(nat_total / max(1e-9, time.time() - t_all), 2),
        "items": clips,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[done] {full}", flush=True)
    print(f"  时长 {meta['duration_sec']}s  有声 {meta['speech_sec']}s  "
          f"平均语速 {meta['avg_cps']} 字/秒", flush=True)
    print(f"  加速 {meta['speedup_count']} 条 / 裁剪 {meta['trim_count']} 条 / "
          f"墙钟 {meta['wall_sec']}s (RTF {meta['rtf']}x)", flush=True)


if __name__ == "__main__":
    main()
