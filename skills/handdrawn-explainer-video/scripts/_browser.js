'use strict';
/* =========================================================
   _browser.js —— render.js / keyframes.js 共用的浏览器加载与工程指纹

   只做两件事：
     1) 找到 playwright-core 与 Chromium（多路径探测，Windows/Linux 都覆盖）
     2) 算出工程指纹（HTML + 它 <script src> 引入的本地 js + 字体/图片资源的
        内容哈希）：改任何一行场景代码，指纹就变 —— 关键帧审查表据此判断
        "这版工程到底被审过没有"。

   不直接运行，被 require。
   ========================================================= */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

/* ---------- 从 html 里解析 <script src="x.js"> 与 <link href="x.css"> ---------- */
function parseRefs(html) {
  const out = [];
  const re = /<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"']+)["']/gi;
  let m;
  while ((m = re.exec(html))) {
    const ref = m[1].trim();
    if (!ref || /^(https?:)?\/\//i.test(ref) || /^(data|blob):/i.test(ref)) continue;
    out.push(ref);
  }
  return out;
}

/* ---------- 工程指纹：内容哈希，与绝对路径无关（换机器/换目录不变） ---------- */
function projectFingerprint(htmlPath) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const dir = path.dirname(path.resolve(htmlPath));
  const parts = [{ name: path.basename(htmlPath), text: html }];

  for (const ref of parseRefs(html)) {
    const p = path.resolve(dir, ref);
    if (!fs.existsSync(p) || !fs.statSync(p).isFile()) continue;
    parts.push({ name: ref.replace(/\\/g, '/'), text: fs.readFileSync(p, 'utf8') });
  }
  /* 字体/图片等二进制资源只吃字节，不吃路径 */
  const assetDirs = ['assets', 'fonts', 'img'];
  for (const d of assetDirs) {
    const abs = path.join(dir, d);
    if (!fs.existsSync(abs) || !fs.statSync(abs).isDirectory()) continue;
    const walk = (cur) => {
      for (const ent of fs.readdirSync(cur, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
        const full = path.join(cur, ent.name);
        if (ent.isDirectory()) { walk(full); continue; }
        if (!/\.(ttf|otf|woff2?|png|jpe?g|webp|svg)$/i.test(ent.name)) continue;
        parts.push({ name: path.relative(dir, full).replace(/\\/g, '/'), buf: fs.readFileSync(full) });
      }
    };
    walk(abs);
  }

  const h = crypto.createHash('sha256');
  for (const part of parts.sort((a, b) => (a.name < b.name ? -1 : 1))) {
    h.update(part.name + '\0');
    h.update(part.buf || part.text);
    h.update('\0');
  }
  return { hash: h.digest('hex').slice(0, 16), files: parts.map(p => p.name).filter(n => /\.(m?js|html|css)$/i.test(n)) };
}

/* ---------- 从工程里解析总时长（dark-field 的 TIMELINE / 手绘的 SCENES） ---------- */
function detectDuration(htmlPath) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const dir = path.dirname(path.resolve(htmlPath));
  let best = null;
  const push = v => { if (Number.isFinite(v) && v > 0) best = Math.max(best || 0, v); };

  for (const ref of parseRefs(html)) {
    const p = path.resolve(dir, ref);
    if (!fs.existsSync(p) || !/\.js$/i.test(p)) continue;
    const src = fs.readFileSync(p, 'utf8');
    /* SCENES: [{start:0, dur:16}, ...] */
    const block = src.match(/const\s+SCENES\s*=\s*\[([\s\S]*?)\];/);
    if (block) {
      for (const m of block[1].matchAll(/start:\s*([\d.]+)\s*,\s*(?:[\w$]+\s*,\s*)*dur:\s*([\d.]+)/g)) {
        push(parseFloat(m[1]) + parseFloat(m[2]));
      }
    }
    /* TIMELINE: [{id:'hook', len:8}, ...] */
    const tl = src.match(/(?:const|let|var)\s+TIMELINE\s*=\s*\[([\s\S]*?)\];/);
    if (tl) {
      let sum = 0;
      for (const m of tl[1].matchAll(/len:\s*([\d.]+)/g)) sum += parseFloat(m[1]);
      push(sum);
    }
  }
  return best;
}

/* ---------- playwright-core：本地 → WorkBuddy 托管 → 全局 ---------- */
function loadPlaywright() {
  try { return require('playwright-core'); } catch (e) { /* next */ }
  const home = process.env.USERPROFILE || process.env.HOME || '';
  const tries = [
    /* WorkBuddy 托管 node 工作区（Windows 下项目内常无 node_modules） */
    path.join(home, '.workbuddy', 'binaries', 'node', 'workspace', 'node_modules', 'playwright-core'),
    /* DSH 托管运行时 */
    path.join(home, '.dsh', 'dsh-runtimes', 'dsh-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright-core'),
  ];
  for (const t of tries) {
    try { return require(t); } catch (e) { /* next */ }
  }
  try {
    const { execSync } = require('child_process');
    const g = execSync('npm root -g', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
    return require(path.join(g, 'playwright-core'));
  } catch (e) { /* next */ }
  console.error('未找到 playwright-core。请二选一：\n' +
    '  · 项目内安装：PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright-core\n' +
    '  · 全局安装：  npm i -g playwright-core');
  process.exit(1);
}

/* ---------- Chromium 探测（Windows + Linux，Playwright / Puppeteer / 系统浏览器） ---------- */
function findChrome() {
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) return process.env.CHROME_PATH;
  const home = process.env.HOME || process.env.USERPROFILE || '/root';
  const candidates = [];

  const pwBases = [path.join(home, '.cache/ms-playwright')];
  if (process.env.LOCALAPPDATA) pwBases.push(path.join(process.env.LOCALAPPDATA, 'ms-playwright'));
  for (const base of pwBases) {
    if (!fs.existsSync(base)) continue;
    for (const d of fs.readdirSync(base)) {
      candidates.push(path.join(base, d, 'chrome-win64', 'chrome.exe'));
      candidates.push(path.join(base, d, 'chrome-win', 'chrome.exe'));
      candidates.push(path.join(base, d, 'chrome-linux64', 'chrome'));
      candidates.push(path.join(base, d, 'chrome-linux', 'chrome'));
      candidates.push(path.join(base, d, 'chrome-headless-shell-linux64', 'chrome-headless-shell'));
      candidates.push(path.join(base, d, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe'));
    }
  }

  const ppBase = path.join(home, '.cache', 'puppeteer', 'chrome');
  if (fs.existsSync(ppBase)) {
    for (const d of fs.readdirSync(ppBase)) {
      candidates.push(path.join(ppBase, d, 'chrome-win64', 'chrome.exe'));
      candidates.push(path.join(ppBase, d, 'chrome-win', 'chrome.exe'));
      candidates.push(path.join(ppBase, d, 'chrome-linux64', 'chrome'));
    }
  }

  if (process.env.ProgramFiles) {
    candidates.push(path.join(process.env.ProgramFiles, 'Google/Chrome/Application/chrome.exe'));
    candidates.push(path.join(process.env.ProgramFiles, 'Microsoft/Edge/Application/msedge.exe'));
  }
  if (process.env['ProgramFiles(x86)']) {
    candidates.push(path.join(process.env['ProgramFiles(x86)'], 'Google/Chrome/Application/chrome.exe'));
    candidates.push(path.join(process.env['ProgramFiles(x86)'], 'Microsoft/Edge/Application/msedge.exe'));
  }
  if (process.env.LOCALAPPDATA) {
    candidates.push(path.join(process.env.LOCALAPPDATA, 'Google/Chrome/Application/chrome.exe'));
    candidates.push(path.join(process.env.LOCALAPPDATA, 'Microsoft/Edge/Application/msedge.exe'));
  }
  candidates.push('/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome');

  for (const c of candidates) if (fs.existsSync(c)) return c;
  return null;
}

/* ---------- 打开工程页面并等待字体（两个脚本共用同一套等待逻辑） ---------- */
async function openPage(browser, htmlPath, viewport) {
  const vw = viewport || { width: 1920, height: 1080 };
  const page = await browser.newPage({ viewport: vw, deviceScaleFactor: 1 });
  const errors = [];
  page.on('console', m => {
    if (m.type() === 'error') { errors.push(m.text()); console.error('[console.error]', m.text()); }
  });
  page.on('pageerror', e => { errors.push(e.message); console.error('[pageerror]', e.message); });
  await page.goto('file://' + path.resolve(htmlPath), { waitUntil: 'load' });
  await page.evaluate(async () => {
    const loads = [];
    const any = window.document.fonts;
    if (any) {
      loads.push(document.fonts.load('400 100px "ZCOOL KuaiLe"', '认字'));
      loads.push(document.fonts.load('400 100px "Patrick Hand"', '123'));
      loads.push(document.fonts.load('700 100px "Caveat"', 'abc'));
      loads.push(document.fonts.ready);
    }
    await Promise.all(loads).catch(() => {});
  });
  const colors = await page.evaluate(() => {
    const c = window.C || {};
    const bg = c.paper || getComputedStyle(document.body).backgroundColor || '#000';
    const ink = c.ink || '#ffffff';
    return { bg, ink };
  });
  return { page, errors, colors };
}

async function launch() {
  const { chromium } = loadPlaywright();
  const exe = findChrome();
  if (!exe) {
    console.error('未找到 Chromium / Chrome。请设置环境变量 CHROME_PATH 指向浏览器可执行文件。');
    process.exit(1);
  }
  const browser = await chromium.launch({
    executablePath: exe,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1', '--hide-scrollbars'],
  });
  return { browser, exe };
}

module.exports = { parseRefs, projectFingerprint, detectDuration, loadPlaywright, findChrome, openPage, launch };
