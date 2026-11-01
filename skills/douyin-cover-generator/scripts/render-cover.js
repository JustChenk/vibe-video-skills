#!/usr/bin/env node
'use strict';
/* =========================================================
 * render-cover.js — 封面渲染 CLI（HTML+Canvas → PNG）
 * douyin-cover-generator skill v2「夜场光场」配套，与视频管线 render.js 同栈同依赖。
 *
 * 用法:
 *   node render-cover.js --title $'十二条路\n门槛写死了' --subtitle "18 岁之后" \
 *     --stamp "期限作废" --kicker "人生高性价比指南" --issue "EP.31" \
 *     --scene threshold --ratio 3:4 --out 封面_竖版3x4.png
 *   node render-cover.js --title "..." --ratio 4:3 --bg frame.png --scene plain --out 封面_横版4x3.png
 *
 * 默认比例: 竖版 3:4（1080x1440）; 横版 4:3（1920x1440）
 * 可选比例: 3:4 / 4:3 / 9:16 / 16:9 / 1:1 / 自定义 --size WxH
 *
 * 依赖: playwright-core（npm i playwright-core，不下载浏览器）
 * Chromium 自动探测顺序: CHROME_PATH → ms-playwright/puppeteer 缓存
 *   → 系统 Chrome/Edge → agent-browser 缓存
 * ========================================================= */
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}
const hasFlag = (name) => process.argv.indexOf(name) >= 0;

/* ---------- Chromium 探测（覆盖视频管线全部路径 + agent-browser 缓存） ---------- */
function findChrome() {
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) return process.env.CHROME_PATH;
  const home = process.env.HOME || process.env.USERPROFILE || '/root';
  const candidates = [];
  const pwBases = [path.join(home, '.cache/ms-playwright')];
  if (process.env.LOCALAPPDATA) pwBases.push(path.join(process.env.LOCALAPPDATA, 'ms-playwright'));
  for (const base of pwBases) {
    if (!fs.existsSync(base)) continue;
    for (const d of fs.readdirSync(base)) {
      candidates.push(path.join(base, d, 'chrome-linux64', 'chrome'));
      candidates.push(path.join(base, d, 'chrome-linux', 'chrome'));
      candidates.push(path.join(base, d, 'chrome-headless-shell-linux64', 'chrome-headless-shell'));
      candidates.push(path.join(base, d, 'chrome-win64', 'chrome.exe'));
      candidates.push(path.join(base, d, 'chrome-win', 'chrome.exe'));
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
  candidates.push('/usr/bin/chromium', '/usr/bin/google-chrome');
  // agent-browser 安装的 Chrome
  const abBase = path.join(home, '.agent-browser', 'browsers');
  if (fs.existsSync(abBase)) {
    for (const d of fs.readdirSync(abBase)) {
      candidates.push(path.join(abBase, d, 'chrome-win64', 'chrome.exe'));
      candidates.push(path.join(abBase, d, 'chrome-linux64', 'chrome'));
    }
  }
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return null;
}

/* ---------- playwright-core 多路径加载（与 render.js 一致） ---------- */
function loadPlaywright() {
  try { return require('playwright-core'); } catch (e) {}
  try {
    const home = process.env.USERPROFILE || process.env.HOME;
    return require(path.join(home, '.workbuddy', 'binaries', 'node', 'workspace', 'node_modules', 'playwright-core'));
  } catch (e) {}
  try {
    const { execSync } = require('child_process');
    const g = execSync('npm root -g').toString().trim();
    return require(path.join(g, 'playwright-core'));
  } catch (e) {}
  console.error('未找到 playwright-core，请先执行：PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright-core（或在全局安装）');
  process.exit(1);
}

/* ---------- 场景名归一：新名 + 旧 --style 名都认 ---------- */
const SCENES = {
  threshold: 'threshold', dazibao: 'threshold',
  orbit: 'orbit', glow: 'orbit',
  beam: 'beam', rays: 'beam',
  plain: 'plain', grid: 'plain'
};

/* ---------- 参数 → 配置 ----------
 * 优先级：CLI 显式参数 > --config 文件值 > 内置默认值。
 * v2 换掉了 v1 的部分视觉参数（bar/fx/badge 块），旧参数会被忽略并提示，
 * 但 --tag / --title-color / --style 这类能自然映射的仍然兼容。
 */
function buildConfig() {
  const cfgFile = arg('--config', '');
  const base = cfgFile ? JSON.parse(fs.readFileSync(cfgFile, 'utf8')) : {};
  const baseBg = base.bg || {};
  const baseColors = base.colors || {};
  const d = (v, fallback) => (v === undefined || v === null ? fallback : v);

  const ratio = arg('--ratio', d(base.ratio, '3:4'));
  const sizeRaw = arg('--size', '');
  const fileSize = Array.isArray(base.size) ? base.size.join('x') : base.size;
  const sizeArg = sizeRaw || fileSize || '';
  let size = null;
  if (sizeArg) {
    const m = String(sizeArg).toLowerCase().split('x');
    if (m.length !== 2 || isNaN(+m[0]) || isNaN(+m[1])) {
      console.error('--size 格式应为 WxH，如 1080x1920');
      process.exit(1);
    }
    size = [+m[0], +m[1]];
  }

  const cliBg = arg('--bg', '');
  const darken = parseFloat(arg('--darken', String(d(baseBg.darken, 0.35))));
  let bg;
  if (cliBg) {
    bg = { type: 'image', src: pathToFileURL(path.resolve(cliBg)).href, darken, scrim: !hasFlag('--no-scrim') };
  } else if (baseBg.type === 'image' && baseBg.src) {
    bg = { type: 'image', src: baseBg.src, darken, scrim: hasFlag('--no-scrim') ? false : baseBg.scrim !== false };
  } else {
    bg = { type: 'gradient', src: '', darken, scrim: true };
  }

  /* 旧参数映射：能对上的直接接过来，对不上的收集起来提示一次 */
  const sceneRaw = arg('--scene', arg('--style', d(base.scene, 'threshold')));
  const issueRaw = arg('--issue', d(base.issue, ''));
  const badgeRaw = arg('--badge', '');
  const ignoreFlags = [];
  ['--bar-color', '--stroke-color', '--fx', '--no-shadow', '--title-scale',
    '--kicker-scale', '--tag-scale', '--badge-caption', '--badge-y', '--badge-scale',
    '--badge-caption-color'].forEach((f) => { if (hasFlag(f) || arg(f, '')) ignoreFlags.push(f); });

  return {
    title: arg('--title', d(base.title, '')),
    subtitle: arg('--subtitle', d(base.subtitle, '')),
    kicker: arg('--kicker', d(base.kicker, '')),
    issue: issueRaw || (badgeRaw ? (/^\d+$/.test(badgeRaw) ? 'EP.' + badgeRaw : badgeRaw) : ''),
    stamp: arg('--stamp', arg('--tag', d(base.stamp, d(base.tag, '')))),
    note: arg('--note', d(base.note, '')),
    scene: SCENES[String(sceneRaw).toLowerCase()] || 'threshold',
    sceneRaw,
    layout: arg('--layout', d(base.layout, 'title')),
    accentLine: arg('--accent-line', d(base.accentLine, 'last')),
    ratio,
    size,
    bg,
    colors: {
      title: arg('--accent-color', arg('--title-color', d(baseColors.title, '#FFC53D'))),
      base: arg('--base-color', d(baseColors.base, '#F2F6FF')),
      subtitle: arg('--subtitle-color', d(baseColors.subtitle, '#E9F0FF')),
      tag: arg('--stamp-color', arg('--tag-color', d(baseColors.tag, '#FF5A3C')))
    },
    font: arg('--font', d(base.font, '')),
    _ignore: ignoreFlags,
    _badgeIgnored: !!badgeRaw
  };
}

(async () => {
  const cfg = buildConfig();
  const OUT = arg('--out', '');
  if (!cfg.title) { console.error('缺少 --title（主标题必填）'); process.exit(1); }
  if (['title', 'brand'].indexOf(cfg.layout) < 0) {
    console.error('--layout 只能是 title（片名当主角）或 brand（系列名入标题块首行）');
    process.exit(1);
  }
  if (cfg.layout === 'brand' && !cfg.kicker) {
    console.error('--layout brand 需要同时给 --kicker（系列标识），否则标题块首行是空的');
    process.exit(1);
  }
  if (['last', 'first', 'all', 'none'].indexOf(cfg.accentLine) < 0) {
    console.error('--accent-line 只能是 last / first / all / none');
    process.exit(1);
  }
  if (!OUT) { console.error('缺少 --out（输出路径必填）'); process.exit(1); }
  if (cfg.bg.type === 'image' && !fs.existsSync(arg('--bg', ''))) {
    console.error('背景图不存在: ' + arg('--bg', ''));
    process.exit(1);
  }
  if (cfg.sceneRaw && !SCENES[String(cfg.sceneRaw).toLowerCase()]) {
    console.error('--scene 只能是 threshold / orbit / beam / plain');
    process.exit(1);
  }
  if (cfg.stamp && cfg.stamp.length > 6) {
    console.warn('[render-cover] 印章文字 ' + cfg.stamp.length + ' 字偏长，印章会缩小字号，建议压到 4 字');
  }
  if (cfg._ignore.length || cfg._badgeIgnored) {
    const used = cfg._ignore.filter((f) => f !== '--badge-y' && f !== '--badge-scale' && f !== '--badge-caption' && f !== '--badge-caption-color');
    if (used.length) console.warn('[render-cover] v2 已移除这些 v1 视觉参数，本次忽略: ' + used.join(' '));
    if (cfg._badgeIgnored) console.warn('[render-cover] --badge 已改为 EP 徽标（--issue），数字会自动加 EP. 前缀');
  }

  const size = cfg.size || {
    '3:4': [1080, 1440],   // 竖版（默认）
    '4:3': [1920, 1440],   // 横版（默认，与成片同宽 1920）
    '9:16': [1080, 1920],
    '16:9': [1920, 1080],
    '1:1': [1080, 1080]
  }[cfg.ratio] || [1080, 1440];
  const [w, h] = size;

  const { chromium } = loadPlaywright();
  const exe = findChrome();
  if (!exe) { console.error('未找到 Chromium，请设置 CHROME_PATH 环境变量'); process.exit(1); }

  const html = path.join(__dirname, '..', 'templates', 'cover.html');
  const browser = await chromium.launch({
    executablePath: exe,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1', '--hide-scrollbars', '--font-render-hinting=none']
  });
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  page.on('console', (m) => { if (m.type() === 'error') console.error('[console.error]', m.text()); });
  page.on('pageerror', (e) => console.error('[pageerror]', e.message));
  await page.goto('file://' + path.resolve(html));
  await page.evaluate(async () => { await document.fonts.ready; });

  const payload = Object.assign({}, cfg);
  delete payload._ignore;
  delete payload._badgeIgnored;
  delete payload.sceneRaw;
  await page.evaluate((c) => window.renderCover(c), payload);

  const outDir = path.dirname(path.resolve(OUT));
  fs.mkdirSync(outDir, { recursive: true });
  await page.screenshot({ path: OUT, type: 'png', clip: { x: 0, y: 0, width: w, height: h } });
  await browser.close();
  console.log(`[render-cover] 已生成 ${OUT} (${w}x${h}) · scene=${cfg.scene} · accent=${cfg.colors.title}`);
})().catch((e) => { console.error('[render-cover] 失败:', e.message); process.exit(1); });
