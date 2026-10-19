#!/usr/bin/env node
'use strict';
/* =========================================================
   grab.js —— 从成片按秒精确抽帧，用于"成片复核"

   为什么要单独一个脚本：
     · PowerShell 里写 ffmpeg ... "$T\vid_$t.jpg" 会被解析成 "{T}\vid_" + "$t.jpg"
       （路径里混变量 → 抽出来是 "路径\97\..." 这种鬼目录）；
     · ffmpeg 的 -ss 放在 -i 前面是快速粗定位、后面才是逐帧精确，容易被写反；
     · 抽完不看，等于没抽 —— 这里顺手把关键指标（帧大小、非底色占比）打出来。

   用法：
     node grab.js <video.mp4> <秒> [秒...]
     node grab.js ./out.mp4 3.2 58 130          # 输出到成片同目录 grab_3_2s.jpg ...
     node grab.js ./out.mp4 --all 172           # 每 5s 抽一张，快速扫全片
     node grab.js ./out.mp4 --acts            # 按 video.html 的幕中段各抽一张（需指定 html）
   参数：
     --out-dir <dir>   输出目录（默认成片同目录下的 grab/）
     --html <video.html>  配合 --acts 用，读 SCENES/TIMELINE 后每幕中段抽 1 张
     --step 5          配合 --all 的间隔秒
   ========================================================= */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : dflt;
}
const has = n => process.argv.includes(n);
const isWin = process.platform === 'win32';
const exe = n => (isWin ? `${n}.exe` : n);

const MP4 = process.argv[2];
if (!MP4 || !fs.existsSync(MP4)) {
  console.error('用法: node grab.js <video.mp4> <秒> [秒...] [--all <总时长>] [--acts --html video.html] [--out-dir grab]');
  process.exit(1);
}
const OUT_DIR = path.resolve(arg('--out-dir', path.join(path.dirname(path.resolve(MP4)), 'grab')));
const HTML = arg('--html', null);
const STEP = parseFloat(arg('--step', '5'));

/* ---------- ffmpeg 探测（与 encode.js 同规则） ---------- */
function findTool(name) {
  try {
    const p = execFileSync(isWin ? 'where' : 'which', [exe(name)], { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().split(/\r?\n/).map(s => s.trim()).filter(Boolean)[0];
    if (p && fs.existsSync(p)) return p;
  } catch (e) { /* next */ }
  if (process.env.HEV_FFMPEG_DIR) {
    const p = path.join(process.env.HEV_FFMPEG_DIR, exe(name));
    if (fs.existsSync(p)) return p;
  }
  let probe = path.dirname(path.resolve(MP4));
  for (let i = 0; i < 4; i++) {
    const p = path.join(probe, 'tools', exe(name));
    if (fs.existsSync(p)) return p;
    const parent = path.dirname(probe);
    if (parent === probe) break;
    probe = parent;
  }
  console.error(`未找到 ${name}：设 HEV_FFMPEG_DIR，或把 ffmpeg 放进 <项目根>/tools/`);
  process.exit(1);
}
const FFMPEG = findTool('ffmpeg');
const FFPROBE = findTool('ffprobe');

/* ---------- 时间点 ---------- */
let times = [];
for (let i = 3; i < process.argv.length; i++) {
  const a = process.argv[i];
  if (a.startsWith('--') || a.startsWith('-')) break;
  const n = parseFloat(a);
  if (Number.isFinite(n)) times.push(n);
}
if (has('--all')) {
  const dur = parseFloat(arg('--all', '0')) ||
    parseFloat(JSON.parse(execFileSync(FFPROBE, ['-v', 'error', '-show_format', '-of', 'json', MP4]).toString()).format.duration);
  times = [];
  for (let t = STEP; t < dur - 0.2; t += STEP) times.push(+t.toFixed(2));
}
if (has('--acts')) {
  if (!HTML) { console.error('--acts 需要配合 --html <video.html>'); process.exit(1); }
  const html = fs.readFileSync(HTML, 'utf8');
  const dir = path.dirname(path.resolve(HTML));
  const srcs = [...html.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)].map(m => path.resolve(dir, m[1]));
  times = [];
  for (const f of srcs) {
    if (!fs.existsSync(f)) continue;
    const src = fs.readFileSync(f, 'utf8');
    const sb = src.match(/const\s+SCENES\s*=\s*\[([\s\S]*?)\];/);
    if (sb) for (const m of sb[1].matchAll(/start:\s*([\d.]+)\s*,\s*dur:\s*([\d.]+)/g)) {
      times.push(+(parseFloat(m[1]) + parseFloat(m[2]) * 0.6).toFixed(2));
    }
    const tb = src.match(/(?:const|let|var)\s+TIMELINE\s*=\s*\[([\s\S]*?)\];/);
    if (tb) {
      let acc = 0;
      for (const m of tb[1].matchAll(/len:\s*([\d.]+)/g)) {
        const len = parseFloat(m[1]);
        times.push(+(acc + len * 0.6).toFixed(2));
        acc += len;
      }
    }
  }
}
if (!times.length) { console.error('没有要抽的时间点。例：node grab.js ./out.mp4 3.2 58 130'); process.exit(1); }

fs.mkdirSync(OUT_DIR, { recursive: true });
console.log(`抽帧 ${times.length} 个 → ${OUT_DIR}`);
for (const t of times) {
  const out = path.join(OUT_DIR, `grab_${String(t).replace('.', '_')}s.jpg`);
  try {
    execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-i', MP4, '-ss', String(t),
      '-frames:v', '1', '-q:v', '2', out], { stdio: ['ignore', 'pipe', 'pipe'] });
    if (!fs.existsSync(out)) throw new Error('ffmpeg 没有产出文件（该时间点超出成片时长？）');
    const kb = (fs.statSync(out).size / 1024).toFixed(0);
    console.log(`  ${String(t).padEnd(7)} → ${path.basename(out)}  ${kb} KB${kb < 25 ? '   ← 偏小，可能是纯色/空白帧' : ''}`);
  } catch (e) {
    const msg = (e.stderr && e.stderr.toString().trim().split('\n').pop()) || e.message.split('\n')[0];
    console.error(`  ${t}s 抽帧失败：${msg}`);
  }
}
console.log('\n逐张 Read 这些图，和 keyframes/ 的审查帧比对：成片画面必须与审查帧一致（含双版本工程）。');
