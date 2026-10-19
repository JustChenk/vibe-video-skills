#!/usr/bin/env node
'use strict';
/* =========================================================
   encode.js —— 帧序列合成 MP4（encode.sh 的跨平台等价物）

   为什么有它：Windows 上没有 bash 时 encode.sh 跑不了，
   实战里每次都要手敲一长串 ffmpeg（还容易漏 -pix_fmt yuv420p / -movflags +faststart）。
   本脚本把 encode.sh 的探测与 fallback 逻辑用 Node 重写一遍，参数一致：
     1) 找 ffmpeg/ffprobe：PATH → 环境变量 HEV_FFMPEG_DIR → 从输出目录向上 4 层找 tools/
     2) 编码器 fallback：libx264 → libopenh264 → libsvtav1 → mpeg4
     3) 合成后自动 ffprobe 校验（时长/帧数/分辨率），并检查编码前帧序列的连续性与 mtime 单簇

   用法：
     node encode.js <frames_dir> <fps> <output.mp4> [bitrate]
     node encode.js ./frames 24 ./my-video.mp4 4.5M
   附加开关：
     --crf 19             libx264 质量（默认 19；暗场风建议 -b:v 8M，用第 4 个参数传码率即可）
     --require-review   编码前要求与 <frames_dir> 同源的 keyframes 签收有效（默认不强制，全量渲染已拦）
     --allow-gaps       允许帧号缺口（默认缺帧直接报错，避免"帧数够但时间轴错位"）
   ========================================================= */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : dflt;
}
const has = n => process.argv.includes(n);

const DIR = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : null;
const FPS = parseFloat(process.argv[3]) || 24;
const OUT = process.argv[4] && !process.argv[4].startsWith('--') ? process.argv[4] : null;
const BR = process.argv[5] && !process.argv[5].startsWith('--') ? process.argv[5] : '4.5M';
const CRF = arg('--crf', '19');
const ALLOW_GAPS = has('--allow-gaps');

if (!DIR || !OUT) {
  console.error('用法: node encode.js <frames_dir> <fps> <output.mp4> [bitrate] [--crf 19] [--allow-gaps]');
  process.exit(1);
}

const isWin = process.platform === 'win32';
const exe = n => (isWin ? `${n}.exe` : n);

/* ---------- ffmpeg / ffprobe 探测 ---------- */
function findTool(name) {
  const tried = [];
  /* 1) PATH */
  try {
    const p = execFileSync(isWin ? 'where' : 'which', [exe(name)], { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().split(/\r?\n/).map(s => s.trim()).filter(Boolean)[0];
    if (p && fs.existsSync(p)) return p;
  } catch (e) { tried.push('PATH'); }
  /* 2) HEV_FFMPEG_DIR */
  if (process.env.HEV_FFMPEG_DIR) {
    const p = path.join(process.env.HEV_FFMPEG_DIR, exe(name));
    if (fs.existsSync(p)) return p;
    tried.push('HEV_FFMPEG_DIR');
  }
  /* 3) 从输出文件目录向上 4 层找 tools/ */
  let probe = path.resolve(path.dirname(path.resolve(OUT)));
  for (let i = 0; i < 4; i++) {
    const p = path.join(probe, 'tools', exe(name));
    if (fs.existsSync(p)) return p;
    const parent = path.dirname(probe);
    if (parent === probe) break;
    probe = parent;
  }
  tried.push('向上 4 层的 tools/');
  console.error(`未找到 ${name}（已尝试：${tried.join(' / ')}）。可设置环境变量 HEV_FFMPEG_DIR 指向 ffmpeg 所在目录。`);
  process.exit(1);
}
const FFMPEG = findTool('ffmpeg');
const FFPROBE = findTool('ffprobe');

/* ---------- 编码前验帧 ---------- */
function checkFrames() {
  const files = fs.readdirSync(DIR).filter(f => /^f\d{5}\.(jpe?g|png)$/i.test(f)).sort();
  if (!files.length) {
    console.error(`✗ ${DIR} 里没有 f00000.jpg 形式的帧，检查渲染是否成功 / 目录是否写错`);
    process.exit(1);
  }
  const nums = files.map(f => parseInt(f.slice(1, 6), 10));
  const first = nums[0], last = nums[nums.length - 1];
  const gaps = [];
  for (let i = 1; i < nums.length; i++) if (nums[i] !== nums[i - 1] + 1) gaps.push(`${nums[i - 1]}→${nums[i]}`);
  if (first !== 0) gaps.unshift(`缺开头 f00000（从 f${String(first).padStart(5, '0')} 开始）`);
  /* mtime 单簇：整批帧应该是一次渲染出来的，跨天的旧帧混进来会造成幕序错乱 */
  const times = files.map(f => fs.statSync(path.join(DIR, f)).mtimeMs).sort((a, b) => a - b);
  const spanMin = (times[times.length - 1] - times[0]) / 60000;
  console.log(`帧序列：${files.length} 张（f${String(first).padStart(5, '0')}–f${String(last).padStart(5, '0')}），` +
    `mtime 跨度 ${spanMin.toFixed(1)} 分钟`);
  if (gaps.length && !ALLOW_GAPS) {
    console.error(`✗ 帧号不连续（${gaps.slice(0, 5).join(', ')}${gaps.length > 5 ? ' …' : ''}）。` +
      `\n  缺帧会让后续帧整体提前，成片音画/幕序错位。补渲或用 --allow-gaps 明确接受。`);
    process.exit(1);
  }
  if (spanMin > 180) {
    console.warn(`⚠️  帧的 mtime 跨度 ${spanMin.toFixed(0)} 分钟，像是多次渲染拼起来的。` +
      `\n   确认不是"改了场景只补渲某段、旧段还留着旧版式"（2026-10-19 踩过）。`);
  }
  return { count: files.length, first, last, expected: last - first + 1 };
}

/* ---------- 编码器 fallback ---------- */
function pickEncoder() {
  let enc = '';
  try {
    enc = execFileSync(FFMPEG, ['-hide_banner', '-encoders'], { stdio: ['ignore', 'pipe', 'pipe'] }).toString();
  } catch (e) { /* 老版本 ffmpeg 可能报错，退回默认 */ }
  if (/libx264/.test(enc)) return { name: 'libx264', args: ['-c:v', 'libx264', '-preset', 'slow', '-crf', CRF] };
  if (/libopenh264/.test(enc)) return { name: 'libopenh264', args: ['-c:v', 'libopenh264', '-b:v', BR, '-profile:v', 'high'] };
  if (/libsvtav1/.test(enc)) return { name: 'libsvtav1', args: ['-c:v', 'libsvtav1', '-b:v', BR] };
  return { name: 'mpeg4', args: ['-c:v', 'mpeg4', '-q:v', '3'] };
}

/* ---------- 主流程 ---------- */
const info = checkFrames();
const enc = pickEncoder();
console.log(`ffmpeg: ${FFMPEG}\n编码器: ${enc.name}${enc.name === 'libx264' ? ` (crf ${CRF})` : ` (${BR})`}`);

const dst = path.resolve(OUT);
fs.mkdirSync(path.dirname(dst), { recursive: true });
if (fs.existsSync(dst)) {
  try { fs.unlinkSync(dst); } catch (e) {
    console.error(`✗ 目标文件被占用（多半是播放器还开着）：${dst}\n  关掉播放器后重跑。`);
    process.exit(1);
  }
}
const tmpOut = dst.replace(/\.mp4$/i, '') + '.tmp.mp4';
const cmd = [
  '-hide_banner', '-loglevel', 'error', '-y',
  '-framerate', String(FPS),
  '-i', path.join(path.resolve(DIR), 'f%05d.jpg'),
  ...enc.args,
  '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
  tmpOut,
];
const t0 = Date.now();
try {
  execFileSync(FFMPEG, cmd, { stdio: 'inherit' });
} catch (e) {
  console.error('✗ 编码失败：', e.message);
  process.exit(1);
}
fs.renameSync(tmpOut, dst);

/* ---------- 产物校验 ---------- */
const probe = JSON.parse(execFileSync(FFPROBE, [
  '-v', 'error', '-show_streams', '-show_format', '-of', 'json', dst,
]).toString());
const v = (probe.streams || []).find(s => s.codec_type === 'video') || {};
const audio = (probe.streams || []).filter(s => s.codec_type === 'audio');
const dur = parseFloat(probe.format && probe.format.duration) || 0;
const nb = parseInt(v.nb_frames, 10) || Math.round(dur * parseFloat(v.r_frame_rate || FPS));
const expect = info.count;
const L = [];
L.push(`✓ 成片 ${path.basename(dst)}`);
L.push(`  时长 ${dur.toFixed(3)}s / ${nb} 帧（期望 ${expect}）/ ${v.width}x${v.height} / ${v.codec_name} ${v.pix_fmt}`);
L.push(`  大小 ${(parseFloat(probe.format.size) / 1048576).toFixed(1)} MB / 编码耗时 ${((Date.now() - t0) / 1000).toFixed(0)}s`);
L.push(`  音轨 ${audio.length ? audio.map(a => a.codec_name).join(',') : '无（成片默认无音轨，配乐走 merge_audio.sh）'}`);
console.log(L.join('\n'));

let bad = 0;
if (Math.abs(nb - expect) > 1) { console.error(`✗ 帧数不符：成片 ${nb}，帧序列 ${expect}`); bad++; }
if (v.pix_fmt && v.pix_fmt !== 'yuv420p') { console.error(`✗ 像素格式 ${v.pix_fmt} ≠ yuv420p（很多播放器/平台要求 yuv420p）`); bad++; }
if (audio.length) { console.warn('⚠️  成片带了音轨；如果这是无声片，说明帧目录或参数串了。'); }
if (bad) process.exit(1);
console.log('编码完成。下一步：抽帧复核（node grab.js <成片> <秒>...），确认画面与审查帧一致。');
