---
name: dark-field-explainer-video

description: "把任意主题制作成「黑场发光字 + 数据可视化 + 粒子流场」风格的科技感动态图文科普短片（1080p MP4，JS + Canvas 逐帧渲染），又称 Opus5.5 风（该风格由 Claude Opus 5.5 主导设计）。风格接近参考片《「我爱你」说到第 1000 遍，信息量几乎为零》：近纯黑底 + 单层颗粒 + 橙红发光强调色 + 衬线大标题 + 极简数据图 + 长黑场转场。当用户要求做'科技感视频/高级感图文视频/暗色系解说视频/数据可视化视频/黑底金字那种风格的视频/Opus5.5 风/opus5.5风格'，或给出一个偏思辨、可量化的主题并要求用这种视觉语言呈现时使用。区别于 handdrawn-explainer-video（纸面手绘卡通）。关键词：科技感视频、暗场、发光字、数据可视化、粒子流场、动态图文、黑底科普、Opus5.5 风"

version: "1.3.0"

author: "CodeBuddy AI"

created: "2026-10-14"

changelog: "1.3.0 渲染管线接入关键帧视觉审查门禁（与手绘风共用 handdrawn-explainer-video 新增的 keyframes.js）：阶段 5 从「抽帧目检」升级为「按幕自动出帧 + 联系表 + 机械体检 + 逐张看过后签收」，render.js 全量渲染前校验签收（改任何 js/html 签收即作废）；编码改用 Node 版 encode.js（无 bash 可用，第 4 参数即码率，暗场仍建议 8M）并加 --clean；新增 grab.js --acts 成片每幕抽帧复核。1.2.1 补坑 2.8「渲染/编码赛跑」：重渲不清空 frames/ + 编码与渲染并行会让成片幕序错乱且错位不单调（ffprobe 完全正常，极难诊断），固化三条纪律——重渲先删整个 frames/、渲染编码严格串行、编码前验帧数与 mtime 单簇。 1.2.0 依 Ep01 实战返工沉淀：precheck 新增 GLOW_NO_COLOR 静态检查（glow-r/glow-w 元素的 class 链缺显式 color 会渲染成黑字橙晕伪发光，渲染前无法目视发现），production-notes 补坑 2.7 与「定位四件套（left/top/size/color）」写法定式。1.1.0 依 159s 实产成片与参考片的差距复盘：新增「三层结构语法」硬纪律（每幕 ≥2 层，杜绝纯黑底孤立文字的空洞幕）、数据可视化组件库（点阵网格 / 微光条目卡）、「大字压场渐晕」可读性手法与新幕式「档案墙幕」，并加入别名「Opus5.5 风」（该风格由 Claude Opus 5.5 主导设计）。1.0.0 首个版本。源自对参考片《「我爱你」说到第 1000 遍，信息量几乎为零》的抽帧逆向：固化「黑场 + 发光字 + 数据可视化 + 粒子流场」的视觉规格（references/style-spec.md）、六种分幕套路（references/scene-patterns.md）、可直跑的工程模板（templates/video-template.html）与渲染前静态自检 scripts/precheck.js。渲染管线复用 handdrawn-explainer-video 的 render.js / encode.sh，不重复实现。"
---

# 暗场发光图文视频生成器（Dark-Field Explainer Video）

> **Goal**：用户给一个主题（可附链接/材料/数据），产出一部 **150~180 秒、1080p、暗场发光图文风格** 的科普解说短片 MP4，含工程源码、分镜脚本与调研材料。

这不是"黑底版的 PPT"。它是一种**有严格视觉纪律的电影感图文语言**：屏幕大部分时间是空的，一个数字出现、发光、然后消失。理解这套纪律比会写 Canvas 重要得多——**先读完「风格定义」，再动笔写代码。**

---

## 1. 什么时候用这个 skill（选型）

| | `dark-field-explainer-video`（本 skill） | `handdrawn-explainer-video` |
|---|---|---|
| 视觉 | 近纯黑底、发光字、橙红强调、数据图、粒子场 | 米黄纸面、手绘线稿、蜡笔色、角色 |
| 气质 | 冷静、克制、有分量、"在讲一件严肃的事" | 亲和、通俗、轻快、"讲给初中生听" |
| 适合的题材 | **能被量化或抽象的认知议题**：信息论、概率、复利、注意力、习惯、熵、迟到的代价、熬夜的账 | **有具体形象、可演示的过程**：Linux 内存怎么管、排序算法怎么走、疫苗怎么起作用 |
| 观众 expectation | 愿意跟着数字思考 | 需要被哄着看完 |
| 渲染成本 | **快**（约 21 fps，720 帧 34 秒） | 慢（线稿描边密集） |

**判断口诀：这个主题最有说服力的是"一个数字"，还是"一个过程"？**
数字和概念 → 本 skill；过程和动作 → 手绘。

两者共用同一条渲染管线，只是第 2 步的美术体系不同，所以 **`render.js` / `encode.sh` 直接复用**，详见 §5。

---

## 2. 风格定义（不可妥协的部分）

完整规格见 `references/style-spec.md`。以下是浓缩版，**八条硬规则**：

### ① 底色是"有颗粒的黑"，不是纯黑
`#0a0a0c`，再叠一层 **5~6% 的胶片颗粒**（`feTurbulence` 噪点，screen 混合）。纯黑在屏幕上会糊成一坨，颗粒让暗部"有呼吸"，这是高级感的第一来源。

### ② 全片只有一种强调色
**橙红 `#ff4d2b`**（亮提 PC 尽可能用 `#ff6a45`）。它只服务于三样东西：**关键数字、关键词、当前焦点**。绝不用于装饰、标题全体、渐变背景。
其余全部是灰阶：`#f2f2f4`（正文）→ `#b9b9c1`（大标题）→ `#8a8a92`（次级）→ `#5a5a62`（弱化）→ `#2e2e36`（描边）。

### ③ 发光是"光晕"，不是"描边"
强调字的发光必须是**三层递进**的 `text-shadow`，绝不加 `text-stroke`：

```css
text-shadow: 0 0 16px rgba(255,86,50,.60),
             0 0 54px rgba(255,70,40,.38),
             0 0 110px rgba(255,60,30,.20);
```

### ④ 字体只有两套
- **衬线（宋体一脉）**：公式、大标题、"有重量的词" → `Source Han Serif SC, Noto Serif SC, Songti SC, STSong, SimSun, serif`
- **无衬线（黑体）**：说明、标签、字幕 → `PingFang SC, Microsoft YaHei, Hiragino Sans GB, sans-serif`
混用第三套字体立刻出戏。

### ⑤ 一屏只讲一件事，且大量留白
画面有效信息区通常只占屏幕的 **40~60%**。四周大面积留空不是没做完，是这套语言的核心语法。**如果一屏塞了三个知识点，那已经失败了。**

### ⑥ 转场靠黑场，不靠特效
幕之间**切到接近全黑**（参考片在 30 秒附近整屏只剩两个字）。默认：幕尾淡出 0.35s → 幕头淡入 0.35s。禁止翻页、滑动、缩放类花哨转场。

### ⑦ 数字要有"落地的重量"
关键数字出现时伴随轻微**缩放弹性**（0.86 → 1.0）和 0.25s 左右的缓动，让它像被"按"进画面里，而不是淡出来就完事。

### ⑧ 每一幕至少两层：背景纹理层 + 前景信息层
背景层是**存在感 5%~20% 的暗淡重复元素**（漂浮消息气泡、点阵网格、弱流场、微光条目），它提供密度与质感；前景才是发光焦点。**禁止出现「纯黑底 + 孤立几行字」的空洞幕**——纯黑只是幕与幕之间的**转场**，不是任何一幕的常态。三层分工与组件规格见 `references/style-spec.md` §5。

---

## 3. 生产流程

### 阶段 0 · 适配性判断
确认主题的说服力来自"可量化"。若主题只能靠讲故事推进（如人物传记），建议改用 `handdrawn-explainer-video`，并向用户说明原因。

### 阶段 1 · 调研与**量化**（本风格的关键差异）
常规调研之外（保留 `research/` 原始来源留痕，形成 **成片 → 调研材料 → 原始来源** 三层溯源），多一步：**把每个论点换算成一个具体数字或对比量级。**
参考片之所以成立，是因为它把"腻了"翻译成了 `≈ 0 bit`。没有数字的论述撑不起这种画面语言。

### 阶段 2 · 分幕（写 `TIMELINE`）
每幕必须回答：这一幕甩给观众的那个数字/那句话是什么？
幕长 **6~12 秒**，总时长 150~180 秒。套路见 `references/scene-patterns.md`（七种：数字幕 / 对比幕 / 公式幕 / 数据图幕 / 列举幕 / 情绪粒子幕 / 档案墙幕）。

**必须有一个钩子开场和一个能落地的应用收尾**——参考片最后落到"要一直出新。这是这个时代的通用法则"，纯理论讲完观众没有带走的东西。

### 阶段 3 · 写工程
从 `templates/video-template.html` 起手，**不要从零写**。它已经包含了 LEGO CSS 变量、场景调度、确定性保障和 `__hostDriven` 让位机制。

### 阶段 4 · 静态自检（**强制，先跑再渲**）
```bash
node <skill>/scripts/precheck.js <项目>/video.html [渲染时长秒]
```
专治三类事故：`--test` 抽多个时间点却得到同一画面（rAF 抢帧）、幕时长改了但渲染 `--dur` 没改、引用了外链资源导致离线渲染失败。

### 阶段 5 · 关键帧视觉审查（**强制门禁，先审再渲**）
```bash
node ../handdrawn-explainer-video/scripts/keyframes.js <项目>/video.html <项目>/keyframes
# → 每幕自动取 20%/55%/90% 各一帧 + 联系表 _联系表.jpg + 审查表 _关键帧审查.video.md
# → 逐张 Read（或先看联系表再放大可疑幕），重点看：发光字有没有变成描边、每幕是否 ≥2 层、
#   强调色是否滥用、有没有纯黑底孤立文字幕
node ../handdrawn-explainer-video/scripts/keyframes.js <项目>/video.html <项目>/keyframes --approve "逐张看过"
```
这版脚本与手绘风共用，按 `TIMELINE` 算幕边界、按暗场底色算"非底色占比"，
一样会拦空白幕 / 越界溢墨 / 压进度条 / 非确定性。**没有有效签收，全量渲染会被 render.js 拒绝。**

（`render.js --test "2,9,17"` 仍然可以用来看某几个时间点，但它只出你点名的那几张、没有签收，
不能替代这一步——暗场尤其容易"抽到的都是正常幕，漏掉那个空洞幕"。）

### 阶段 6 · 全量渲染 + 编码
```bash
node .../render.js <项目>/video.html <项目>/frames --fps 30 --dur <总时长> --clean
node .../encode.js <项目>/frames 30 "<项目>/<片名>.mp4" 8M    # 或 bash .../encode.sh …
```
> 这类画面建议 **`-b:v 8M`**：大面积近黑场景在低码率下会出现色带（banding）。`encode.js` 的第 4 个参数就是码率。
> 编码后用 `node .../grab.js "<成片>" --acts --html <项目>/video.html` 铺一遍每幕，和审查帧比对。

### 阶段 7 · 交付
如需配乐/配音：`bash scripts/merge-audio.sh -a assets/xx.mp3 <视频>`。
封面用 `douyin-cover-generator`，**注意封面风格要跟这条暗色片保持一致**（黑底 + 橙强调），不能还用手绘纸面那套。

---

## 4. 技术铁律（逐帧渲染的生命线）

### 铁律一 · `renderFrame(t)` 必须是纯函数
同一个 `t` 必须永远得到同一幅画面。**禁止**在渲染路径里调用 `Math.random()`、`Date.now()`、`performance.now()`。
随机数必须在**初始化阶段**定死（生成粒子数组时抽完，之后只推演），参考片流场那 1000 个粒子的初始坐标就是启动时一次抽好的。

### 铁律二 · 让位机制（`__hostDriven`）
工程 HTML 同时扮演"浏览器预览页"和"渲染源"两个角色，**实时的 `requestAnimationFrame` 循环会和宿主驱动的 `renderFrame(t)` 抢帧**。症状极其隐蔽：`--test` 抽五个不同时间点，出来的却是同一幕。

模板里的正确写法：

```js
window.renderFrame = t => { window.__hostDriven = true; frame(t); };
(function loop(){
  if (!window.__hostDriven) frame((performance.now()/1000) % DURATION);
  requestAnimationFrame(loop);
})();
```

**宿主一旦接管，rAF 立刻让位。** `precheck.js` 会强制校验这一点。

### 铁律三 · 零外链资源
无头浏览器渲染时不保证联网。**禁止** `<img src="http...">`、外链 `@font-face`、CDN 脚本。字体一律走系统字体栈（§2 ④）。

---

## 5. 依赖与脚本（共享，不重复实现）

| 资源 | 位置 | 说明 |
|---|---|---|
| `render.js` | `../handdrawn-explainer-video/scripts/render.js` | 逐帧渲染（playwright-core + Chromium）；全量渲染前校验关键帧签收 |
| `keyframes.js` | `../handdrawn-explainer-video/scripts/keyframes.js` | 关键帧视觉审查 + 机械体检 + 签收（暗场同样适用） |
| `encode.js` / `encode.sh` | `../handdrawn-explainer-video/scripts/` | 帧序列 → MP4（无 bash 用 .js，两版探测/fallback 一致） |
| `grab.js` | `../handdrawn-explainer-video/scripts/grab.js` | 成片精确抽帧复核（`--acts` 每幕 1 张） |
| `merge-audio.sh` | `<项目根>/scripts/merge-audio.sh` | 混音/变速（配乐版规则） |
| ffmpeg/ffprobe | `<项目根>/tools/` | `encode.js` / `encode.sh` 自动向上探测 |

运行时：**Node ≥ 18**、`playwright-core`、本机 Chromium、ffmpeg。安装说明见 `../handdrawn-explainer-video/SKILL.md` §安装。

---

## 6. 四个 skill 的串联

| Skill | 接入点 |
|---|---|
| `series-video-planner` | 主题一集讲不完时，先拆集目（>180s 或 >1 个心智模型） |
| `handdrawn-explainer-video` | **并列关系**，按 §1 选型二选一；共享渲染脚本；题材不合适时互相让路 |
| **`dark-field-explainer-video`（本 skill）** | 暗场发光图文风格的单集全流程 |
| `douyin-cover-generator` | 成片后补封面，风格需对齐暗色 + 橙强调 |

---

## 7. 参考

- 参考片：`assets/「我爱你」说到第 1000 遍，信息量几乎为零.mp4`（1920×1080 / 30fps / 164s / 带 AAC 旁白 / 11Mbps）
- 风格拆解与实测参数：`references/style-spec.md`
- 分幕套路与代码：`references/scene-patterns.md`
- 生产经验与踩坑：`references/production-notes.md`
- 可直跑的工程模板：`templates/video-template.html`
