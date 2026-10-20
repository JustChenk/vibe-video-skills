#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_dub_video.py —— 帧序列 + 配音轨 → 配音成片（通用）

配音版视频的最后一步：把逐帧序列和 tts_voiceover.py 产出的 voice.wav 合成 MP4。

用法:
    python build_dub_video.py <frames_dir> <voice.wav> <out.mp4> [--fps 24] [--crf 19]

例:
    python build_dub_video.py ./frames_voice ./voicework/voice.wav ./pkg_配音版.mp4
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_tool(name, explicit=None):
    """定位 ffmpeg/ffprobe：显式参数 > 环境变量 > 同级 tools/ > PATH。"""
    cands = []
    if explicit:
        cands.append(Path(explicit))
    env = os.environ.get(name.upper())
    if env:
        cands.append(Path(env))
    here = Path(__file__).resolve().parent
    exe = f'{name}.exe' if sys.platform == 'win32' else name
    cands += [here.parent / 'tools' / exe, here / 'tools' / exe,
              Path.cwd() / 'tools' / exe]
    for c in cands:
        if c.exists():
            return str(c)
    found = shutil.which(name)
    return found or name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames_dir', help='帧目录，文件名须为 f%%05d.jpg')
    ap.add_argument('voice', help='配音轨 voice.wav（tts_voiceover.py 产出）')
    ap.add_argument('out', help='输出 mp4')
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--crf', type=int, default=19)
    ap.add_argument('--audio-bitrate', default='192k')
    ap.add_argument('--ffmpeg', default=None)
    ap.add_argument('--ffprobe', default=None)
    args = ap.parse_args()

    frames = Path(args.frames_dir)
    voice = Path(args.voice)
    out = Path(args.out)
    if not frames.is_dir():
        sys.exit(f'✗ 帧目录不存在：{frames}')
    if not voice.exists():
        sys.exit(f'✗ 配音轨不存在：{voice}')

    ffmpeg = find_tool('ffmpeg', args.ffmpeg)
    ffprobe = find_tool('ffprobe', args.ffprobe)

    n = len([f for f in os.listdir(frames) if f.endswith('.jpg')])
    if n == 0:
        sys.exit('✗ 帧目录里没有 jpg')
    print(f'帧数 {n}  →  {n / args.fps:.3f}s @ {args.fps}fps')

    out.parent.mkdir(parents=True, exist_ok=True)
    target = out
    if target.exists():
        try:
            target.unlink()
        except PermissionError:
            # 常见于成片正被播放器打开
            print(f'⚠ {target} 被占用，改写 {target.name}.new')
            target = out.with_suffix(out.suffix + '.new')

    cmd = [
        ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
        '-framerate', str(args.fps), '-i', str(frames / 'f%05d.jpg'),
        '-i', str(voice),
        '-map', '0:v:0', '-map', '1:a:0',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', str(args.crf),
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', args.audio_bitrate, '-ar', '44100', '-ac', '1',
        '-shortest', '-movflags', '+faststart',
        str(target),
    ]
    if subprocess.run(cmd).returncode != 0:
        sys.exit('✗ 编码失败')

    info = subprocess.run(
        [ffprobe, '-v', 'error',
         '-show_entries', 'stream=codec_type,codec_name,nb_frames,r_frame_rate,sample_rate,channels',
         '-show_entries', 'format=duration,size', '-of', 'json', str(target)],
        capture_output=True, text=True).stdout
    j = json.loads(info)
    print(f'OK {target.name}')
    for s in j['streams']:
        print('  ', {k: v for k, v in s.items()
                     if k in ('codec_type', 'codec_name', 'nb_frames',
                              'r_frame_rate', 'sample_rate', 'channels')})
    print('  ', {k: j['format'][k] for k in ('duration', 'size')})


if __name__ == '__main__':
    main()
