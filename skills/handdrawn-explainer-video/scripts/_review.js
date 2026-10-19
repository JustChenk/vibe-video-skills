'use strict';
/* =========================================================
   _review.js —— 关键帧签收的路径约定与校验（keyframes.js / render.js 共用）

   签收文件与审查帧放在同一个目录（默认 <主题文件夹>/keyframes/）：
     keyframes/_关键帧审查.<入口名>.md     人看的审查表
     keyframes/_联系表.jpg                 一张图看全片
     keyframes/kf_<秒>s.jpg                逐帧
     keyframes/_keyframe_review.<入口名>.json  签收记录（含工程指纹）

   为什么要"签收"：precheck 只能证明代码没写错，证明不了画面对；
   把"审过 = 点过头"固化成指纹记录，工程一改指纹就变、签收自动作废，
   render.js 才能真的拦住"没看图就全量渲染"。
   ========================================================= */
const fs = require('fs');
const path = require('path');
const { projectFingerprint } = require('./_browser.js');

function reviewPaths(htmlPath, outDir) {
  const base = path.basename(htmlPath).replace(/\.html?$/i, '');
  const dir = path.resolve(outDir);
  return {
    dir,
    base,
    manifest: path.join(dir, `_关键帧审查.${base}.md`),
    contact: path.join(dir, '_联系表.jpg'),
    receipt: path.join(dir, `_keyframe_review.${base}.json`),
  };
}

/* opts.checkNewer：除指纹外再用 mtime 兜一层（指纹已覆盖 js/html/字体，mtime 只作补充告警） */
function verifyReview(htmlPath, outDir, opts = {}) {
  const { receipt, dir } = reviewPaths(htmlPath, outDir);
  const finger = projectFingerprint(htmlPath);
  if (!fs.existsSync(receipt)) {
    return { ok: false, reason: `没有关键帧签收记录（${path.relative(process.cwd(), receipt)}）`, finger };
  }
  let rec;
  try { rec = JSON.parse(fs.readFileSync(receipt, 'utf8')); } catch (e) {
    return { ok: false, reason: `签收文件损坏：${receipt}`, finger };
  }
  if (rec.fingerprint !== finger.hash) {
    return {
      ok: false,
      reason: `工程已改动（当前指纹 ${finger.hash}，签收时 ${rec.fingerprint}）—— 旧签收作废，必须重新出帧审查`,
      finger, rec,
    };
  }
  const missing = (rec.frames || []).filter(f => !fs.existsSync(path.join(dir, f)));
  if (missing.length) {
    return {
      ok: false,
      reason: `审查帧缺失 ${missing.length} 张（如 ${missing[0]}）—— 帧目录被清理过，重新跑 keyframes.js`,
      finger, rec,
    };
  }
  if (opts.checkNewer && rec.approvedAt) {
    const stamp = new Date(rec.approvedAt).getTime();
    const newer = (finger.files || []).filter(rel => {
      const p = path.resolve(path.dirname(htmlPath), rel);
      return fs.existsSync(p) && fs.statSync(p).mtimeMs > stamp + 2000;
    });
    if (newer.length) {
      return { ok: false, reason: `签收之后这些文件又被改过：${newer.join(', ')}`, finger, rec };
    }
  }
  return { ok: true, rec, finger };
}

module.exports = { reviewPaths, verifyReview };
