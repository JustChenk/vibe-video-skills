"""评测 TTS 输出：音色相似度（speaker embedding 余弦）+ 语音清晰度（ASR 回环 CER）。

用法：
  python scripts/eval_tts.py --model 1.7b --ref assets/ref/ref_cand2.wav \
      --text "要合成的文本" --audio output/clone_1.7b.wav
  # 批量
  python scripts/eval_tts.py --batch output/xxx/manifest.json
"""
import os
import sys
import json
import argparse
import re
from pathlib import Path

os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
# 模型目录：可用环境变量 TTS_QWEN_DIR 指向 tts_qwen 工程根，或命令行 --model-dir / --qwen-dir
QWEN_ROOT = Path(os.environ.get("TTS_QWEN_DIR") or ROOT)
MODELS = {
    "1.7b": QWEN_ROOT / "models" / "Qwen3-TTS-12Hz-1.7B-Base",
    "0.6b": QWEN_ROOT / "models" / "Qwen3-TTS-12Hz-0.6B-Base",
}


def cos(a, b):
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


_PUNCT = "，。！？、；：\u201c\u201d\u2018\u2019（）《》…—-"
_PUNCT += ",.!?;:\"'()[]{}<>"


def norm_cn(s: str) -> str:
    """归一化，便于 CER 计算：去标点、转小写、去空格。"""
    s = re.sub("[" + re.escape(_PUNCT) + r"\s]", "", s)
    return s.lower()


def cer(ref: str, hyp: str) -> float:
    ref, hyp = norm_cn(ref), norm_cn(hyp)
    if not ref:
        return 1.0
    # Levenshtein
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


def med_f0(path):
    """中位基频（Hz）。音高突变（如女声克隆里冒出男声）在 cos 上可能仍 >0.95，
    但 F0 会腰斩 —— 这是抓「换了个声音」最灵敏的单一判据。"""
    import librosa
    wav, sr = librosa.load(str(path), sr=16000, mono=True)
    f0 = librosa.yin(wav, fmin=60, fmax=600, sr=16000)
    f0 = f0[np.isfinite(f0)]
    return float(np.median(f0)) if len(f0) else 0.0


def load_model(key):
    from qwen_tts import Qwen3TTSModel
    return Qwen3TTSModel.from_pretrained(
        str(MODELS[key]), device_map="cuda:0", dtype=torch.bfloat16,
        attn_implementation="sdpa")


def spk_emb(model, path):
    import librosa
    wav, sr = librosa.load(str(path), sr=None, mono=True)
    tgt = model.model.speaker_encoder_sample_rate
    if sr != tgt:
        wav = librosa.resample(y=wav.astype(np.float32), orig_sr=sr, target_sr=tgt)
    with torch.no_grad():
        e = model.model.extract_speaker_embedding(audio=wav.astype(np.float32), sr=tgt)
    return e.detach().float().cpu().numpy()


_WM = None
_WHISPER_DIR = os.environ.get(
    "WHISPER_DIR",
    str(ROOT / "models" / "hf_home" / "hub"
        / "models--Systran--faster-whisper-large-v3" / "snapshots"))


def _get_whisper():
    global _WM
    if _WM is not None:
        return _WM
    from faster_whisper import WhisperModel
    # 优先用本地快照，避免联网重下
    p = Path(_WHISPER_DIR)
    if p.is_dir() and (p / "config.json").exists():
        target = str(p)
    elif p.is_dir() and list(p.glob("*/model.bin")):
        target = str(next(p.glob("*/model.bin")).parent)
    else:
        target = "large-v3"
    print(f"[asr] whisper = {target}", flush=True)
    _WM = WhisperModel(target, device="cuda", compute_type="float16")
    return _WM


def asr(path):
    """ASR 回环（Whisper 单例，避免每条重载导致 OOM）。"""
    import soundfile as sf
    import soxr
    a, sr = sf.read(str(path), dtype="float32", always_2d=True)
    a = a.mean(axis=1)
    if sr != 16000:
        a = soxr.resample(a, sr, 16000).astype(np.float32)
    segs, _ = _get_whisper().transcribe(
        a, language="zh", beam_size=5, vad_filter=False,
        condition_on_previous_text=False)
    return "".join(s.text for s in segs).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="1.7b", choices=list(MODELS))
    ap.add_argument("--qwen-dir", default=None,
                    help="tts_qwen 工程根（含 models/）；也可用环境变量 TTS_QWEN_DIR")
    ap.add_argument("--ref", required=True)
    ap.add_argument("--text", default=None)
    ap.add_argument("--audio", default=None)
    ap.add_argument("--batch", default=None, help="align_report.json 或 manifest.json，批量评测")
    ap.add_argument("--take-suffix", default=None,
                    help="align_report 模式下 take/ 文件后缀（默认 qwen）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # 允许命令行覆盖模型根目录
    if args.qwen_dir:
        MODELS["1.7b"] = Path(args.qwen_dir) / "models" / "Qwen3-TTS-12Hz-1.7B-Base"
        MODELS["0.6b"] = Path(args.qwen_dir) / "models" / "Qwen3-TTS-12Hz-0.6B-Base"

    # ---- 阶段 1：算音色相似度（占用显存）----
    import gc
    model = load_model(args.model)
    ref_e = spk_emb(model, args.ref)

    targets = []
    if args.batch:
        man = json.loads(Path(args.batch).read_text(encoding="utf-8"))
        base = Path(args.batch).parent
        if "cues" in man:
            # tts_voiceover.py 的 align_report.json：cue 存在 take/{i:03d}_<engine>.wav
            take = base / "take"
            engine = args.take_suffix or "qwen"
            for c in man["cues"]:
                i = c.get("i", c.get("idx"))
                cands = [take / f"{i:03d}_{engine}.wav", take / f"{i:03d}.wav"]
                p = next((x for x in cands if x.exists()), None)
                if p:
                    targets.append((p, c.get("text", ""), p.name))
        else:
            # build/tts_cli 产出的 manifest：items[] 带 file 或 idx
            for it in man["items"]:
                name = it.get("file") or f"cue_{it['idx']:03d}.wav"
                p = base / name
                if p.exists():
                    targets.append((p, it.get("text", ""), name))
    else:
        targets.append((Path(args.audio), args.text or "", Path(args.audio).name))

    sims = [(round(cos(ref_e, spk_emb(model, p)), 4)) for p, _, _ in targets]

    # ---- 参考音的 F0 基准（音高是第二道、也是最灵敏的判据）----
    ref_f0 = med_f0(args.ref)
    f0s = [round(med_f0(p), 1) for p, _, _ in targets]

    # ---- 释放 TTS 模型，给 ASR 腾显存（8GB 卡必须）----
    del model
    gc.collect()
    torch.cuda.empty_cache()
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        print(f"[eval] freed TTS model; VRAM free {free / 1024 ** 3:.2f}/{total / 1024 ** 3:.2f} GB", flush=True)
    print(f"[eval] 参考音 F0 中位 = {ref_f0:.1f} Hz", flush=True)

    # ---- 阶段 2：ASR 回环算 CER ----
    rows = []
    for (p, txt, name), sim, f0 in zip(targets, sims, f0s):
        hyp = asr(p)
        rows.append({"file": name, "text": txt, "asr": hyp, "spk_cos": sim,
                     "f0": f0, "f0_ratio": round(f0 / ref_f0, 3) if ref_f0 else None,
                     "cer": round(cer(txt, hyp), 4) if txt else None})
        flag = ""
        if sim < 0.95:
            flag += " ⚠cos"
        if ref_f0 and f0 < ref_f0 * 0.75:
            flag += " ⚠F0"
        print(f"{name:>12}  spk_cos={sim:.3f}  F0={f0:6.1f}Hz  "
              f"CER={rows[-1]['cer'] if rows[-1]['cer'] is not None else float('nan'):.3f}"
              f"{flag}  {hyp[:34]}", flush=True)

    if rows:
        ok = [r for r in rows if r["cer"] is not None]
        bad = [r for r in rows if r["spk_cos"] < 0.95
               or (ref_f0 and r["f0"] < ref_f0 * 0.75)]
        print(f"\n[summary] n={len(rows)}  mean_spk_cos={np.mean([r['spk_cos'] for r in rows]):.4f}"
              f"  F0={min(r['f0'] for r in rows):.0f}~{max(r['f0'] for r in rows):.0f}Hz"
              + (f"  mean_CER={np.mean([r['cer'] for r in ok]):.4f}" if ok else ""), flush=True)
        if bad:
            print(f"[summary] ⚠ 音色/音高异常 {len(bad)} 条：{[(r['file'], r['spk_cos'], r['f0']) for r in bad]}",
                  flush=True)
        else:
            print("[summary] ✓ 全部通过音色+音高判据", flush=True)

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
