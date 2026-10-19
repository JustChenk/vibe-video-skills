#!/usr/bin/env node
'use strict';
/* =========================================================
   keyframes.js —— 关键帧「视觉审查」流水线（全量渲染前的硬门禁）

   为什么需要它（2026-10-19《AI 逆向一切》两次返工的教训）：
     静态检查（precheck.js）只能证明"代码没写错"，证明不了"画面对"。
     红圈画到画面外、箭头端点啃进卡片、两个数字挤在一起、字幕压住标题……
     这些只有把帧当图片看一遍才发现，而"拿几个拍脑袋的时间点抽两张"
     恰好会漏掉出事的那一幕。等到全量渲染 + 合成 + 人类看片才发现，
     就要重渲 + 重编 + 两版一起返工。

   它做三件事：
     1) 自动选点：按幕边界 / SRT 字幕条自动生成审查点（不用手挑时间点），
        每幕至少 3 个（入场后 / 中段 / 收尾前），保证"每一幕都被看过"。
     2) 出图 + 机械体检：渲染成 kf_<秒>s.jpg，并生成一张联系表
        (_联系表.jpg) 供一次 Read 看全片；同时用像素统计拦下
        空白幕 / 满屏 / 越界压边 / 压进度条 / 渲染不确定（同 t 两次不一致）。
     3) 签收与校验：人（Agent）逐张看完后 --approve 签收，签收记录里带
        工程指纹；工程任何 js/html 改动 → 指纹变 → 旧签收自动作废。
        render.js 全量渲染前会调 --verify，没有有效签收直接拒绝渲染。

   用法：
     node keyframes.js ./video.html ./keyframes                 # 生成审查帧 + 联系表 + 审查表
     node keyframes.js ./video.html ./keyframes --srt xxx.srt    # 额外按字幕时间点补帧
     node keyframes.js ./video.html ./keyframes --approve "已逐张看过"   # 审完签收
     node keyframes.js ./video.html ./keyframes --verify         # 只校验（退出码 1 = 没审/已过期）
   常用参数：
     --fps 24            帧率（默认读 window.__meta.fps，再不行 24）
     --dur 172           总时长（默认读 __meta.duration / SCENES / TIMELINE）
     --offsets .2,.55,.9 每幕取点位置（相对幕长），默认 .2,.55,.9
     --points "3,18,40"  额外指定时间点（与幕内取点合并）
     --srt file.srt      按字幕时间点补帧（每条字幕入场后 0.6s）
     --srt-per-act 2     每幕最多补几条字幕帧（默认 2）
     --no-contact        不生成联系表
     --strict            有机械 WARN 也拒绝签收
     --json              末尾输出一段机器可读结果
   退出码：0 = 通过；1 = 失败/未签收/签收过期
   ========================================================= */
const fs = require('fs');
const path = require('path');
const { launch, openPage, projectFingerprint, detectDuration } = require('./_browser.js');

/* ---------------- 参数 ---------------- */
function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : dflt;
}
const has = name => process.argv.includes(name);

const HTML = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : null;
const OUT = (process.argv[3] && !process.argv[3].startsWith('--') ? process.argv[3] : null) || './keyframes';
const APPROVE = arg('--approve', null);
const VERIFY = has('--verify');
const STRICT = has('--strict');
const JSONOUT = has('--json');
const NO_CONTACT = has('--no-contact');
const SRT = arg('--srt', null);
const EXTRA_POINTS = arg('--points', null);
const OFFSETS = arg('--offsets', '0.2,0.55,0.9').split(',').map(Number).filter(n => n >= 0 && n <= 1);
const SRT_PER_ACT = parseInt(arg('--srt-per-act', '2'), 10);
const QUALITY = parseInt(arg('--quality', '92'), 10);

const die = (msg) => { console.error(msg); process.exit(1); };

/* 签收路径与校验逻辑放在 _review.js，render.js 复用同一份约定 */
const { reviewPaths, verifyReview } = require('./_review.js');

/* ---------------- 幕边界：优先问页面要，其次静态解析 ---------------- */
async function readTimeline(page, htmlPath, durOverride) {
  const meta = await page.evaluate(() => {
    const m = window.__meta || {};
    const out = { fps: m.fps || null, duration: m.duration || null, acts: [], mode: '' };

    if (typeof SCENES !== 'undefined' && Array.isArray(SCENES)) {
      out.mode = 'SCENES';
      out.acts = SCENES.map((s, i) => ({
        name: s.name || `S${i + 1}`,
        start: Number(s.start) || 0,
        dur: Number(s.dur) || 0,
      }));
    } else if (typeof TIMELINE !== 'undefined' && Array.isArray(TIMELINE)) {
      out.mode = 'TIMELINE';
      let acc = 0;
      out.acts = TIMELINE.map((s, i) => {
        const act = { name: s.id || `S${i + 1}`, start: acc, dur: Number(s.len) || 0 };
        acc += act.dur;
        return act;
      });
      out.duration = out.duration || acc;
    }
    return out;
  });

  const fps = parseInt(arg('--fps', String(meta.fps || 24)), 10) || 24;
  let duration = parseFloat(arg('--dur', '0')) || meta.duration || 0;
  if (!duration) duration = detectDuration(htmlPath) || 0;
  if (!duration) die('读不到总时长：请显式传 --dur <秒>（工程里既没有 SCENES/TIMELINE，也没有 window.__meta.duration）');

  let acts = (meta.acts || []).filter(a => a.dur > 0);
  if (!acts.length) acts = [{ name: 'ALL', start: 0, dur: duration }];
  return { fps, duration, acts, mode: meta.mode || 'fallback' };
}

/* ---------------- SRT 解析 ---------------- */
function parseSRT(file) {
  const txt = fs.readFileSync(file, 'utf8').replace(/\r/g, '');
  const out = [];
  const re = /(\d\d):(\d\d):(\d\d)[,.](\d{3})\s*-->\s*(\d\d):(\d\d):(\d\d)[,.](\d{3})/g;
  let m;
  while ((m = re.exec(txt))) {
    const s = (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]) + (+m[4]) / 1000;
    out.push({ start: s });
  }
  return out;
}

/* ---------------- 选点 ---------------- */
function planPoints(acts, duration, srtCues) {
  const picks = [];
  const add = (t, why) => {
    if (!(t > 0.15) || t >= duration - 0.05) return;
    const dup = picks.find(p => Math.abs(p.t - t) < 0.2);
    if (dup) { if (!dup.why.includes(why)) dup.why += ' / ' + why; return; }
    picks.push({ t: Math.round(t * 100) / 100, why });
  };

  /* 每幕按相对位置取点：保证"每一幕的入场 / 中段 / 收尾"都被看过 */
  let actNo = 0;
  for (const a of acts) {
    actNo++;
    for (const off of OFFSETS) {
      add(a.start + a.dur * off, `${a.name}@${Math.round(off * 100)}%`);
    }
    /* 幕末 0.35s 常是 wipe 转场，单独取一张容易误判"画面空白"，故不取 t=dur-0.1 */
  }

  /* 字幕：每幕最多 SRT_PER_ACT 条，取"字幕入场后 0.6s"，专验字幕条位置与换行 */
  if (srtCues && srtCues.length) {
    for (const a of acts) {
      const inAct = srtCues.filter(c => c.start >= a.start && c.start < a.start + a.dur);
      if (!inAct.length) continue;
      const step = Math.max(1, Math.floor(inAct.length / SRT_PER_ACT));
      for (let i = 0; i < inAct.length && i / step < SRT_PER_ACT; i += step) {
        add(inAct[i].start + 0.6, `${a.name}·字幕`);
      }
    }
  }

  if (EXTRA_POINTS) {
    for (const raw of EXTRA_POINTS.split(',')) {
      const t = parseFloat(raw);
      if (Number.isFinite(t)) add(t, '手动指定');
    }
  }

  picks.sort((x, y) => x.t - y.t);
  return picks;
}

/* ---------------- 像素体检（在页面里解码截图，零额外依赖） ----------------
   背景色不是纯色：手绘风有纸纹点阵 + 径向渐晕，暗场风有网格与颗粒。
   所以先取画布四边 2px 的一圈像素估计"底色"，再按相对亮度差算"非底色占比"，
   并且只把**连成片的**非底色像素计为墨迹（纸纹这种孤立噪点按 3x3 邻域投票滤掉）。 */
async function analyze(page, dataUrl, colors) {
  return page.evaluate(async ({ dataUrl, fallbackBg }) => {
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = dataUrl; });
    const W = img.naturalWidth, H = img.naturalHeight;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const c = cv.getContext('2d');
    c.drawImage(img, 0, 0);
    const px = c.getImageData(0, 0, W, H).data;

    const lumAt = (x, y) => {
      const i = (y * W + x) * 4;
      return 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    };

    /* 1) 底色估计：四边一圈的亮度中位数 */
    const samples = [];
    for (let x = 0; x < W; x += 2) { samples.push(lumAt(x, 1)); samples.push(lumAt(x, H - 2)); }
    for (let y = 0; y < H; y += 2) { samples.push(lumAt(1, y)); samples.push(lumAt(W - 2, y)); }
    samples.sort((a, b) => a - b);
    const bgLum = samples[Math.floor(samples.length / 2)] || 244;

    /* 2) 逐点判定：与底色亮度差 > 阈值 记为"有内容"；用 3x3 邻域投票去孤立噪点 */
    const STEP = 2, TH = 34;                    /* 34/255 ≈ 13% 亮度差 */
    const cols = Math.floor(W / STEP), rows = Math.floor(H / STEP);
    const mask = new Uint8Array(cols * rows);
    for (let gy = 0; gy < rows; gy++) {
      for (let gx = 0; gx < cols; gx++) {
        mask[gy * cols + gx] = Math.abs(lumAt(gx * STEP, gy * STEP) - bgLum) > TH ? 1 : 0;
      }
    }
    const solid = new Uint8Array(cols * rows);
    let inkCnt = 0;
    for (let gy = 0; gy < rows; gy++) {
      for (let gx = 0; gx < cols; gx++) {
        if (!mask[gy * cols + gx]) continue;
        let n = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const x2 = gx + dx, y2 = gy + dy;
          if (x2 < 0 || y2 < 0 || x2 >= cols || y2 >= rows) continue;
          n += mask[y2 * cols + x2];
        }
        if (n >= 4) { solid[gy * cols + gx] = 1; inkCnt++; }
      }
    }
    const total = cols * rows;

    /* 3) 分区统计：贴边 / 左右安全区外 / 底部进度条带 */
    const marginPx = Math.round(8 / STEP), safeX = Math.round(W * 0.042 / STEP);
    const yP0 = Math.round(H * 0.93 / STEP), yP1 = Math.round(H * 0.98 / STEP);
    let border = 0, borderAll = 0, leftEdge = 0, rightEdge = 0, bottomBand = 0, bottomAll = 0;
    for (let gy = 0; gy < rows; gy++) {
      for (let gx = 0; gx < cols; gx++) {
        const on = solid[gy * cols + gx];
        const inBorder = gx < marginPx || gx >= cols - marginPx || gy < marginPx || gy >= rows - marginPx;
        if (inBorder) { borderAll++; if (on) border++; }
        if (on && gx < safeX) leftEdge++;
        if (on && gx >= cols - safeX) rightEdge++;
        if (gy >= yP0 && gy < yP1) { bottomAll++; if (on) bottomBand++; }
      }
    }
    return {
      w: W, h: H,
      bgLum: +bgLum.toFixed(1),
      ink: +(inkCnt / total).toFixed(4),
      border: +(border / Math.max(1, borderAll)).toFixed(4),
      leftEdge: +(leftEdge / total).toFixed(4),
      rightEdge: +(rightEdge / total).toFixed(4),
      bottomBand: +(bottomBand / Math.max(1, bottomAll)).toFixed(3),
      fallbackBgUsed: !bgLum && fallbackBg,
    };
  }, { dataUrl, fallbackBg: colors.bg });
}

/* 判据是"相对占位"，不是美术标准：只用来拦空白幕、越界、压条这类硬伤。
   实测（1920x1080，手绘纸面/暗场两类）：常规内容幕 3%~14%，金句幕单行 1%~2%，
   空幕 <0.7%。所以空白判定取 0.6% ERROR，1~2% 只给 WARN（可能是一行字的转场瞬间）。 */
function judge(stats) {
  const pct = v => (v * 100).toFixed(1) + '%';
  const issues = [];
  if (stats.ink < 0.006) issues.push({ level: 'ERROR', msg: `画面几乎全空（非底色仅 ${pct(stats.ink)}）→ 该幕没渲染出内容 / 时间基准错` });
  else if (stats.ink < 0.02) issues.push({ level: 'WARN', msg: `画面很空（非底色 ${pct(stats.ink)}）→ 确认这是"只露一行字"的设计，而不是元素没出现` });
  if (stats.ink > 0.55) issues.push({ level: 'WARN', msg: `画面被填满（非底色 ${pct(stats.ink)}）→ 检查是否叠字、元素越界` });
  if (stats.border > 0.004 && stats.ink > 0.02) {
    issues.push({ level: 'WARN', msg: `画面最外 8px 有内容（${pct(stats.border)}）→ 元素出界或被裁切` });
  }
  if (stats.leftEdge > 0.002 || stats.rightEdge > 0.002) {
    issues.push({ level: 'WARN', msg: `左右安全区(4.2%)外有内容（左 ${pct(stats.leftEdge)} / 右 ${pct(stats.rightEdge)}）→ 可能被切边` });
  }
  if (stats.bottomBand > 0.40) issues.push({ level: 'WARN', msg: `底部进度条一带内容占 ${pct(stats.bottomBand)} → 检查是否压到进度条` });
  return issues;
}

/* ---------------- 联系表（一张图看全片） ---------------- */
async function makeContactSheet(browser, shots, outFile, W = 1920) {
  const COLS = 4, CW = 480, CH = 270, LABEL = 34;
  const rows = Math.ceil(shots.length / COLS);
  const H = rows * (CH + LABEL);
  const page = await browser.newPage({ viewport: { width: W, height: Math.min(H, 4000) }, deviceScaleFactor: 1 });
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:#1b1712}canvas{display:block}</style><canvas id="c" width="${W}" height="${H}"></canvas>`);
  await page.evaluate(async ({ shots, COLS, CW, CH, LABEL, H }) => {
    const c = document.getElementById('c').getContext('2d');
    c.fillStyle = '#1b1712'; c.fillRect(0, 0, c.canvas.width, H);
    for (let i = 0; i < shots.length; i++) {
      const s = shots[i];
      const col = i % COLS, row = Math.floor(i / COLS);
      const x = col * CW, y = row * (CH + LABEL);
      const img = new Image();
      await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = s.dataUrl; });
      c.drawImage(img, x, y, CW, CH);
      c.fillStyle = s.error ? '#7a1f14' : '#2a241d';
      c.fillRect(x, y + CH, CW, LABEL);
      c.fillStyle = s.error ? '#ffd9d0' : '#f3e6c8';
      c.font = 'bold 17px "Segoe UI", "Microsoft YaHei", sans-serif';
      c.textAlign = 'left'; c.textBaseline = 'middle';
      c.fillText(`${s.t.toFixed(1)}s  ${s.why}`, x + 8, y + CH + LABEL / 2 + 1);
    }
  }, { shots, COLS, CW, CH, LABEL, H });
  const el = await page.$('#c');
  await el.screenshot({ path: outFile, type: 'jpeg', quality: 88 });
  await page.close();
}

/* ---------------- 审查表（人看的 markdown） ---------------- */
function writeManifest(file, ctx) {
  const { html, finger, fps, duration, mode, rows, warns, contact, outDir } = ctx;
  const rel = p => path.relative(path.dirname(file), p).replace(/\\/g, '/');
  const L = [];
  L.push(`# 关键帧审查表 · ${path.basename(html)}`);
  L.push('');
  L.push(`> 工程指纹 \`${finger.hash}\` ｜ ${duration.toFixed(1)}s / ${fps}fps / ${rows.length} 帧 / 幕边界来源：${mode}`);
  L.push(`> 生成时间：${new Date().toLocaleString('zh-CN')}`);
  L.push('');
  L.push('## 这轮要看什么（逐张 Read，不许跳）');
  L.push('');
  L.push('1. **每个数字都能说出含义**——画面上了无来源的数字（seed、坐标、字号）＝参数错位。');
  L.push('2. **每个该有文字的元素真的有字**——徽章、价签、卡片、贴纸逐个确认，文字消失比多出数字更难发现。');
  L.push('3. **元素不越界、不互相压字**——尤其红圈 / 箭头 / 大字标题 / 底部字幕。');
  L.push('4. **局部坐标写错的典型症状**：元素"飞到画面角落 / 右下方"，与它该标注的卡片完全分离。');
  L.push('5. 错别字、数据与调研材料一致、每幕都有内容、幕间转场不穿帮。');
  L.push('');
  if (contact) {
    L.push('## 联系表（先看这一张，再逐张放大）');
    L.push('');
    L.push(`![联系表](${rel(contact)})`);
    L.push('');
  }
  L.push('## 逐帧清单');
  L.push('');
  L.push('| # | 时间 | 取点原因 | 机械体检 | 看图结论 |');
  L.push('|---|---|---|---|---|');
  rows.forEach((r, i) => {
    const iss = r.issues.length
      ? r.issues.map(x => `${x.level === 'ERROR' ? '❌' : '⚠️'} ${x.msg}`).join('<br>')
      : `墨迹 ${(r.stats.ink * 100).toFixed(1)}%`;
    L.push(`| ${i + 1} | [${r.t.toFixed(1)}s](${rel(r.file)}) | ${r.why} | ${iss} | ☐ |`);
  });
  L.push('');
  if (warns.length) {
    L.push('## 机械体检汇总（脚本能发现的，先修这些）');
    L.push('');
    for (const w of warns) L.push(`- **${w.t.toFixed(1)}s** ${w.level === 'ERROR' ? '❌ ERROR' : '⚠️ WARN'}：${w.msg}`);
    L.push('');
  } else {
    L.push('## 机械体检汇总');
    L.push('');
    L.push('- 无：没有空白幕、没有贴边溢墨、没有压进度条。**这不代表画面没问题**，仍要逐张看图。');
    L.push('');
  }
  L.push('## 签收');
  L.push('');
  L.push('逐张看完、改完、**重新出帧**之后再签收（签收会把当前工程指纹写死）：');
  L.push('');
  L.push('```bash');
  L.push(`node <skill>/scripts/keyframes.js ./${path.basename(html)} ${path.relative(path.dirname(html), outDir).replace(/\\/g, '/') || '.'} --approve "逐张看过，无错位"`);
  L.push('```');
  L.push('');
  L.push('签收之后只要再改任何 js/html，指纹就变了，签收自动作废，`render.js` 会拒绝全量渲染。');
  L.push('');
  fs.writeFileSync(file, L.join('\n'), 'utf8');
}

/* =========================================================
   main
   ========================================================= */
(async () => {
  if (!HTML) die('用法: node keyframes.js <video.html> [outdir] [--srt x.srt] [--approve "说明"] [--verify]');
  if (!fs.existsSync(HTML)) die(`找不到工程文件：${HTML}`);

  const paths = reviewPaths(HTML, OUT);

  /* --verify：只校验，不开浏览器（快） */
  if (VERIFY) {
    const v = verifyReview(HTML, OUT, { checkNewer: true });
    if (v.ok) {
      console.log(`✓ 关键帧已审查签收：${v.rec.frames.length} 帧 / 指纹 ${v.rec.fingerprint} / ${v.rec.approvedAt}`);
      if (JSONOUT) console.log(JSON.stringify({ ok: true, ...v.rec }));
      process.exit(0);
    }
    console.error(`✗ 关键帧审查未通过：${v.reason}`);
    if (JSONOUT) console.log(JSON.stringify({ ok: false, reason: v.reason, fingerprint: v.finger.hash }));
    process.exit(1);
  }

  const finger = projectFingerprint(HTML);
  const { browser, exe } = await launch();
  console.log('chromium:', exe);
  const { page, errors, colors } = await openPage(browser, HTML);
  const { fps, duration, acts, mode } = await readTimeline(page, HTML, 0);
  console.log(`工程：${path.basename(HTML)}  指纹 ${finger.hash}  ${duration.toFixed(1)}s / ${fps}fps / ${acts.length} 幕（${mode}）`);

  const srtCues = SRT ? parseSRT(SRT) : null;
  if (SRT && (!srtCues || !srtCues.length)) die(`SRT 解析失败或没有条目：${SRT}`);
  const plan = planPoints(acts, duration, srtCues);
  if (!plan.length) die('没有生成任何审查点，检查 --offsets / --points');

  fs.mkdirSync(paths.dir, { recursive: true });

  /* ---- 1. 逐点渲染 ---- */
  const rows = [];
  const shots = [];
  for (const p of plan) {
    const file = path.join(paths.dir, `kf_${p.t.toFixed(1).replace('.', '_')}s.jpg`);
    await page.evaluate(t => window.renderFrame(t), p.t);
    const buf = await page.screenshot({ path: file, type: 'jpeg', quality: QUALITY });
    const dataUrl = 'data:image/jpeg;base64,' + buf.toString('base64');
    let stats = null, issues = [];
    try {
      stats = await analyze(page, dataUrl, colors);
      issues = judge(stats);
    } catch (e) {
      issues = [{ level: 'WARN', msg: `像素体检失败：${e.message}` }];
    }
    rows.push({ t: p.t, why: p.why, file, stats, issues });
    shots.push({ t: p.t, why: p.why, dataUrl, error: issues.some(i => i.level === 'ERROR') });
    process.stdout.write(`  ${p.t.toFixed(1)}s ${p.why}${issues.length ? '  ← ' + issues.map(i => i.level).join(',') : ''}\n`);
  }

  /* ---- 2. 确定性：同一个 t 隔几张再渲一次，必须逐字节一致 ---- */
  let deterministic = true;
  if (rows.length >= 2) {
    const mid = rows[Math.floor(rows.length / 2)];
    await page.evaluate(t => window.renderFrame(t), mid.t + 1.7);
    const a = await page.screenshot({ type: 'jpeg', quality: QUALITY });
    await page.evaluate(t => window.renderFrame(t), mid.t + 1.7);
    const b = await page.screenshot({ type: 'jpeg', quality: QUALITY });
    deterministic = a.equals(b);
    if (!deterministic) {
      console.error(`✗ 渲染不确定：t=${(mid.t + 1.7).toFixed(1)}s 连渲两次画面不同 → 渲染路径里用了 Math.random / Date.now，逐帧录制会闪`);
    }
  }

  /* ---- 3. 联系表 ---- */
  let contact = null;
  if (!NO_CONTACT) {
    contact = path.join(paths.dir, '_联系表.jpg');
    await makeContactSheet(browser, shots, contact);
    console.log('联系表:', contact);
  }
  await browser.close();

  /* ---- 4. 汇总 + 审查表 ---- */
  const warns = [];
  for (const r of rows) for (const i of r.issues) warns.push({ t: r.t, ...i });
  if (!deterministic) warns.push({ t: 0, level: 'ERROR', msg: '同 t 两次渲染不一致（非确定性）' });
  if (errors.length) warns.push({ t: 0, level: 'WARN', msg: `页面报错 ${errors.length} 条（见上方 console.error）` });

  writeManifest(paths.manifest, { html: HTML, finger, fps, duration, mode, rows, warns, contact, outDir: paths.dir });
  console.log('审查表:', paths.manifest);

  const hard = warns.filter(w => w.level === 'ERROR');
  console.log(`\n共 ${rows.length} 帧：${hard.length} 个 ERROR，${warns.length - hard.length} 个 WARN`);

  /* ---- 5. 签收 / 汇总退出 ---- */
  if (APPROVE !== null) {
    if (!APPROVE || APPROVE.length < 4) {
      die('签收必须写明看过了什么（例：--approve "逐张看过，无错位"），避免"无脑签收"');
    }
    if (hard.length) die(`还有 ${hard.length} 个 ERROR，修完重跑 keyframes.js 再来签收`);
    if (STRICT && warns.length) die(`--strict：还有 ${warns.length} 个 WARN，先处理再签收`);
    const rec = {
      html: path.basename(HTML),
      fingerprint: finger.hash,
      fps, duration: +duration.toFixed(3), mode,
      approvedAt: new Date().toISOString(),
      note: APPROVE,
      frames: rows.map(r => path.basename(r.file)),
      contact: contact ? path.basename(contact) : null,
      warns: warns.length,
    };
    fs.writeFileSync(paths.receipt, JSON.stringify(rec, null, 2), 'utf8');
    console.log(`✓ 已签收（指纹 ${finger.hash}）：${paths.receipt}`);
    console.log('  之后改任何 js/html 都会让签收失效，需要重新出帧审查。');
    if (JSONOUT) console.log(JSON.stringify({ ok: true, approved: rec }));
    process.exit(0);
  }

  if (JSONOUT) {
    console.log(JSON.stringify({
      ok: hard.length === 0 && deterministic,
      fingerprint: finger.hash,
      frames: rows.map(r => ({ t: r.t, file: path.basename(r.file), ink: r.stats && r.stats.ink, issues: r.issues })),
      contact: contact ? path.basename(contact) : null,
      manifest: paths.manifest,
    }));
  }

  if (hard.length || !deterministic) {
    console.error('\n✗ 机械体检有 ERROR：先修再进入看图环节。');
    process.exit(1);
  }
  console.log('\n下一步：逐张 Read 上面的帧（或先看联系表），确认无错位/无多余数字/无叠字后：');
  console.log(`  node ${path.relative(process.cwd(), __filename)} ${HTML} ${OUT} --approve "逐张看过，无错位"`);
  console.log('没有有效签收，render.js 拒绝全量渲染。');
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
