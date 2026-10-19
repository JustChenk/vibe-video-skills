#!/usr/bin/env node
'use strict';
/* =========================================================
   render.js —— 逐帧渲染 video.html → JPEG 帧序列

   用法:
     node render.js <html_path> <frames_dir> [options]

   自检模式（抽几个时间点看看）:
     node render.js ./video.html ./testframes --test "3.2,8,14"
     → 只出几张图，不做任何门禁检查（自检就是为了看问题）

   全量模式（出整片帧）:
     node render.js ./video.html ./frames --fps 24 --dur 170
     ⚠️ 全量渲染前必须通过【关键帧视觉审查】：
        先跑 keyframes.js 出审查帧并逐张看过，再 --approve 签收；
        这里读不到有效签收（没签 / 工程改过 / 帧被删）就直接拒绝渲染。
        确需跳过（例如只补渲一小段）用 --allow-unreviewed，并在交付说明里写清原因。

   参数:
     --fps 24              帧率（默认 24）
     --dur 170             总时长秒（默认 170；写成工程真实时长）
     --test "3,8"          抽帧自检，只渲这些时间点
     --review-dir <dir>    签收目录，默认 ./keyframes（与 keyframes.js 保持一致）
     --clean               开始前清空目标帧目录（防止旧帧和新帧混在一起）
     --allow-unreviewed    跳过关键帧签收门禁（不推荐）
     --quality 92          JPEG 质量

   依赖: playwright-core（npm i playwright-core）+ 本机 Chromium/Chrome
   ========================================================= */
const fs = require('fs');
const path = require('path');
const { launch, openPage, verifyReview } = (() => {
  const b = require('./_browser.js');
  const r = require('./_review.js');
  return { ...b, ...r };
})();

function arg(name, dflt) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : dflt;
}
const has = n => process.argv.includes(n);

const HTML = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : null;
const OUT_DIR = process.argv[3] && !process.argv[3].startsWith('--') ? process.argv[3] : null;
const FPS = parseInt(arg('--fps', '24'), 10);
const DUR = parseFloat(arg('--dur', '170'));
const TEST = arg('--test', null);
const REVIEW_DIR = arg('--review-dir', './keyframes');
const CLEAN = has('--clean');
const ALLOW_UNREVIEWED = has('--allow-unreviewed');
const QUALITY = parseInt(arg('--quality', '92'), 10);

if (!HTML || !OUT_DIR) {
  console.error('用法: node render.js <html_path> <frames_dir> [--fps 24] [--dur 170] [--test "3.2,8"] [--clean] [--review-dir ./keyframes]');
  process.exit(1);
}

/* ---------------- 全量渲染门禁：关键帧视觉审查签收 ---------------- */
function gate() {
  if (TEST) return;                                  /* 自检模式不拦 */
  if (ALLOW_UNREVIEWED) {
    console.warn('\n⚠️  --allow-unreviewed：跳过关键帧视觉审查门禁。');
    console.warn('   交付前请补跑 keyframes.js 并逐张看一遍，别让未审画面进成片。\n');
    return;
  }
  const v = verifyReview(HTML, REVIEW_DIR, { checkNewer: true });
  if (v.ok) {
    console.log(`✓ 关键帧已审查签收：${v.rec.frames.length} 帧 / 指纹 ${v.rec.fingerprint} / ${v.rec.approvedAt}`);
    return;
  }
  console.error('\n✗ 拒绝全量渲染：关键帧视觉审查没有通过。');
  console.error(`  原因：${v.reason}\n`);
  console.error('  正确顺序：');
  console.error(`    node keyframes.js ${HTML} ${REVIEW_DIR}            # 出审查帧 + 联系表 + 审查表`);
  console.error('    # 逐张 Read 审查帧（或先看 _联系表.jpg），改完重跑到干净再签收');
  console.error(`    node keyframes.js ${HTML} ${REVIEW_DIR} --approve "逐张看过，无错位"`);
  console.error(`    node render.js ${HTML} ${OUT_DIR} --fps ${FPS} --dur ${DUR}\n`);
  console.error('  静态 precheck 只能证明代码没写错，证明不了画面对；这一步不能省。');
  process.exit(1);
}

(async () => {
  gate();

  const { browser, exe } = await launch();
  console.log('chromium:', exe);

  if (CLEAN && fs.existsSync(OUT_DIR)) {
    const before = fs.readdirSync(OUT_DIR).filter(f => /\.(jpe?g|png)$/i.test(f)).length;
    for (const f of fs.readdirSync(OUT_DIR)) {
      if (/\.(jpe?g|png)$/i.test(f)) fs.unlinkSync(path.join(OUT_DIR, f));
    }
    console.log(`已清空 ${OUT_DIR}（删掉 ${before} 张旧帧）`);
  }
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const { page, errors } = await openPage(browser, HTML);
  const fontsOk = await page.evaluate(() => document.fonts.check('100px "ZCOOL KuaiLe"') || true);
  console.log('fonts loaded:', fontsOk);

  if (TEST) {
    for (const t of TEST.split(',').map(Number)) {
      await page.evaluate(tt => window.renderFrame(tt), t);
      const f = path.join(OUT_DIR, `test_${String(t).replace('.', '_')}s.jpg`);
      await page.screenshot({ path: f, type: 'jpeg', quality: QUALITY });
      console.log('rendered', t, '->', f);
    }
    console.log('\n⚠️  自检帧只能用来"看问题"，不能当审查证据：出片前仍要跑 keyframes.js 走完整审查。');
  } else {
    const total = Math.round(DUR * FPS);
    const t0 = Date.now();
    for (let i = 0; i < total; i++) {
      await page.evaluate(t => window.renderFrame(t), i / FPS);
      await page.screenshot({
        path: path.join(OUT_DIR, `f${String(i).padStart(5, '0')}.jpg`),
        type: 'jpeg', quality: QUALITY,
      });
      if (i % 240 === 0) {
        const el = (Date.now() - t0) / 1000;
        console.log(`frame ${i}/${total}  ${el.toFixed(0)}s elapsed  ${(i / Math.max(el, 0.01)).toFixed(1)} fps`);
      }
    }
    const got = fs.readdirSync(OUT_DIR).filter(f => /^f\d{5}\.jpg$/.test(f)).length;
    console.log(`\nDONE ${total} frames in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    if (got !== total) {
      console.error(`✗ 帧数不符：期望 ${total}，实际 ${got}（渲染中断或目录里有旧帧，重跑请加 --clean）`);
      await browser.close();
      process.exit(1);
    }
    if (errors.length) console.warn(`⚠️  渲染期间页面报了 ${errors.length} 条错误，先核对画面再编码`);
  }

  await browser.close();
})();
