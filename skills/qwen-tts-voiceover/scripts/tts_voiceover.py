#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_voiceover.py —— 按 SRT 给动画工程配音，三级对齐后重排时间轴

用法:
    python scripts/tts_voiceover.py <srt> <outdir> --project <工程目录>
    python scripts/tts_voiceover.py x.srt x/voicework --project x --voice zh-CN-YunxiNeural

三级对齐:
    L1 句内变速：仅在 --auto-tempo 打开时，把超过可用槽位 --max-tempo 倍的句子压回去
    L2 吞并 gap：句子起点 = max(原字幕起点, 前句结束 + --min-gap)，留白全部可借
    L3 幕级重排：幕只增不减（max(原dur, 语音需求 + --tail)），画面靠 TIME_MAP 拉伸

产出:
    <outdir>/voice.wav              整轨配音 44.1k / 单声道 / s16
    <outdir>/voice_new.srt          新时间轴字幕
    <outdir>/align_report.json      逐句对账（窗口 / 实测 / 新位置 / 溢出）
    <outdir>/take/NNN.mp3|wav       逐句音档（改音色后可只重跑部分）
    <project>/voice_timeline.js     注入段（video_voice.html 加载）
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# skill 根目录（本脚本位于 <skill>/scripts/ 下）
ROOT = Path(__file__).resolve().parent.parent


def find_ffmpeg(explicit=None):
    """定位 ffmpeg：显式参数 > 环境变量 > skill 同级 tools/ > PATH。"""
    cands = []
    if explicit:
        cands.append(Path(explicit))
    env = os.environ.get('FFMPEG')
    if env:
        cands.append(Path(env))
    # 常见工程布局：项目根/tools/ffmpeg.exe
    cands += [ROOT / 'tools' / 'ffmpeg.exe', ROOT.parent / 'tools' / 'ffmpeg.exe',
              ROOT / 'tools' / 'ffmpeg']
    for c in cands:
        if c.exists():
            return c
    import shutil
    found = shutil.which('ffmpeg')
    if found:
        return Path(found)
    return Path(explicit or 'ffmpeg')


RATE = 44100
TS_RE = re.compile(
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')


def log(*a):
    print(*a, flush=True)


# ---------------- SRT ----------------

def parse_srt(path):
    raw = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', raw.strip()):
        m = TS_RE.search(block)
        if not m:
            continue
        g = list(map(int, m.groups()))
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        lines = [l.strip() for l in block.split('\n')]
        i = next(i for i, l in enumerate(lines) if '-->' in l)
        text = ''.join(l for l in lines[i + 1:] if l).strip()
        if text:
            cues.append({'start': a, 'end': b, 'text': text})
    return cues


def fmt_srt(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


# ---------------- 幕结构 ----------------

def read_acts(project):
    txt = (Path(project) / 'framework.js').read_text(encoding='utf-8')
    pairs = re.findall(r'\{start:\s*([\d.]+)\s*,\s*dur:\s*([\d.]+)', txt)
    return [{'name': f'S{i + 1}', 'start': float(s), 'dur': float(d)} for i, (s, d) in enumerate(pairs)]


# ---------------- TTS ----------------

def sapi_synth(text, out_wav, rate=0, voice_kw='Huihui'):
    """Windows 本地 SAPI 合成（离线兜底，音色一般；用于验证链路，正式出片请换引擎）"""
    import win32com.client
    sp = win32com.client.Dispatch('SAPI.SpVoice')
    vs = sp.GetVoices()
    picked = None
    for i in range(vs.Count):
        d = vs.Item(i).GetDescription()
        if voice_kw.lower() in d.lower():
            picked = vs.Item(i)
            break
    if picked is not None:
        sp.Voice = picked
    sp.Rate = max(-10, min(10, rate))
    stream = win32com.client.Dispatch('SAPI.SpFileStream')
    stream.Open(str(Path(out_wav).resolve()), 3, False)
    sp.AudioOutputStream = stream
    sp.Speak(text)
    stream.Close()


# ---------------- Qwen3-TTS 本地克隆引擎 ----------------

def qwen_synth_batch(cues, ref_audio, ref_text, model_key, evo, language='Chinese',
                     token_cap_ratio=1.7, max_retries=5, log_fn=log,
                     spk_threshold=0.95, f0_ratio=0.75):
    """用 Qwen3-TTS Base 模型逐句克隆合成（保持与 edge/sapi 引擎相同的产出契约）。

    关键点（踩过的坑，别改回去）：
      1) max_new_tokens 必须按句子长度封顶 —— generation_config 默认 8192（≈655s 音频），
         采样一旦进重复循环会狂生成几分钟，表现为「卡死」。
      2) 触顶即判截断并重采样 —— 采样有随机性，单次可能撞上重复循环。
      3) 参考音末采样必须≈0（在语音自然停顿处收尾 + 补数字静音），
         否则每句开头会多出参考音尾字（如「的是」）。
      4) **必须做说话人 + 音高校验** —— 仅靠「时长接近预估」选候选远远不够：
         本项目中第 21 条「Ghidra 看程序，IDA、Hopper 看二进制，JADX 拆安卓包」
         含大量英文专名，采样崩成**男声**（F0 320Hz→144Hz），但时长恰好接近预估。
         教训：阈值 0.90 太松 —— 实测正常句 cos 在 0.966~0.987，
         崩坏句 0.9202 仍 >0.90 被放行。现取 **0.95**（落在实测空隙里），
         并加 **F0 比值**双保险（崩坏句 F0 只有参考音的约 45%）。
    """
    import numpy as np
    import soundfile as sf
    import torch

    sys.path.insert(0, str(evo))
    from qwen_tts import Qwen3TTSModel

    MODELS = {
        '1.7b': evo / 'models' / 'Qwen3-TTS-12Hz-1.7B-Base',
        '0.6b': evo / 'models' / 'Qwen3-TTS-12Hz-0.6B-Base',
    }
    model_dir = MODELS[model_key]
    if not model_dir.exists():
        sys.exit(f'✗ 模型不存在：{model_dir}')
    if not Path(ref_audio).exists():
        sys.exit(f'✗ 参考音不存在：{ref_audio}')

    log_fn(f'   Qwen3-TTS {model_key} ← {model_dir.name}')
    model = Qwen3TTSModel.from_pretrained(
        str(model_dir), device_map='cuda:0', dtype=torch.bfloat16,
        attn_implementation='sdpa')
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(ref_audio), ref_text=ref_text, x_vector_only_mode=False)

    # ---- 参考音的音色基准 + 音高基准 ----
    import librosa

    def spk_emb(arr, sr):
        tgt = model.model.speaker_encoder_sample_rate
        a = arr.astype(np.float32)
        if sr != tgt:
            a = librosa.resample(y=a, orig_sr=int(sr), target_sr=tgt)
        with torch.no_grad():
            e = model.model.extract_speaker_embedding(audio=a, sr=tgt)
        return e.detach().float().cpu().numpy().ravel()

    def med_f0(arr, sr):
        a = arr.astype(np.float32)
        if sr != 16000:
            a = librosa.resample(y=a, orig_sr=int(sr), target_sr=16000)
        f = librosa.yin(a, fmin=60, fmax=600, sr=16000)
        f = f[np.isfinite(f)]
        return float(np.median(f)) if len(f) else 0.0

    ref_w, ref_sr = sf.read(str(ref_audio), dtype='float32', always_2d=True)
    ref_mono = ref_w.mean(axis=1)
    ref_e = spk_emb(ref_mono, ref_sr)
    ref_f0 = med_f0(ref_mono, ref_sr)
    log_fn(f'   参考音基准：cos=1.000  F0中位={ref_f0:.1f}Hz')

    def cos(a, b):
        return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))

    def voice_ok(wav, sr):
        """音色 + 音高双判据。返回 (是否合格, cos, f0)。"""
        s = cos(ref_e, spk_emb(wav, sr))
        f = med_f0(wav, sr)
        ok = s >= spk_threshold and (ref_f0 <= 0 or f >= ref_f0 * f0_ratio)
        return ok, s, f

    TOK_PER_SEC = 12.5        # 12Hz tokenizer
    ok_n, fail, retried = 0, [], []
    for i, c in enumerate(cues):
        text = c['text'].strip()
        chars = len(re.sub(r'\s', '', text))
        # 预估需要多久：按 6 字/秒推，至少给 1.2s，留 token_cap_ratio 余量
        est = max(chars / 6.0, 1.2)
        tok_cap = max(160, int(est * TOK_PER_SEC * token_cap_ratio))

        cands = []
        for attempt in range(max_retries):
            try:
                torch.manual_seed(20261019 + i * 1009 + attempt)
                wavs, sr = model.generate_voice_clone(
                    text=text, language=language, voice_clone_prompt=prompt,
                    max_new_tokens=tok_cap)
                wav = np.asarray(wavs[0], dtype=np.float32).ravel()
                dur = len(wav) / sr

                # ① 截断 = 撞上重复循环
                if dur >= (tok_cap / TOK_PER_SEC) * 0.92 and attempt < max_retries - 1:
                    continue
                # ② 音色 / 音高跑偏 = 换了个人在说，必须重采
                good, sim, f0 = voice_ok(wav, sr)
                if not good and attempt < max_retries - 1:
                    log_fn(f'   ! #{i:>2} 第{attempt + 1}次音色/音高跑偏 '
                           f'(cos={sim:.3f}, F0={f0:.0f}Hz)，重采')
                    continue

                cands.append((dur, wav, sr, sim, f0, good))
                # 已经拿到「合格 + 时长接近」的，不用再采
                if good and abs(dur - est) / est <= 0.25:
                    break
            except RuntimeError as e:
                if 'out of memory' in str(e).lower():
                    torch.cuda.empty_cache()
                    continue
                raise
        if not cands:
            fail.append(i)
            c['dur'] = 0.0
            continue

        # 在「音色合格」的候选里取最接近预估时长的；都不过关就告警
        good_c = [x for x in cands if x[5]]
        if good_c:
            good_c.sort(key=lambda x: abs(x[0] - est))
            dur, wav, sr, sim, f0, _ = good_c[0]
        else:
            cands.sort(key=lambda x: -x[3])
            dur, wav, sr, sim, f0, _ = cands[0]
            retried.append((i, round(sim, 3), round(f0)))
            log_fn(f'   ⚠ #{i:>2} 音色仍偏低 (cos={sim:.3f}, F0={f0:.0f}Hz)，已用最佳候选')

        c['raw_dur'] = dur
        c['spk_cos'] = round(sim, 4)
        c['f0'] = round(f0, 1)
        sf.write(str(c['src']), wav, sr)
        ok_n += 1
        if (i + 1) % 10 == 0 or i + 1 == len(cues):
            log_fn(f'   … {i + 1}/{len(cues)}')

    del model
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    if fail:
        sys.exit(f'✗ {len(fail)} 句合成失败：{fail[:8]}')
    if retried:
        log_fn(f'   ⚠ 音色低于 {spk_threshold} 的句子：{retried}')
    else:
        log_fn(f'   ✓ 全部 {ok_n} 句音色合格 (cos≥{spk_threshold}, F0≥{ref_f0 * f0_ratio:.0f}Hz)')
    return ok_n



async def synth_one(text, voice, rate, out, sem, retries=3):
    import edge_tts
    async with sem:
        for k in range(retries):
            try:
                await edge_tts.Communicate(text, voice, rate=rate).save(str(out))
                if out.exists() and out.stat().st_size > 1024:
                    return True
            except Exception as e:
                if k == retries - 1:
                    log(f'   ✗ 合成失败 [{text[:18]}…] {type(e).__name__}: {e}')
                await asyncio.sleep(1.2 * (k + 1))
    return False


# ---------------- 音频 ----------------

def to_wav(ffmpeg, src, dst, tempo=1.0):
    """裁掉首尾静音（-50dB 以下），可选变速，统一 44.1k 单声道 s16"""
    af = ('silenceremove=start_periods=1:start_threshold=-50dB:detection=peak,'
          'areverse,'
          'silenceremove=start_periods=1:start_threshold=-50dB:detection=peak,'
          'areverse')
    if abs(tempo - 1.0) > 0.002:
        af += f',atempo={tempo:.4f}'
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-i', str(src), '-af', af,
                    '-ar', str(RATE), '-ac', '1', '-c:a', 'pcm_s16le', str(dst)], check=True)


def wav_dur(p):
    with wave.open(str(p), 'rb') as w:
        return w.getnframes() / w.getframerate()


# ---------------- 布局 ----------------

def layout(cues, acts, min_gap, tail):
    for a in acts:
        a['cues'] = []
    for c in cues:
        for a in acts:
            if a['start'] <= c['start'] < a['start'] + a['dur']:
                a['cues'].append(c)
                break
        else:
            acts[-1]['cues'].append(c)

    for a in acts:
        a['new_dur'] = a['dur']

    for _ in range(5):
        cur = 0.0
        for a in acts:
            a['new_start'] = cur
            scale = a['new_dur'] / a['dur'] if a['dur'] > 0 else 1.0
            t = cur
            for c in a['cues']:
                want = a['new_start'] + (c['start'] - a['start']) * scale
                c['new_start'] = max(want, t)
                c['new_end'] = c['new_start'] + c['dur']
                t = c['new_end'] + min_gap
            need = (a['cues'][-1]['new_end'] + tail - cur) if a['cues'] else 0.0
            a['new_dur'] = max(a['dur'], need)
            cur += a['new_dur']
    return cur


def build_track(cues, total, out):
    buf = bytearray((int(total * RATE) + 1) * 2)
    overlaps = []
    for c in cues:
        with wave.open(str(c['wav']), 'rb') as f:
            data = f.readframes(f.getnframes())
        off = int(round(c['new_start'] * RATE)) * 2
        end = off + len(data)
        if end > len(buf):
            buf.extend(b'\x00' * (end - len(buf)))
        elif any(buf[max(0, off - 1):min(len(buf), off + 24)]):
            overlaps.append(c['idx'])
        buf[off:end] = data
    with wave.open(str(out), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(bytes(buf))
    return overlaps


# ---------------- 输出：时间轴注入段 ----------------

def write_timeline(project, acts, cues, total):
    L = ["/* 自动生成：scripts/tts_voiceover.py —— 配音版时间轴注入段，别手改 */",
         f"window.__meta = {{ fps: 24, duration: {total:.3f} }};",
         "window.__SCENES = ["]
    for a in acts:
        L.append(f"  {{ start: {a['new_start']:.3f}, dur: {a['new_dur']:.3f}, name: '{a['name']}' }},")
    L += ["];", "window.__CAPTIONS_LIST = ["]
    for c in cues:
        txt = c['text'].replace('\\', '\\\\').replace("'", "\\'")
        L.append(f"  [{c['new_start']:.3f}, {c['new_end']:.3f}, '{txt}'],")
    L += ["];"]
    mt = ','.join(
        f"[{a['start']:.3f},{a['start'] + a['dur']:.3f},{a['new_start']:.3f},{a['new_start'] + a['new_dur']:.3f}]"
        for a in acts)
    L.append(f"window.__TIME_MAP = [{mt}];")
    L.append("""window.__TIME_REMAP = (function (M) {
  return function (t) {
    for (var i = 0; i < M.length; i++) {
      var o = M[i];
      if (t <= o[3] || i === M.length - 1) {
        var span = o[3] - o[2];
        var k = span > 0 ? (t - o[2]) / span : 0;
        k = Math.max(0, Math.min(1, k));
        return o[0] + k * (o[1] - o[0]);
      }
    }
    return t;
  };
})(window.__TIME_MAP);""")
    p = Path(project) / 'voice_timeline.js'
    p.write_text('\n'.join(L) + '\n', encoding='utf-8')
    return p


# ---------------- 主流程 ----------------

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('srt')
    ap.add_argument('outdir')
    ap.add_argument('--project', required=True)
    ap.add_argument('--engine', choices=['edge', 'sapi', 'qwen'], default='edge')
    ap.add_argument('--voice', default='zh-CN-YunxiNeural')
    ap.add_argument('--rate', default='+0%', help='edge-tts 语速，如 +10%%（注意带符号）')
    ap.add_argument('--sapi-voice', default='Huihui', help='SAPI 音色关键字：Huihui/Kangkang/Yaoyao')
    ap.add_argument('--sapi-rate', type=int, default=2, help='SAPI 语速 -10~10')
    ap.add_argument('--jobs', type=int, default=4)
    # ---- qwen 引擎 ----
    ap.add_argument('--qwen-model', default='1.7b', choices=['1.7b', '0.6b'],
                    help='Qwen3-TTS Base 模型规格')
    ap.add_argument('--qwen-dir', default=os.environ.get('TTS_QWEN_DIR', ''),
                    help='tts_qwen 工程根目录（含 models/）。也可用环境变量 TTS_QWEN_DIR')
    ap.add_argument('--ref-audio', default=None,
                    help='qwen 引擎的参考音（必须已做干净收尾，末采样≈0）')
    ap.add_argument('--ref-text', default=None, help='参考音对应文本；省略则读同名 .txt')
    ap.add_argument('--qwen-language', default='Chinese')
    ap.add_argument('--min-gap', type=float, default=0.12)
    ap.add_argument('--tail', type=float, default=0.5)
    ap.add_argument('--auto-tempo', action='store_true', help='开启 L1：超长句轻度变速')
    ap.add_argument('--max-tempo', type=float, default=1.10)
    ap.add_argument('--ffmpeg', default=None, help='ffmpeg 路径（默认自动查找）')
    args = ap.parse_args()

    outdir = Path(args.outdir)
    take = outdir / 'take'
    take.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg(args.ffmpeg)
    if not (ffmpeg.exists() or str(ffmpeg) == 'ffmpeg'):
        sys.exit(f'✗ 找不到 ffmpeg：{ffmpeg}（用 --ffmpeg 或环境变量 FFMPEG 指定）')

    cues = parse_srt(args.srt)
    acts = read_acts(args.project)
    if not cues:
        sys.exit('✗ SRT 没解析出字幕')
    if not acts:
        sys.exit('✗ 读不到 SCENES，检查 --project 指向的 framework.js')
    old_total = max(a['start'] + a['dur'] for a in acts)
    log(f'字幕 {len(cues)} 句 / 幕 {len(acts)} 段 / 原总长 {old_total:.1f}s')
    log(f'音色 {args.voice}  语速 {args.rate}  并发 {args.jobs}')

    # 1) 合成
    if args.engine == 'sapi':
        log('\n[1/4] 系统语音合成（离线兜底，用于验证链路）…')
        for i, c in enumerate(cues):
            c['idx'] = i
            src = take / f'{i:03d}_sapi.wav'
            sapi_synth(c['text'], src, rate=args.sapi_rate, voice_kw=args.sapi_voice)
            c['src'] = src
        log(f'   ✓ {len(cues)} 句全部合成')
    elif args.engine == 'qwen':
        log(f'\n[1/4] Qwen3-TTS 本地克隆合成（{args.qwen_model}）…')
        if not args.ref_audio:
            sys.exit('✗ --engine qwen 需要 --ref-audio')
        if not args.qwen_dir:
            sys.exit('✗ --engine qwen 需要 --qwen-dir（tts_qwen 工程根，含 models/），'
                     '或用环境变量 TTS_QWEN_DIR')
        if not Path(args.qwen_dir).is_dir():
            sys.exit(f'✗ --qwen-dir 不存在：{args.qwen_dir}')
        ref_text = args.ref_text
        if not ref_text:
            p = Path(args.ref_audio).with_suffix('.txt')
            if not p.exists():
                sys.exit(f'✗ 缺 --ref-text，且找不到 {p}')
            ref_text = p.read_text(encoding='utf-8').strip()
        args.voice = f"qwen3-tts-{args.qwen_model}-clone:{Path(args.ref_audio).name}"
        for i, c in enumerate(cues):
            c['idx'] = i
            c['src'] = take / f'{i:03d}_qwen.wav'
        qwen_synth_batch(cues, args.ref_audio, ref_text, args.qwen_model,
                         Path(args.qwen_dir), language=args.qwen_language)
        log(f'   ✓ {len(cues)} 句全部合成')
    else:
        log('\n[1/4] edge-tts 合成 …')
        sem = asyncio.Semaphore(args.jobs)

        async def job(i, c):
            c['idx'] = i
            src = take / f'{i:03d}.mp3'
            c['src'] = src
            return await synth_one(c['text'], args.voice, args.rate, src, sem)

        ok = await asyncio.gather(*[job(i, c) for i, c in enumerate(cues)])
        bad = [i for i, v in enumerate(ok) if not v]
        if bad:
            sys.exit(f'✗ {len(bad)} 句合成失败：{bad[:8]}（edge-tts 常见 403，换 --engine sapi 或本地模型）')
        log(f'   ✓ {len(cues)} 句全部合成')

    # 2) 裁静音 + 量时长
    log('\n[2/4] 去首尾静音、量实测时长 …')
    for c in cues:
        c['wav'] = take / f"{c['idx']:03d}.wav"
        to_wav(ffmpeg, c['src'], c['wav'], 1.0)
        c['dur'] = wav_dur(c['wav'])
        c['win'] = c['end'] - c['start']

    # 3) 布局（L2 吞 gap + L3 幕级重排；L1 可选）
    if args.auto_tempo:
        log('\n[3/4] L1 变速：对超出槽位的句子轻度压缩 …')
        for i, c in enumerate(cues):
            slot = (cues[i + 1]['start'] - c['start']) if i + 1 < len(cues) else c['win']
            if c['dur'] > slot * 1.15:
                tempo = min(args.max_tempo, c['dur'] / (slot * 1.05))
                if tempo > 1.02:
                    to_wav(ffmpeg, c['src'], c['wav'], tempo)
                    c['dur'] = wav_dur(c['wav'])
                    c['tempo'] = tempo
    log('\n[4/4] L2 吞并间隙 + L3 幕级重排 …')
    total = layout(cues, acts, args.min_gap, args.tail)

    # 4) 出整轨
    overlaps = build_track(cues, total, outdir / 'voice.wav')

    # 5) 出字幕 / 报告 / 注入段
    srt_lines = []
    for i, c in enumerate(cues, 1):
        srt_lines += [str(i), f"{fmt_srt(c['new_start'])} --> {fmt_srt(c['new_end'])}", c['text'], '']
    (outdir / 'voice_new.srt').write_text('\n'.join(srt_lines), encoding='utf-8')
    tl = write_timeline(args.project, acts, cues, total)

    report = {
        'voice': args.voice, 'rate': args.rate,
        'total_before': round(old_total, 3), 'total_after': round(total, 3),
        'stretch': round(total / old_total, 3),
        'overlaps': overlaps,
        'acts': [{'name': a['name'], 'old': a['dur'], 'new': round(a['new_dur'], 3),
                  'scale': round(a['new_dur'] / a['dur'], 3)} for a in acts],
        'cues': [{'i': c['idx'], 'text': c['text'], 'win': round(c['win'], 3),
                  'tts': round(c['dur'], 3), 'new_start': round(c['new_start'], 3),
                  'overflow': round(c['dur'] - c['win'], 3),
                  'tempo': round(c.get('tempo', 1.0), 4)} for c in cues],
    }
    (outdir / 'align_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    log(f'\n✓ 整轨 {outdir / "voice.wav"}  {total:.1f}s')
    log(f'  总长 {old_total:.1f}s → {total:.1f}s（×{total / old_total:.3f}）')
    for a in acts:
        log(f'  {a["name"]}  {a["dur"]:>5.1f}s → {a["new_dur"]:>6.1f}s  ×{a["new_dur"] / a["dur"]:.3f}')
    over = [c for c in cues if c['win'] and c['dur'] > c['win']]
    log(f'  溢出句 {len(over)}/{len(cues)}，最大溢出 {max((c["dur"] - c["win"] for c in cues), default=0):+.2f}s')
    if overlaps:
        log(f'  ⚠️ 音频重叠句：{overlaps}')
    log(f'  注入段 {tl}')
    if total / old_total > 1.25:
        log(f'  ⚠️ 拉伸超过 25%，画面会明显变慢；可加 --rate +8% 再跑一次')


if __name__ == '__main__':
    asyncio.run(main())
