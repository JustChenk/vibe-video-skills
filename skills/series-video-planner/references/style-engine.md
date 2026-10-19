# 系列风格引擎：怎么让 N 集的画风保持一致

> 本文件回答一个问题：**风格总纲写完、样张也过了，怎么保证第 2 集到第 17 集不会各画各的？**
> 答案是：不靠"约定"，靠**代码层面的强制**——把风格做成一个组件库，场景文件只能调用它，不能自己画。

---

## 一、问题：风格为什么一定会走样

多集、多人（或多次模型调用）制作时，风格漂移有四个必然来源：

| 漂移源 | 表现 | 只靠文档能拦住吗 |
|---|---|---|
| **色值手抄** | 第 3 集把 `#B3241C` 记成 `#C0392B` | ❌ 文档管不住手 |
| **坐标手写** | 第 5 集字幕写到 y=800，压住时间轴 | ❌ 每个人判断不同 |
| **组件重造** | 第 7 集觉得卡片不好看，自己画了个圆角卡 | ❌ "我觉得更好"是创作本能 |
| **动效自创** | 第 9 集加了淡入淡出 | ❌ 很难逐帧检查 |

**结论**：风格一致性是**工程问题**，不是纪律问题。要靠 API 强制。

---

## 二、解法：三层结构

```
style-tokens.json     ← 唯一真源（数据）
        ↓
   archive.js         ← 唯一实现（代码，导出 window.A）
        ↓
    scenes.js         ← 每集只写"画什么"，不写"怎么画"
```

### 第一层：`style-tokens.json`（机器可读的规则）

不是给模型看的说明书，是**给代码读的配置**：

```json
{
  "colors": { "paper": {...}, "ink": {...}, "accent": { "vermilion": "#B3241C", "maxAreaRatio": 0.03 } },
  "fonts":  { "numeric": {...}, "title": {...}, "body": {...} },
  "layout": { "headerBand": {...}, "subtitleBand": {...}, "timeline": {...} },
  "motion": { "stamp": {...}, "typing": {...}, "forbidden": ["fadeIn", "flyIn", ...] },
  "cover":  { ... },
  "sourcePolicy": { "tiers": { "A": {...}, "B": {...}, "C": {...} } }
}
```

关键字段不是色值本身，而是**约束**：`accent.maxAreaRatio`（强调色面积上限）、`motion.forbidden`（禁止的动效）、`layout`（哪些区域永久占位）。

### 第二层：`archive.js`（唯一实现）

把风格做成一个**封闭的组件库**，用 IIFE 包起来，只导出 `window.A`：

```js
(function () {
  const W = 1920, H = 1080;
  const C = { paper: '#E8DFC8', ink: '#1C1A17', red: '#B3241C', ... };
  const L = { margin: 96, takeY: 700, subY: 826, tlY: 972, ... };
  const A = {
    paper(ctx) {...},          // 纸底（缓存 Canvas）
    header(ctx, l, r, a) {...},// 页眉
    timeline(ctx, opt) {...},  // 40 年时间轴
    card(ctx, x, y, w, h, o){...},
    dossier(ctx, ...) {...},   // 档案袋
    stamp(ctx, text, ...) {...},
    title(ctx, lines, ...) {...},
    table(ctx, ...) {...},
    subtitle(ctx, text, p) {...},   // ← 字幕坐标写死在这里
    takeaway(ctx, text, p) {...},   // ← 说明行坐标写死在这里
    footer(ctx, text, p) {...},
    // ... 共 17 个组件
  };
  window.A = A;
})();
```

**关键设计**：

1. **`subtitle` 和 `takeaway` 不接受坐标参数**——位置写死在组件内部。这样任何一集都不可能把字幕写到别处。
2. **`C`（色值）只在库内部可见**，场景文件通过 `A.C.red` 取，不能自己写十六进制。
3. **`L`（版式常量）同样只在库内部**，场景如需定位只能调组件。
4. 所有组件接收**进度参数 `p`（0–1）**，内部分配动效，场景不需要管"怎么出现"。

### 第三层：`scenes.js`（每集只写内容）

```js
function scene3(ctx, t, L) {
  A.timeline(ctx, { grow: 1, active: [1990, 2010] });   // ← 母题：一行搞定
  A.block(ctx, 150, 160, 780, 290, {                     // ← 组件：给内容
    p: A.pg(t, 0.6, 1.8), rot: -0.5,
    head: '别人写的', sub: '泡沫怎么破的\n大藏省怎么救的',
  });
  A.takeaway(ctx, '它不写国家怎么决策，写决策落到人身上是什么样', A.pg(t, 6.2, 7.4));
  A.subtitle(ctx, '市面上写日本的书都在讲国家，这本书讲的是具体的人', A.pg(t, 0.4, 23.0));
}
```

场景文件里**没有一处色值、没有一处字幕坐标、没有一处动效实现**。

---

## 三、`framework.js`：三条硬规矩

`framework.js` 是全系列共用的主框架，**做新集时通常不改**。它负责三件容易出错的事：

### 规矩一：场景函数收到的是**幕内相对时间**

```js
function renderFrame(t) {
  drawBackground(t);                    // 纸底 + 页眉（统一在这里画）
  const { sc, i, local } = sceneAt(t);
  sc.draw(ctx, local, local, i);        // ← 传 local，不是 t
  drawTransition(t);
}
```

**为什么重要**：如果传全局 `t`，场景里写 `A.pg(t, 0.6, 1.8)` 就永远算不对（除了第一幕）。这个坑本次踩过——内容全部不出现，且 precheck 不报错。

### 规矩二：自动化环境必须让位

```js
const AUTOMATED = (typeof navigator !== 'undefined') && navigator.webdriver === true;
function loop(ts) {
  if (window.__hostDriven || AUTOMATED) return;
  renderFrame(((ts - _rafStart) / 1000) % DUR);
}
if (!AUTOMATED) requestAnimationFrame(loop);
```

**为什么重要**：rAF 预览循环会和宿主抽帧抢画布。症状是**抽多个时间点得到同一画面**——极难排查，因为静态检查全绿。

### 规矩三：`renderFrame(t)` 必须是纯函数

同样的 `t` 必须得到同样的画面。任何随机数都要用确定性种子：

```js
function rng(seed) { /* mulberry32 */ }
```

纸底噪点用 `rng(20261020)`，每次生成完全一样。

---

## 四、给新集的接入流程（可复制）

```bash
# 1. 复制框架三件（archive.js / framework.js / video.html）
cp ../Ep00-一个国家的错题本/archive.js .
cp ../Ep00-一个国家的错题本/framework.js .
cp ../Ep00-一个国家的错题本/video.html .

# 2. 新建 scenes.js（从零写，或复制 Ep00 改）
#    只写 scene1..sceneN + SCENES 数组里的 dur

# 3. 改写 framework.js 的 SCENES 数组（start/dur/name）
# 4. precheck → keyframes → 看图 → 签收 → render
```

**`SCENES` 数组是唯一需要按集修改的地方**：

```js
const SCENES = [
  {start: 0.0,   dur: 12, draw: scene1, name: 'S1 抽档'},
  {start: 12.0,  dur: 18, draw: scene2, name: 'S2 钩子'},
  // 后一幕 start 必须 == 前一幕 start + dur（precheck 会查）
];
```

---

## 五、一致性怎么验收（不靠人肉比对）

### 5.1 机械项（脚本能查）

| 检查 | 手段 |
|---|---|
| 色值没手写 | `grep -E "#[0-9A-Fa-f]{6}" scenes.js` 应为 0 命中 |
| 字幕坐标没手写 | `grep "subY\|826" scenes.js` 应为 0 命中 |
| 场景函数用幕内时间 | 看 `A.pg(t, a, b)` 的 a/b 是否都小于 `dur` |
| `SCENES` 时间轴连续 | `precheck.js` 已自动检查 |
| 母题在场 | 每幕 `grep` 到 `A.timeline` 调用 |

### 5.2 视觉项（必须看图）

**关键帧审查是硬门禁**，但要知道它拦得住什么、拦不住什么：

| 拦得住 | 拦不住 |
|---|---|
| 空白幕（非底色 < 0.6%） | 叠字（元素互压但都可见） |
| 画面被填满（> 55%） | 语义错位（箭头指向错的元素） |
| 元素越界（最外 8px 有墨） | 字号层级失当 |
| 左右安全区外有内容 | 颜色对比不足 |
| 压底部进度条 | 母题缺失 |

**所以必须逐张 Read**，不能只看机械体检通过。

### 5.3 本次踩到的"机械体检误判"

`paperDeep`（#CFC0A0）与 `paper`（#E8DFC8）亮度差只有 12%，低于检测阈值 34/255，导致整张卡片被当成底色 → 误报"画面几乎全空"。

**处理**：不是调检测阈值（那是掩盖问题），而是**给卡片加边线、加深底色、加结构线**（折盖线），让它在视觉上真的立起来——同时也让它可被检测到。**视觉改进和检测改进应该是同一件事。**

---

## 六、风格引擎的边界

这套引擎能保证"画风一致"，但保证不了"好看"。它管的是：

- ✅ 色板、字体层级、版式坐标、动效白名单、母题在场
- ✅ 字幕与说明行的位置（永远不会压在一起）
- ❌ 每一幕的内容选择（那是分镜的事）
- ❌ 信息密度是否合适（需要看图判断）
- ❌ 叙事节奏（需要读分镜判断）

**换句话说**：引擎保证"这 17 集是同一个人做的"，但"做得好不好"仍然取决于每一集的分镜设计与看图审查。

---

## 七、文件清单（一个完整的集目录）

```
EpXX-主题/
├── video.html              # 加载 archive.js → scenes.js → framework.js
├── archive.js              # 风格引擎（跨集共用，一般不改）
├── framework.js            # 主框架（跨集共用，只改 SCENES 数组）
├── scenes.js               # 本集内容（唯一需要大改的文件）
├── 字幕.srt                # voice-ready
├── 调研材料.md
├── 视频分镜脚本.md
├── 运镜与制作思路.md         # 为什么这么画
├── keyframes/              # 审查帧 + 联系表 + 签收记录
├── frames/                 # 全量渲染帧（可删，约 1-2GB）
└── 成片.mp4
```
