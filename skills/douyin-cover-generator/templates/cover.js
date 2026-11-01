/* =========================================================
 * cover.js — 夜场光场封面引擎 v2（douyin-cover-generator skill）
 *
 * 运行环境：浏览器页面（templates/cover.html），由 scripts/render-cover.js
 * 通过 playwright-core 截图调用。纯 Canvas 2D，零外部依赖。
 *
 * 设计内核（v2 重构，2026-10-18）：
 *   1. 暗场不黑——五段墨色渐变 + 三层大气光 + 暗角，永远不是一块死灰
 *   2. 光即隐喻——每张封面只有一个光的结构，且必须和文案说同一件事
 *   3. 字是主角——两行硬碰、吃满画幅宽度、逐字字距，不用描边凑对比
 *   4. 双色分层——常规行冷白、强调行金；金色「先糊一层大晕、再叠实体渐变」
 *   5. 一枚印章——全图唯一高饱和色，歪 3°，只用来压紧迫感
 *   6. 编辑暗号——页眉/EP徽标/细线菱形/mono 标注/四角裁切/胶片颗粒
 *
 * 对外接口：window.renderCover(config) -> Promise<void>
 *   config = {
 *     title, subtitle, kicker, issue, stamp, note: string
 *     scene: 'threshold' | 'orbit' | 'beam' | 'plain'   （默认 threshold）
 *     layout: 'title' | 'brand'    （brand = 系列名入标题块首行、片名降一档）
 *     accentLine: 'last' | 'first' | 'all' | 'none'     （默认 last，哪一行用金色）
 *     ratio: '3:4' | '4:3' | '9:16' | '16:9' | '1:1'   （默认 3:4 竖版）
 *     size: [w, h]
 *     bg: { type:'gradient'|'image', src, darken, scrim }
 *     colors: { title（金/强调）, base（冷白）, subtitle, tag（印章红） }
 *     font: string
 *   }
 * ========================================================= */
(function () {
  'use strict';

  /* 默认比例：竖版 3:4（1080x1440）/ 横版 4:3（1920x1440，与成片同宽） */
  var RATIOS = {
    '3:4': [1080, 1440],
    '4:3': [1920, 1440],
    '9:16': [1080, 1920],
    '16:9': [1920, 1080],
    '1:1': [1080, 1080]
  };

  /** 中文粗体字体栈：Windows 微软雅黑 → macOS 苹方 → Linux/鸿蒙 Noto */
  var FONT = '"Microsoft YaHei","PingFang SC","Noto Sans SC","Source Han Sans SC","HarmonyOS Sans SC",sans-serif';
  /** 技术标注用等宽字体 */
  var MONO = '"SF Mono","Consolas","Roboto Mono","DejaVu Sans Mono",monospace';

  /** 中文标题字距 = 0.058em（标题越大字距越大，视觉上才不会「挤成一块」） */
  var TRACK = 0.058;

  /** 旧 --style 名 → 新 scene 名（保证老命令不炸） */
  var SCENE_ALIAS = {
    threshold: 'threshold',
    orbit: 'orbit',
    beam: 'beam',
    plain: 'plain',
    dazibao: 'threshold',  // 旧：大字报 → 门槛光栅
    glow: 'orbit',         // 旧：辉光粒子 → 光轮
    rays: 'beam',          // 旧：斜射光束 → 光束
    grid: 'plain'          // 旧：科技网格 → 纯暗场
  };

  /* =========================================================
     1. 基础工具
     ========================================================= */

  /** 确定性随机：同一配置输出稳定可复现 */
  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function num(v, dflt) {
    var n = parseFloat(v);
    return isFinite(n) && n > 0 ? n : dflt;
  }

  function rgb(hex) {
    var s = String(hex || '#ffffff').replace('#', '');
    if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2];
    var n = parseInt(s, 16);
    if (!isFinite(n)) n = 0xffffff;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function mix(hex, to, t) {
    var a = rgb(hex), b = rgb(to);
    var out = '#';
    for (var i = 0; i < 3; i++) {
      var v = Math.round(a[i] + (b[i] - a[i]) * t);
      out += ('0' + Math.max(0, Math.min(255, v)).toString(16)).slice(-2);
    }
    return out;
  }

  function rgba(hex, a) {
    var c = rgb(hex);
    return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
  }

  function setFont(ctx, size, weight, family) {
    ctx.font = (weight || 900) + ' ' + size + 'px ' + (family || FONT);
  }

  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function radial(ctx, x, y, r, stops) {
    if (r <= 0) return;
    var g = ctx.createRadialGradient(x, y, 0, x, y, r);
    for (var i = 0; i < stops.length; i++) g.addColorStop(stops[i][0], stops[i][1]);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  function line(ctx, x1, y1, x2, y2) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }

  /* ---------- 逐字排版：中文标题的字距只能自己算 ---------- */
  function measureTracked(ctx, text, size, tracking, weight, family) {
    setFont(ctx, size, weight, family);
    var chars = String(text).split('');
    var total = 0;
    for (var i = 0; i < chars.length; i++) total += ctx.measureText(chars[i]).width;
    return total + tracking * Math.max(0, chars.length - 1);
  }

  /**
   * 逐字绘制并返回总宽
   * x：align=center 时为中心，align=left 时为左缘；baseline：字母基线
   */
  function drawTracked(ctx, text, x, baseline, size, tracking, fill, o) {
    o = o || {};
    setFont(ctx, size, o.weight || 900, o.family);
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    var chars = String(text).split('');
    var ws = [];
    var total = 0;
    var i;
    for (i = 0; i < chars.length; i++) {
      var w = ctx.measureText(chars[i]).width;
      ws.push(w);
      total += w;
    }
    total += tracking * Math.max(0, chars.length - 1);
    var cursor = o.align === 'left' ? x : x - total / 2;
    for (i = 0; i < chars.length; i++) {
      if (chars[i] !== ' ') {
        ctx.fillStyle = fill;
        ctx.fillText(chars[i], cursor, baseline);
      }
      cursor += ws[i] + tracking;
    }
    return total;
  }

  /** 从上限往下试，找到能塞进 maxW 的最大字号 */
  function fitSize(ctx, text, maxW, cap, trackingRatio) {
    var s = cap;
    while (s > 20 && measureTracked(ctx, text, s, s * trackingRatio) > maxW) s -= 2;
    return Math.max(16, s);
  }

  var BREAK_PUNCT = '，。！？、；：,.!?;:~～—…';

  /**
   * 选中缝位置：标点最优先，其次按 Intl.Segmenter 的中文词边界，
   * 都尽量靠近中点。避免把「省钱」这种词从中间劈开。
   */
  function pickBreak(text) {
    var target = text.length / 2;
    var best = -1, bestScore = -1e9, i;
    function consider(idx, bonus) {
      if (idx <= 0 || idx >= text.length) return;
      var score = bonus + 40 - Math.abs(idx - target);
      if (score >= bestScore) { bestScore = score; best = idx; }
    }
    for (i = 1; i < text.length; i++) {
      if (BREAK_PUNCT.indexOf(text[i - 1]) >= 0 || text[i] === ' ') consider(i, 100);
    }
    try {
      if (typeof Intl !== 'undefined' && Intl.Segmenter) {
        var seg = new Intl.Segmenter('zh-Hans', { granularity: 'word' });
        var idx = 0;
        var parts = seg.segment(text);
        for (var s of parts) {
          idx += s.segment.length;
          consider(idx, 30);
        }
      }
    } catch (e) { /* 没有 Segmenter 就退回中点 */ }
    if (best < 0) best = Math.ceil(text.length / 2);
    return best;
  }

  /** 标题折行：显式 \n 优先；否则在词边界处切，最多 maxLines 行 */
  function wrapTitle(text, wrapAt, maxLines) {
    if (String(text).indexOf('\n') >= 0) {
      return String(text).split('\n').map(function (s) { return s.trim(); })
        .filter(function (s) { return s; }).slice(0, maxLines);
    }
    if (text.length <= wrapAt) return [text];
    var best = pickBreak(text);
    var lines = [text.slice(0, best).trim(), text.slice(best).trim()];
    if (text.length > wrapAt * maxLines) {
      var per = Math.ceil(text.length / maxLines);
      lines = [];
      for (var j = 0; j < text.length; j += per) lines.push(text.slice(j, j + per));
      lines = lines.slice(0, maxLines);
      console.warn('[cover] 标题 ' + text.length + ' 字已折 ' + lines.length + ' 行，建议压到 12 字以内');
    }
    return lines.filter(function (l) { return l; });
  }

  /* =========================================================
     2. 色板与版式度量
     ========================================================= */

  function palette(cfg) {
    var accent = cfg.colors.title || '#FFC53D';
    return {
      accent: accent,
      base: cfg.colors.base || '#F2F6FF',
      sub: cfg.colors.subtitle || '#E9F0FF',
      stamp: cfg.colors.tag || '#FF5A3C',
      accentHi: mix(accent, '#FFFFFF', 0.74),
      accentMid: mix(accent, '#FFFFFF', 0.24),
      accentLo: mix(accent, '#000000', 0.14),
      baseHi: '#FFFFFF',
      baseLo: mix(cfg.colors.base || '#F2F6FF', '#7F95B8', 0.42)
    };
  }

  /** 所有位置都是画幅比例，换比例不用改代码；横竖版共用中轴构图，只调重心 */
  function metrics(w, h, vertical) {
    return {
      vertical: vertical,
      headerBase: h * 0.075,
      headerX: w * 0.085,
      titleX: w * 0.5,
      titleAlign: 'center',
      titleCenterY: h * (vertical ? 0.365 : 0.353),
      titleMaxW: w * 0.86,
      titleCap: h * (vertical ? 0.20 : 0.235),
      blockMaxH: h * (vertical ? 0.30 : 0.34),
      ruleY: h * 0.553,
      gateY: h * (vertical ? 0.668 : 0.745),
      subBase: h * (vertical ? 0.903 : 0.625),
      subX: w * 0.5,
      subAlign: 'center'
    };
  }

  /* =========================================================
     3. 场景：底 + 光结构（每张封面只允许一个）
     ========================================================= */

  function drawBase(ctx, w, h, m, p, vertical) {
    var g = ctx.createLinearGradient(0, 0, w * 0.35, h);
    g.addColorStop(0.00, '#05060C');
    g.addColorStop(0.30, '#0A1022');
    g.addColorStop(0.55, '#0B1226');
    g.addColorStop(0.76, '#070A15');
    g.addColorStop(1.00, '#03040A');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    var ax = vertical ? w * 0.51 : w * 0.30;
    var ay = vertical ? h * 0.46 : h * 0.42;
    radial(ctx, ax, ay, Math.max(w, h) * 0.47, [
      [0, rgba(p.accent, 0.16)],
      [0.45, rgba(p.accent, 0.06)],
      [1, rgba(p.accent, 0)]
    ]);
    radial(ctx, ax, ay + h * 0.03, Math.max(w, h) * 0.26, [
      [0, rgba(p.accent, 0.10)],
      [1, rgba(p.accent, 0)]
    ]);
    radial(ctx, w * 0.09, h * 0.66, Math.max(w, h) * 0.46, [
      [0, 'rgba(58,104,255,0.13)'],
      [1, 'rgba(58,104,255,0)']
    ]);
    radial(ctx, w * 0.92, h * 0.25, Math.max(w, h) * 0.38, [
      [0, 'rgba(122,84,255,0.10)'],
      [1, 'rgba(122,84,255,0)']
    ]);
  }

  function drawStars(ctx, w, h, p, rnd) {
    var n = Math.min(720, Math.round((w * h) / 4200));
    ctx.save();
    for (var i = 0; i < n; i++) {
      var x = rnd() * w;
      var y = Math.pow(rnd(), 0.85) * h * 0.98;
      var r = Math.pow(rnd(), 2.6) * (h * 0.0013) + h * 0.00018;
      var fade = 1 - Math.max(0, (y - h * 0.68) / (h * 0.45)) * 0.6;
      ctx.globalAlpha = (0.10 + rnd() * 0.7) * fade;
      ctx.fillStyle = rnd() > 0.84 ? '#CFE1FF' : '#FFFFFF';
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    // 柔焦光斑：让暗部有厚度
    for (var k = 0; k < 6; k++) {
      var bx = w * (0.05 + rnd() * 0.9);
      var by = h * (0.05 + rnd() * 0.9);
      var br = h * (0.02 + rnd() * 0.05);
      radial(ctx, bx, by, br, [
        [0, 'rgba(198,220,255,' + (0.045 + rnd() * 0.04).toFixed(3) + ')'],
        [1, 'rgba(150,180,255,0)']
      ]);
    }
  }

  /** 四芒星：暗场里的呼吸点 */
  function flare(ctx, x, y, s, a) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    radial(ctx, x, y, s * 3.4, [
      [0, 'rgba(255,248,232,' + a + ')'],
      [0.3, 'rgba(255,224,168,' + (a * 0.26).toFixed(3) + ')'],
      [1, 'rgba(255,205,130,0)']
    ]);
    ctx.strokeStyle = 'rgba(255,242,220,' + a + ')';
    ctx.lineCap = 'round';
    var spikes = [[1, 0, 3.6, 1.2], [0, 1, 2.2, 1], [-1, 0, 2.0, 0.9], [0, -1, 1.5, 0.8]];
    for (var i = 0; i < spikes.length; i++) {
      var dx = spikes[i][0], dy = spikes[i][1], len = spikes[i][2], lw = spikes[i][3];
      ctx.lineWidth = lw;
      line(ctx, x - dx * s * len, y - dy * s * len, x + dx * s * len, y + dy * s * len);
    }
    ctx.restore();
  }

  function drawFlares(ctx, w, h, vertical) {
    var pts = vertical
      ? [[0.18, 0.205, 0.0056, 0.5], [0.86, 0.315, 0.0042, 0.4], [0.13, 0.60, 0.0042, 0.32], [0.93, 0.20, 0.003, 0.3]]
      : [[0.40, 0.16, 0.005, 0.45], [0.72, 0.24, 0.004, 0.36], [0.90, 0.62, 0.004, 0.3]];
    for (var i = 0; i < pts.length; i++) {
      flare(ctx, w * pts[i][0], h * pts[i][1], h * pts[i][2], pts[i][3]);
    }
  }

  /** 场景一：门槛——光束汇集到一道封死的横栏（最契合「路径/门槛/期限」） */
  function sceneThreshold(ctx, w, h, m, p, vertical, note) {
    var gateY = m.gateY;
    var x0 = w * (vertical ? 0.08 : 0.06);
    var x1 = w * (vertical ? 0.92 : 0.94);
    var vpx = (x0 + x1) / 2;
    var s0 = vertical ? 0.02 : 0.03;
    var s1 = vertical ? 0.98 : 0.97;
    var endY = h * (vertical ? 0.846 : 1.00);
    var i;

    // 地面光池
    ctx.save();
    ctx.translate(vpx, gateY + h * 0.034);
    ctx.scale(1, 0.30);
    ctx.globalCompositeOperation = 'lighter';
    radial(ctx, 0, 0, (x1 - x0) * 0.42, [
      [0, rgba(p.accent, 0.16)],
      [1, rgba(p.accent, 0)]
    ]);
    ctx.restore();

    // 十二条光路
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    var N = 12;
    var rayW = Math.max(6, h * 0.0072);
    for (i = 0; i < N; i++) {
      var t = i / (N - 1);
      var ex = (s0 + t * (s1 - s0)) * w;
      var mid = Math.sin(Math.PI * t);
      var g = ctx.createLinearGradient(vpx, gateY, ex, endY);
      g.addColorStop(0.00, rgba(p.accent, 0.58 + mid * 0.28));
      g.addColorStop(0.20, rgba(p.accent, 0.28 + mid * 0.12));
      g.addColorStop(0.62, rgba(p.accent, 0.10));
      g.addColorStop(1.00, rgba(p.accent, 0));
      ctx.strokeStyle = g;
      ctx.globalAlpha = 0.14;
      ctx.lineWidth = rayW;
      line(ctx, vpx, gateY, ex, endY);
      ctx.globalAlpha = 1;
      ctx.lineWidth = Math.max(1, h * 0.0014);
      line(ctx, vpx, gateY, ex, endY);
    }
    // 余脉：一路渗到画框下沿，避免下半部发空
    ctx.globalAlpha = 1;
    var tail = ctx.createLinearGradient(0, endY - h * 0.04, 0, h);
    tail.addColorStop(0, rgba(p.accent, 0.05));
    tail.addColorStop(1, rgba(p.accent, 0.012));
    ctx.strokeStyle = tail;
    ctx.lineWidth = Math.max(1, h * 0.0009);
    for (i = 0; i < N; i++) {
      var tt = i / (N - 1);
      var exx = (s0 + tt * (s1 - s0)) * w;
      var py = endY - h * 0.035;
      var px = vpx + (exx - vpx) * (py - gateY) / (h - gateY);
      line(ctx, px, py, exx, h + h * 0.02);
    }
    ctx.restore();

    // 栅栏
    var step = w * 0.026;
    for (var x = x0 + step; x < x1 - step; x += step) {
      var k = Math.sin(Math.PI * (x - x0) / (x1 - x0));
      ctx.fillStyle = rgba(p.accent, 0.05 + Math.max(0, k) * 0.15);
      ctx.fillRect(x, gateY - h * 0.0235, Math.max(1, w * 0.0015), h * 0.047);
    }

    // 门柱
    var posts = [x0, x1];
    for (i = 0; i < posts.length; i++) {
      var pg = ctx.createLinearGradient(0, gateY - h * 0.043, 0, gateY + h * 0.043);
      pg.addColorStop(0, rgba(p.accent, 0));
      pg.addColorStop(0.5, rgba(mix(p.accent, '#FFFFFF', 0.55), 0.92));
      pg.addColorStop(1, rgba(p.accent, 0));
      ctx.fillStyle = pg;
      ctx.fillRect(posts[i] - Math.max(1, w * 0.0016), gateY - h * 0.043, Math.max(2, w * 0.0032), h * 0.086);
    }

    // 横梁
    ctx.save();
    var barG = ctx.createLinearGradient(x0, 0, x1, 0);
    barG.addColorStop(0.00, rgba(p.accent, 0));
    barG.addColorStop(0.14, rgba(mix(p.accent, '#FFFFFF', 0.45), 0.6));
    barG.addColorStop(0.50, rgba(mix(p.accent, '#FFFFFF', 0.86), 0.98));
    barG.addColorStop(0.86, rgba(mix(p.accent, '#FFFFFF', 0.45), 0.6));
    barG.addColorStop(1.00, rgba(p.accent, 0));
    ctx.shadowColor = rgba(p.accent, 0.92);
    ctx.shadowBlur = h * 0.026;
    ctx.fillStyle = barG;
    ctx.fillRect(x0, gateY - Math.max(1, h * 0.0018), x1 - x0, Math.max(3, h * 0.003));
    ctx.restore();

    // 技术标注（可选）：唯一允许出现在光结构上的文字
    if (note) {
      ctx.save();
      ctx.globalAlpha = 0.38;
      var ns = h * 0.0126;
      var nt = h * 0.005;
      var nw = measureTracked(ctx, note, ns, nt, 400, MONO);
      if (nw > w * 0.6) { ns *= (w * 0.6) / nw; nt *= (w * 0.6) / nw; }
      drawTracked(ctx, note, vpx, gateY - h * 0.036, ns, nt, rgba(p.accent, 0.9), {
        weight: 400, family: MONO
      });
      ctx.restore();
    }
  }

  /** 场景二：光轮——一枚行星的边缘横贯画面，适合「周期/门槛/命运」 */
  function sceneOrbit(ctx, w, h, m, p, vertical) {
    var cx = w * 0.5;
    var cy = h * (vertical ? 1.34 : 1.30);
    var r = h * (vertical ? 0.60 : 0.56);
    var i;

    // 地平线上方的余晖：先让「行星」有大气
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    radial(ctx, cx, cy - r, r * 0.62, [
      [0, rgba(p.accent, 0.075)],
      [0.5, rgba(p.accent, 0.03)],
      [1, rgba(p.accent, 0)]
    ]);
    radial(ctx, cx, cy - r * 0.02, r * 1.06, [
      [0.90, rgba(p.accent, 0)],
      [0.985, rgba(p.accent, 0.05)],
      [1, rgba(p.accent, 0)]
    ]);
    ctx.restore();

    // 星球本体：把背景压成实体（边缘以下不再透星光）
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(3,5,12,0.68)';
    ctx.fill();

    // 边缘光晕：整条边缘先糊一层，再按角度叠亮段
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.shadowColor = rgba(p.accent, 0.85);
    ctx.shadowBlur = h * 0.032;
    ctx.strokeStyle = rgba(p.accent, 0.26);
    ctx.lineWidth = Math.max(2, h * 0.0032);
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    // 按角度分 128 段：光源在正上方
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (i = 0; i < 128; i++) {
      var a0 = (i / 128) * Math.PI * 2;
      var a1 = ((i + 1) / 128) * Math.PI * 2;
      var ang = (a0 + a1) / 2;
      var k = 0.18 + 0.82 * Math.max(0, Math.cos(ang + Math.PI / 2));
      ctx.strokeStyle = rgba(p.accent, (0.55 * k).toFixed(3));
      ctx.lineWidth = Math.max(2, h * 0.0022);
      ctx.beginPath();
      ctx.arc(cx, cy, r, a0, a1 + 0.006);
      ctx.stroke();
    }
    ctx.restore();

    // 十二根刻度：沿可见弧面排开，把「12」藏进结构里
    ctx.save();
    var dir = Math.atan2(h / 2 - cy, w / 2 - cx);
    for (i = 0; i < 12; i++) {
      var t = (i / 11 - 0.5) * 0.9;
      var a3 = dir + t;
      var k2 = 0.25 + 0.75 * Math.cos(t * 1.4);
      ctx.strokeStyle = rgba(p.accent, (0.36 * k2).toFixed(3));
      ctx.lineWidth = Math.max(1, h * 0.0011);
      line(ctx,
        cx + Math.cos(a3) * r * 1.014, cy + Math.sin(a3) * r * 1.014,
        cx + Math.cos(a3) * r * 1.052, cy + Math.sin(a3) * r * 1.052);
    }
    ctx.restore();
  }

  /** 光束模板：横向软边 + 纵向渐隐，用离屏层烘焙，避免 ctx.filter 的平台差异 */
  function makeShaft(color) {
    var c2 = document.createElement('canvas');
    c2.width = 128;
    c2.height = 256;
    var g2 = c2.getContext('2d');
    var vg = g2.createLinearGradient(0, 0, 0, 256);
    vg.addColorStop(0.00, rgba(color, 1));
    vg.addColorStop(0.35, rgba(color, 0.7));
    vg.addColorStop(0.70, rgba(color, 0.28));
    vg.addColorStop(1.00, rgba(color, 0.06));
    g2.fillStyle = vg;
    g2.fillRect(0, 0, 128, 256);
    g2.globalCompositeOperation = 'destination-in';
    var hg = g2.createLinearGradient(0, 0, 128, 0);
    hg.addColorStop(0.00, 'rgba(0,0,0,0)');
    hg.addColorStop(0.30, 'rgba(0,0,0,0.5)');
    hg.addColorStop(0.50, 'rgba(0,0,0,1)');
    hg.addColorStop(0.70, 'rgba(0,0,0,0.5)');
    hg.addColorStop(1.00, 'rgba(0,0,0,0)');
    g2.fillStyle = hg;
    g2.fillRect(0, 0, 128, 256);
    return c2;
  }

  /** 场景三：光束——一束斜穿画面的体积光，适合情绪/故事 */
  function sceneBeam(ctx, w, h, m, p, vertical) {
    var i;
    var tpl = makeShaft(p.accent);

    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.translate(w * 0.5, -h * 0.18);
    var shafts = [
      { x: -0.10, rot: -0.40, wid: 0.30, a: 0.20 },
      { x: 0.10, rot: -0.30, wid: 0.16, a: 0.24 },
      { x: 0.42, rot: -0.56, wid: 0.36, a: 0.12 }
    ];
    for (i = 0; i < shafts.length; i++) {
      var s = shafts[i];
      ctx.save();
      ctx.rotate(s.rot);
      ctx.globalAlpha = s.a;
      ctx.drawImage(tpl, w * s.x, 0, w * s.wid, h * 1.5);
      ctx.restore();
    }
    ctx.globalAlpha = 1;

    // 光刃：一条锐利的高光边，给光束一个「入射方向」
    ctx.save();
    ctx.rotate(-0.34);
    var eg = ctx.createLinearGradient(0, 0, 0, h * 1.35);
    eg.addColorStop(0, rgba(mix(p.accent, '#FFFFFF', 0.72), 0.5));
    eg.addColorStop(0.55, rgba(mix(p.accent, '#FFFFFF', 0.4), 0.14));
    eg.addColorStop(1, rgba(p.accent, 0));
    ctx.fillStyle = eg;
    ctx.fillRect(w * 0.115, 0, Math.max(1.5, w * 0.0018), h * 1.35);
    ctx.restore();
    ctx.restore();

    // 入射点的光核
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    radial(ctx, w * 0.47, h * 0.02, Math.max(w, h) * 0.36, [
      [0, rgba(p.accent, 0.12)],
      [0.55, rgba(p.accent, 0.04)],
      [1, rgba(p.accent, 0)]
    ]);
    ctx.restore();

    // 落地光池：光要有落点，画面才不会头重脚轻
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.translate(w * 0.66, h * 1.0);
    ctx.scale(1, 0.22);
    radial(ctx, 0, 0, w * 0.48, [
      [0, rgba(p.accent, 0.09)],
      [1, rgba(p.accent, 0)]
    ]);
    ctx.restore();

    // 尘埃：只在光里才看得见
    var rnd = mulberry32(7717 + Math.round(w));
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (i = 0; i < 46; i++) {
      var dx = rnd() * w;
      var dy = h * (0.05 + rnd() * 0.62);
      var dr = h * (0.0006 + rnd() * 0.0016);
      ctx.globalAlpha = 0.10 + rnd() * 0.28;
      ctx.fillStyle = '#FFE7BE';
      ctx.beginPath();
      ctx.arc(dx, dy, dr, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function drawScene(ctx, w, h, m, p, cfg, vertical) {
    drawBase(ctx, w, h, m, p, vertical);
    var rnd = mulberry32(20261018 + Math.round(w * 7 + h));
    drawStars(ctx, w, h, p, rnd);
    drawFlares(ctx, w, h, vertical);

    var scene = SCENE_ALIAS[cfg.scene] || 'threshold';
    if (scene === 'threshold') sceneThreshold(ctx, w, h, m, p, vertical, cfg.note);
    else if (scene === 'orbit') sceneOrbit(ctx, w, h, m, p, vertical);
    else if (scene === 'beam') sceneBeam(ctx, w, h, m, p, vertical);
  }

  /* =========================================================
     4. 图片背景：把自有素材调进同一套夜色里
     ========================================================= */
  function drawImageBg(ctx, img, w, h, m, p, cfg, vertical) {
    var iw = img.naturalWidth || img.width;
    var ih = img.naturalHeight || img.height;
    var target = w / h, cur = iw / ih, sx = 0, sy = 0, sw = iw, sh = ih;
    if (cur > target) { sw = ih * target; sx = (iw - sw) / 2; }
    else { sh = iw / target; sy = (ih - sh) / 2; }
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, w, h);

    // 冷调压色：让实拍素材也落进这套墨蓝里
    ctx.save();
    ctx.globalCompositeOperation = 'multiply';
    ctx.fillStyle = '#39426A';
    ctx.fillRect(0, 0, w, h);
    ctx.restore();

    ctx.fillStyle = 'rgba(3,5,12,' + Math.max(0, Math.min(0.85, cfg.bg.darken)) + ')';
    ctx.fillRect(0, 0, w, h);

    // 文字区压暗：中轴构图，上下都要托住字
    if (cfg.bg.scrim) {
      var tg = ctx.createLinearGradient(0, 0, 0, h * 0.62);
      tg.addColorStop(0, 'rgba(3,5,12,0.72)');
      tg.addColorStop(1, 'rgba(3,5,12,0)');
      ctx.fillStyle = tg;
      ctx.fillRect(0, 0, w, h * 0.62);
      var sg = ctx.createLinearGradient(0, h * 0.55, 0, h);
      sg.addColorStop(0, 'rgba(3,5,12,0)');
      sg.addColorStop(1, 'rgba(3,5,12,0.78)');
      ctx.fillStyle = sg;
      ctx.fillRect(0, h * 0.55, w, h * 0.45);
    }

    // 标题后方的暖光：图片再暗也要有光源感
    radial(ctx, m.titleX, m.titleCenterY, Math.max(w, h) * 0.34, [
      [0, rgba(p.accent, 0.10)],
      [1, rgba(p.accent, 0)]
    ]);
  }

  /* =========================================================
     5. 排版：页眉 / 标题 / 细分隔 / 副标题 + 印章
     ========================================================= */

  function drawHeader(ctx, w, h, m, p, cfg, brand) {
    var s = h * 0.021;
    if (cfg.kicker && !brand) {
      var bh = h * 0.0217;
      ctx.fillStyle = rgba(p.accent, 0.92);
      ctx.fillRect(m.headerX, m.headerBase - bh, Math.max(2, w * 0.0033), bh);
      drawTracked(ctx, cfg.kicker, m.headerX + w * 0.0198, m.headerBase, s, s * 0.09,
        'rgba(226,237,255,0.62)', { weight: 600, align: 'left' });
    }
    if (cfg.issue) {
      var cw = h * 0.082, ch = h * 0.0315;
      var cx = w - m.headerX - cw, cy = m.headerBase - ch * 0.9;
      roundRect(ctx, cx, cy, cw, ch, h * 0.0032);
      ctx.fillStyle = rgba(p.accent, 0.06);
      ctx.fill();
      ctx.strokeStyle = rgba(p.accent, 0.40);
      ctx.lineWidth = Math.max(1, w * 0.0009);
      ctx.stroke();
      drawTracked(ctx, cfg.issue, cx + cw / 2, cy + ch * 0.665, h * 0.0151, h * 0.0034,
        rgba(p.accent, 0.95), { weight: 600, family: MONO });
    }
  }

  /** 白行：冷白 → 淡蓝，靠暗投影托住 */
  function drawBaseLine(ctx, text, x, baseline, size, p, m, family) {
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,0.62)';
    ctx.shadowBlur = size * 0.28;
    ctx.shadowOffsetY = size * 0.10;
    var g = ctx.createLinearGradient(0, baseline - size * 0.9, 0, baseline + size * 0.16);
    g.addColorStop(0.00, p.baseHi);
    g.addColorStop(0.56, p.base);
    g.addColorStop(1.00, p.baseLo);
    drawTracked(ctx, text, x, baseline, size, size * TRACK, g, {
      align: m.titleAlign, weight: 900, family: family
    });
    ctx.restore();
  }

  /** 金行：先糊一层大晕，再叠实体渐变——这是「发光」和「贴一层黄」的区别 */
  function drawAccentLine(ctx, text, x, baseline, size, p, m, family) {
    ctx.save();
    ctx.shadowColor = rgba(p.accent, 0.62);
    ctx.shadowBlur = size * 0.54;
    drawTracked(ctx, text, x, baseline, size, size * TRACK, rgba(p.accent, 0.95), {
      align: m.titleAlign, weight: 900, family: family
    });
    ctx.restore();

    ctx.save();
    ctx.shadowColor = rgba(p.accentLo, 0.5);
    ctx.shadowBlur = size * 0.12;
    ctx.shadowOffsetY = size * 0.028;
    var g = ctx.createLinearGradient(0, baseline - size * 0.92, 0, baseline + size * 0.14);
    g.addColorStop(0.00, p.accentHi);
    g.addColorStop(0.38, p.accentMid);
    g.addColorStop(0.72, p.accent);
    g.addColorStop(1.00, p.accentLo);
    drawTracked(ctx, text, x, baseline, size, size * TRACK, g, {
      align: m.titleAlign, weight: 900, family: family
    });
    ctx.restore();
  }

  function drawTitleBlock(ctx, lines, m, p, cfg) {
    var n = lines.length;
    var brand = cfg.layout === 'brand' && !!cfg.kicker && n > 1;
    var scales = [], i;
    for (i = 0; i < n; i++) scales.push(brand && i === 0 ? 0.76 : 1);

    var cap = Math.min(m.titleCap, m.blockMaxH / (n * 1.2));
    var fitted = [];
    for (i = 0; i < n; i++) fitted.push(fitSize(ctx, lines[i], m.titleMaxW, cap, TRACK));
    var baseSize = Infinity;
    for (i = 0; i < n; i++) baseSize = Math.min(baseSize, fitted[i] / scales[i]);

    var sizes = [];
    for (i = 0; i < n; i++) sizes.push(Math.min(cap, baseSize * scales[i]));

    var maxSize = 0;
    for (i = 0; i < n; i++) maxSize = Math.max(maxSize, sizes[i]);
    var lh = maxSize * 1.19;
    var blockH = (n - 1) * lh + maxSize;
    var top = m.titleCenterY - blockH / 2;

    // 强调行：默认最后一行
    var accentIdx = n - 1;
    var acc = cfg.accentLine || 'last';
    if (acc === 'first') accentIdx = 0;
    else if (acc === 'all') accentIdx = -2;   // -2 = 全部
    else if (acc === 'none') accentIdx = -1;

    var y = top + sizes[0] * 0.86;
    for (i = 0; i < n; i++) {
      var isAccent = accentIdx === -2 || i === accentIdx;
      if (isAccent) drawAccentLine(ctx, lines[i], m.titleX, y, sizes[i], p, m, cfg.font);
      else drawBaseLine(ctx, lines[i], m.titleX, y, sizes[i], p, m, cfg.font);
      y += lh;
    }
    return {
      top: top,
      bottom: top + blockH,
      size: maxSize
    };
  }

  /** 标题与场景之间的细分隔：两段细线夹一枚菱形 */
  function drawSpine(ctx, w, h, m, p, block) {
    var y = Math.max(m.ruleY, block.bottom + h * 0.045);
    if (y > m.gateY - h * 0.07) return;
    var half = Math.min(w * 0.10, h * 0.09), gap = Math.min(w * 0.0185, h * 0.016);
    ctx.strokeStyle = rgba(p.accent, 0.26);
    ctx.lineWidth = 1;
    line(ctx, w / 2 - half, y, w / 2 - gap, y);
    line(ctx, w / 2 + gap, y, w / 2 + half, y);
    ctx.save();
    ctx.translate(w / 2, y);
    ctx.rotate(Math.PI / 4);
    ctx.fillStyle = rgba(p.accent, 0.55);
    ctx.fillRect(-h * 0.0031, -h * 0.0031, h * 0.0062, h * 0.0062);
    ctx.restore();
  }

  function drawStamp(ctx, text, cx, cy, bw, bh, p) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-3 * Math.PI / 180);
    var x = -bw / 2, y = -bh / 2;

    ctx.shadowColor = rgba(p.stamp, 0.45);
    ctx.shadowBlur = bh * 0.34;
    roundRect(ctx, x, y, bw, bh, bh * 0.09);
    ctx.fillStyle = rgba(p.stamp, 0.10);
    ctx.fill();
    ctx.lineWidth = Math.max(2, bh * 0.033);
    ctx.strokeStyle = rgba(p.stamp, 0.92);
    ctx.stroke();

    ctx.shadowBlur = 0;
    ctx.lineWidth = Math.max(1, bh * 0.011);
    ctx.strokeStyle = rgba(p.stamp, 0.42);
    roundRect(ctx, x + bh * 0.078, y + bh * 0.078, bw - bh * 0.156, bh - bh * 0.156, bh * 0.05);
    ctx.stroke();

    var ts = bh * 0.62;
    var tw = measureTracked(ctx, text, ts, ts * 0.12, 800);
    var sc = Math.min(1, (bw - bh * 0.28) / Math.max(1, tw));
    drawTracked(ctx, text, 0, ts * 0.34, ts * sc, ts * sc * 0.12, rgba(p.stamp, 0.96),
      { weight: 800, align: 'center' });
    ctx.restore();
  }

  function drawCaption(ctx, w, h, m, p, cfg) {
    var baseSize = h * (m.vertical ? 0.052 : 0.046);
    var maxW = w * 0.86;
    var size = baseSize;
    var subW = 0, gap = 0, dotR = 0, stampH = 0, stampW = 0, total = 0;
    var hasStamp = !!cfg.stamp;

    // 副标题 + 印章必须整体塞进画幅：先压字号，压到底再舍弃印章
    function measure(s, withStamp) {
      subW = cfg.subtitle ? measureTracked(ctx, cfg.subtitle, s, s * 0.045, 800) : 0;
      gap = s * 0.40;
      dotR = s * 0.066;
      stampH = s * 1.22;
      stampW = stampH * 3.1;
      total = subW + (withStamp ? gap * 2 + dotR * 2 + stampW : 0);
    }
    measure(size, hasStamp);
    while (size > baseSize * 0.72 && total > maxW) {
      size -= 2;
      measure(size, hasStamp);
    }
    if (total > maxW && hasStamp) {
      hasStamp = false;
      measure(size, false);
    }
    while (size > 24 && total > maxW) {
      size -= 2;
      measure(size, false);
    }

    var x0 = m.subAlign === 'center' ? m.titleX - total / 2 : m.subX;
    var baseline = m.subBase;

    if (cfg.subtitle) {
      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,0.6)';
      ctx.shadowBlur = size * 0.32;
      ctx.shadowOffsetY = size * 0.1;
      drawTracked(ctx, cfg.subtitle, x0, baseline, size, size * 0.045, rgba(p.sub, 0.96),
        { weight: 800, align: 'left' });
      ctx.restore();
    }

    if (hasStamp) {
      var dotX = x0 + subW + gap + dotR;
      var cy = baseline - size * 0.33;
      ctx.fillStyle = rgba(p.accent, 0.85);
      ctx.beginPath();
      ctx.arc(dotX, cy, dotR, 0, Math.PI * 2);
      ctx.fill();
      drawStamp(ctx, cfg.stamp, dotX + dotR + gap + stampW / 2, cy, stampW, stampH, p);
    }
  }

  /* =========================================================
     6. 收尾：压暗 / 颗粒 / 裁切标记
     ========================================================= */

  function drawFinish(ctx, w, h, m) {
    // 底部压暗：给副标题一块干净的底
    var sg = ctx.createLinearGradient(0, h * 0.78, 0, h);
    sg.addColorStop(0, 'rgba(3,5,12,0)');
    sg.addColorStop(0.45, 'rgba(3,5,12,0.42)');
    sg.addColorStop(1, 'rgba(3,5,12,0.74)');
    ctx.fillStyle = sg;
    ctx.fillRect(0, h * 0.78, w, h * 0.22);

    // 暗角
    var vg = ctx.createRadialGradient(w / 2, h * 0.46, Math.min(w, h) * 0.20, w / 2, h * 0.5, Math.max(w, h) * 0.86);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(0.62, 'rgba(0,0,0,0.16)');
    vg.addColorStop(1, 'rgba(0,0,0,0.70)');
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, w, h);

    // 胶片颗粒：把「渐变」变成「材质」
    var nz = document.createElement('canvas');
    nz.width = nz.height = 256;
    var nx = nz.getContext('2d');
    var img = nx.createImageData(256, 256);
    for (var i = 0; i < img.data.length; i += 4) {
      var v = 110 + Math.random() * 145;
      img.data[i] = v; img.data[i + 1] = v; img.data[i + 2] = v; img.data[i + 3] = 255;
    }
    nx.putImageData(img, 0, 0);
    ctx.save();
    ctx.globalCompositeOperation = 'overlay';
    ctx.globalAlpha = 0.05;
    ctx.fillStyle = ctx.createPattern(nz, 'repeat');
    ctx.fillRect(0, 0, w, h);
    ctx.restore();

    // 四角裁切标记
    var mm = Math.min(w, h) * 0.048;
    var L = Math.min(w, h) * 0.022;
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.13)';
    ctx.lineWidth = Math.max(1, Math.min(w, h) * 0.0013);
    var corners = [[mm, mm, 1, 1], [w - mm, mm, -1, 1], [mm, h - mm, 1, -1], [w - mm, h - mm, -1, -1]];
    for (var c = 0; c < corners.length; c++) {
      var q = corners[c];
      ctx.beginPath();
      ctx.moveTo(q[0] + q[2] * L, q[1]);
      ctx.lineTo(q[0], q[1]);
      ctx.lineTo(q[0], q[1] + q[3] * L);
      ctx.stroke();
    }
    ctx.restore();
  }

  /* =========================================================
     7. 主入口
     ========================================================= */
  window.renderCover = function (config) {
    var cfg = {
      title: (config && config.title) || '',
      subtitle: (config && config.subtitle) || '',
      kicker: (config && config.kicker) || '',
      issue: (config && config.issue) || '',
      stamp: (config && config.stamp) || (config && config.tag) || '',
      note: (config && config.note) || '',
      scene: (config && config.scene) || 'threshold',
      layout: (config && config.layout) || 'title',
      accentLine: (config && config.accentLine) || 'last',
      ratio: (config && config.ratio) || '3:4',
      size: (config && config.size) || null,
      font: (config && config.font) || '',
      colors: Object.assign({
        title: '#FFC53D',
        base: '#F2F6FF',
        subtitle: '#E9F0FF',
        tag: '#FF5A3C'
      }, (config && config.colors) || {}),
      bg: Object.assign({
        type: 'gradient',
        src: '',
        darken: 0.35,
        scrim: true
      }, (config && config.bg) || {})
    };

    var size = cfg.size || RATIOS[cfg.ratio] || RATIOS['3:4'];
    var w = size[0], h = size[1];
    var vertical = h >= w;

    var canvas = document.getElementById('cover');
    canvas.width = w;
    canvas.height = h;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    var ctx = canvas.getContext('2d');

    function paint(bgImg) {
      var p = palette(cfg);
      var m = metrics(w, h, vertical);
      ctx.clearRect(0, 0, w, h);

      if (bgImg) {
        drawImageBg(ctx, bgImg, w, h, m, p, cfg, vertical);
      } else {
        drawScene(ctx, w, h, m, p, cfg, vertical);
      }

      var brand = cfg.layout === 'brand' && !!cfg.kicker;
      // 9 字以内单行（字号仍能撑满宽度）；10 字以上自动折两行，避免字被压小
      var lines = wrapTitle(cfg.title, 9, 2);
      if (!lines.length) lines = [' '];
      if (brand) lines = [cfg.kicker].concat(lines).slice(0, 3);

      drawHeader(ctx, w, h, m, p, cfg, brand);
      var block = drawTitleBlock(ctx, lines, m, p, cfg);
      drawSpine(ctx, w, h, m, p, block);
      drawCaption(ctx, w, h, m, p, cfg);
      drawFinish(ctx, w, h, m);
    }

    if (cfg.bg.type === 'image' && cfg.bg.src) {
      return new Promise(function (resolve, reject) {
        var img = new Image();
        img.onload = function () { paint(img); resolve(); };
        img.onerror = function () { reject(new Error('背景图加载失败: ' + cfg.bg.src)); };
        img.src = cfg.bg.src;
      });
    }
    paint(null);
    return Promise.resolve();
  };
})();
