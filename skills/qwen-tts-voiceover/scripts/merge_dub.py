"""merge_dub.py —— 把克隆配音音轨并进无声母版，产出配音版 mp4（路线 B 并轨）。

口径（2026-10-22 用户确认）：
  - 视频时间轴不动；配音按 SRT 槽位/空档自然走（fit-next，见 synthesize_srt_fitnext.py）
  - 只有**真实语音**超出片尾才延长视频（tpad 克隆末帧，静态帧延长零成本）；
    音轨自带的 0.3s 静音垫尾不算溢出——用 --voice-end 传 manifest 的 voice_end_sec 判断
  - 音频规格与 REA 配音版一致：aac 192k / 44.1k / 单声道
  - 原无声母版永不改动，输出新文件

用法：
  python merge_dub.py <无声母版.mp4> <voice.wav> <输出_配音版.mp4> [--voice-end 164.6] [--vb 4.5M]

ffmpeg/ffprobe 默认取 PATH，可用 VIBE_FFMPEG / VIBE_FFPROBE 环境变量覆盖。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

FFMPEG = Path(os.environ.get("VIBE_FFMPEG", "ffmpeg"))
FFPROBE = Path(os.environ.get("VIBE_FFPROBE", "ffprobe"))


def probe_duration(p: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def wav_duration(p: Path) -> float:
    import soundfile as sf
    info = sf.info(str(p))
    return info.frames / info.samplerate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("voice")
    ap.add_argument("out")
    ap.add_argument("--vb", default="4.5M", help="延长视频重编码时的视频码率（与 encode.sh 一致）")
    ap.add_argument("--voice-end", type=float, default=None,
                    help="真实语音结束点（manifest 的 voice_end_sec）。不给则用音轨全长"
                         "（含 0.3s 静音垫尾，会把片尾误判为需延长）")
    args = ap.parse_args()

    video, voice, out = Path(args.video), Path(args.voice), Path(args.out)
    if out.exists():
        sys.exit(f"输出已存在，先删再跑（防覆盖）：{out}")
    v_dur = probe_duration(video)
    a_dur = wav_duration(voice)
    speech_end = args.voice_end if args.voice_end is not None else a_dur
    # 只有真实语音冲出片尾才延长视频；音轨自带的 0.3s 静音垫尾不算
    extend = speech_end - v_dur
    final_dur = max(v_dur, speech_end)

    cmd = [str(FFMPEG), "-y", "-v", "error", "-i", str(video), "-i", str(voice),
           "-map", "0:v:0", "-map", "1:a:0"]
    if extend > 0.05:
        # 配音冲出片尾：克隆末帧延长视频（重编码，仅此分支）
        print(f"[extend] 配音超出片尾 {extend:.2f}s → tpad 克隆末帧延长，视频重编码")
        cmd += ["-vf", f"tpad=stop_mode=clone:stop_duration={extend + 0.2:.3f}",
                "-c:v", "libx264", "-b:v", args.vb, "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-af", "apad", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "1",
            "-t", f"{final_dur:.3f}", str(out)]
    print("[cmd]", " ".join(cmd))
    subprocess.run(cmd, check=True)

    got = probe_duration(out)
    print(f"[done] {out}")
    print(f"       母版 {v_dur:.2f}s + 配音 {a_dur:.2f}s → 成片 {got:.2f}s")
    if abs(got - final_dur) > 0.15:
        sys.exit(f"时长异常：期望 {final_dur:.2f}s 实得 {got:.2f}s")


if __name__ == "__main__":
    main()
