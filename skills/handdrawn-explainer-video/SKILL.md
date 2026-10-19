---
name: handdrawn-explainer-video
  
description: "把任意主题制作成 3 分钟以内的手绘卡通风格科普教学短片（JS + Canvas 逐帧渲染成 1080p MP4，无配音）。当用户要求'做个教学视频/科普短片/手绘动画视频/讲解视频'，或给出一个主题、文章链接希望生成讲解视频时使用。关键词：教学视频、科普视频、手绘动画、科普短片、Canvas 动画、讲解视频"
  
version: "1.6.0"
  
author: "CodeBuddy AI"
  
created: "2026-10-10"
  
changelog: "1.6.0 关键帧视觉审查门禁（源自《AI 逆向一切》两次返工的教训）：新增 scripts/keyframes.js（按幕+字幕自动选点出帧、联系表、空白/越界/压条/非确定性机械体检、逐张看过后 --approve 签收、签收绑定工程指纹）与 scripts/_review.js / _browser.js；render.js 全量渲染前强制校验签收（无签收/工程改过/帧被删一律拒绝，仅 --allow-unreviewed 显式跳过），新增 --clean、--review-dir，自检帧明确不当作审查证据；precheck.js 新增局部坐标误用（translate 块里画 circled/banner/chapterTitle）、字幕表时间轴与语速、渲染确定性三类检查；新增 Windows 可用的 scripts/encode.js（编码前验帧连续性+mtime、编码后校验帧数/yuv420p/音轨）与 scripts/grab.js（精确抽帧、--acts 每幕抽帧）；阶段 4 重写为「静态自检 → 关键帧审查签收」，阶段 5 加前置条件与双版本纪律；技术备忘 8 补双向坐标坑、新增 9~14（审查门禁成因、测试帧不可当证据、双版本同源同批、编码前验帧、Windows 别凑 bash、中文源码勿用管道批量替换）；产物目录新增 keyframes/。 1.5.0 迁入 vibe-video-skills 合集仓库（位于 skills/handdrawn-explainer-video/）：安装说明改为「clone 合集 + 链接 skill 目录」两种方式，补充同仓库另两个 skill（series-video-planner / douyin-cover-generator）的串联关系；本 skill 制作流程无功能变更。 1.4.0 新增 scripts/precheck.js 渲染前静态自检（用函数真实签名校验所有调用点，专治参数错位/漏参/时间基准错误，--dump 可打印参数绑定）；阶段 4 强制先跑 precheck；阶段 3 增加『API 签名速查表』与签名纪律；技术备忘新增第 7 条（参数错位类 bug 的成因与防护）。 1.3.1 阶段 3 字体引入支持 junction 零复制共享（Windows 推荐）或 copy 自包含二选一；技术备忘补充 rationale 与实测结论。 1.3.0 阶段 0 新增 research/ 原始调研留痕（每条来源一个 md：URL+摘要+原文摘录），调研材料数据点附引用链接，形成 成片→调研材料→原始来源 三层溯源链。 1.2.0 恢复『安装』章节(通用表述)、README 作品演示与参考文献；纳入 Git API 推送脚本与经验手册。 1.1.0 所有产物统一收纳到 <项目根>/<主题文件夹>/；路径去掉 /workspace 等 Linux 假设"  
---

# 手绘卡通教学视频生成器

> **Goal**：用户给一个主题（可附链接/材料），产出一部 **≤3 分钟、无配音、手绘卡通风格、初中生能看懂、开头有钩子** 的 1080p 科普教学短片 MP4，以及配套的调研材料与分镜脚本。

## 安装（Installation）

本 skill 是 [vibe-video-skills](https://github.com/JustChenk/vibe-video-skills) 合集仓库里的一个标准 **Agent Skill 包**（`SKILL.md` 清单 + 模板/脚本/字体等资源文件），位于仓库的 `skills/handdrawn-explainer-video/`。任何支持 Agent Skill 机制的 AI 编程助手都能加载它。安装方法 = **把 skill 目录放进所用工具的 skill 加载目录**。

**方式 A · 克隆一次 + 链接（推荐，与同仓库另两个 skill 共用一份）**

```bash
git clone https://github.com/JustChenk/vibe-video-skills.git ~/vibe-video-skills

# 用户级（对所有项目生效，以 CodeBuddy 为例）
ln -s ~/vibe-video-skills/skills/handdrawn-explainer-video ~/.codebuddy/skills/handdrawn-explainer-video
# Windows 零复制（无需管理员权限）：
#   mklink /J "%USERPROFILE%\.codebuddy\skills\handdrawn-explainer-video" "%USERPROFILE%\vibe-video-skills\skills\handdrawn-explainer-video"

# 项目级（仅当前项目生效）
cd <你的项目根目录>
ln -s ~/vibe-video-skills/skills/handdrawn-explainer-video .codebuddy/skills/handdrawn-explainer-video
```

**方式 B · 只取这一个 skill（sparse-checkout，不下载其余内容）**

```bash
git clone --filter=blob:none --sparse https://github.com/JustChenk/vibe-video-skills.git ~/.codebuddy/skills/vibe-video-skills
cd ~/.codebuddy/skills/vibe-video-skills && git sparse-checkout set skills/handdrawn-explainer-video
```

其他支持 Agent Skill 规范的工具安装方法完全相同，只是目录不同——把上面命令里的 `~/.codebuddy/skills/`（或 `.codebuddy/skills/`）换成所用工具的 skill 目录即可（例如 `~/.claude/skills/`、`~/.workbuddy/skills/`、项目级 `.dsh/skills/` 等，以各自文档为准）。

安装后新开会话即可被自动发现（Skill 名称：`handdrawn-explainer-video`）。用户说"做个教学视频 / 科普短片 / 手绘动画视频"并给出主题时即触发。

**同仓库的另两个 skill（可串联，也可单独用）**

| Skill | 作用 | 什么时候用 |
|---|---|---|
| `series-video-planner` | 大主题 → N 集系列视频的规划方法论（拆分逻辑/链接强度/勘误台账/进度表） | 主题一集讲不完（>180s 或 >1 个心智模型），要先拆集目 |
| **`handdrawn-explainer-video`（本 skill）** | 单集生产全流程：调研 → 分镜 → 动画 → 自检 → 渲染 → 交付 | 每集的实际制作 |
| `douyin-cover-generator` | 纯代码生成高点击封面（默认 3:4 竖版 1080×1440 + 4:3 横版 1920×1440） | 成片出来后补封面物料 |

**运行时依赖（首次使用前装一次）**

| 依赖 | 安装 | 用途 |
|---|---|---|
| playwright-core | `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i -g playwright-core` | 逐帧渲染（不会下载浏览器） |
| Chromium / Chrome | 本机已有即可；无则设 `CHROME_PATH` 指向可执行文件 | 渲染引擎（render.js 自动探测） |
| ffmpeg | `apt install ffmpeg` 或官网安装 | 帧序列合成 MP4（编码器自动 fallback） |
| Node.js ≥ 18 | 官网安装 | 运行 render.js |

## 产物目录约定（先读，全流程遵守）

**每部视频的全部产物统一收纳在项目根目录下一个以主题命名的文件夹中**，例如主题为"大模型认字"时：

```
<项目根>/<主题文件夹>/          # 如 D:/.../vibe视频制作/大模型认字/，主题名简短（≤10 字）
├── 调研材料.md                 # 阶段 0 产出（提炼稿，数据点附 research/ 引用链接）
├── research/                   # 阶段 0 产出（原始调研留痕，每条来源一个 md）
│   ├── 01-来源标题.md
│   ├── 02-来源标题.md
│   └── ...
├── 视频分镜脚本.md             # 阶段 2 产出
├── video.html                  # 动画工程（互动预览版）
├── scenes.js / framework.js / handdrawn.js
├── assets/fonts/*.ttf          # 手写字体（真实 copy 或指向 <skill>/assets 的 junction）
├── keyframes/                  # 阶段 4 关键帧视觉审查（逐帧 + 联系表 + 审查表 + 签收记录，出片后可删）
├── testframes/                 # 阶段 4 抽帧速览（交付后可删）
├── frames/                     # 阶段 5 全量帧（体积大，合成后可删）
└── <片名>.mp4                  # 阶段 5 成片
```

- **开工第一步就创建该文件夹**，此后调研材料、research/、分镜、工程、帧、成片全部写在其内，禁止散落到项目根目录、tmp/ 或其他位置
- 下文所有命令中的 `<主题文件夹>` 均指此目录；`<项目根>` 为当前工作目录
- frames/ 、testframes/ 、keyframes/ 是中间产物，交付确认后提醒用户可删（一部 170s 视频的 frames 约 1-2 GB）。
  注意：**删掉 keyframes/ 等于作废旧签收**，以后想重渲必须先重新出帧审查（这是刻意的设计，别图省事删它）。
- research/ 是溯源用的工作留痕，**仅本地保留，不随项目分发**（原文摘录有版权风险）；公开仓库的参考文献在 README 单独维护

## When to Use

- 用户要求"做一个教学/科普/讲解视频"、"做个手绘动画视频"
- 用户给出一个主题、文章、链接，希望转成视频内容
- 用户想"用 JS+Canvas 做动画短片"

## 硬性要求（不可妥协）

| # | 要求            | 落实方式                                                    |
| - | ------------- | ------------------------------------------------------- |
| 1 | **时长 ≤ 3 分钟** | 场景总时长 ≤180s，建议 150-175s，8 幕以内                           |
| 2 | **无声音**       | 不配音不配乐，所有信息靠画面与字幕传达；精力全花在画面上                            |
| 3 | **初中生能看懂**    | 禁用术语黑话，必要术语必须当场用类比解释（如"token = 带编号的拼图块"）；每屏 ≤2 行大字      |
| 4 | **开头有钩子**     | 第 1 幕（前 15s 内）必须制造认知冲突/悬念，见【钩子公式】                       |
| 5 | **材料不足主动搜索**  | 用户给的材料不够撑起 3 分钟叙事时，必须 WebSearch 补充调研，交叉验证事实             |
| 6 | **方向不明先沟通**   | 主题模糊/材料不足/有多种切入角度时，先用 AskUserQuestion 与用户确认，并给出 2-4 个选项 |

## 工作流（7 个阶段）

```
调研 → 分镜 → 动画 → ①静态自检 → ②关键帧视觉审查（签收）→ ③全量渲染 + 合成 + 成片复核 → 交付
```

### 阶段 0 · 素材解析与调研（必须做透）

1. **有链接** → WebFetch 全文抓取，提炼：核心问题、关键概念、数据点、案例、金句。
2. **有文件**（用户上传或项目内已有材料）→ Read 解析。
3. **材料不足以撑起 150s+ 叙事** → WebSearch 补充 2-4 轮：
   - 搜权威来源（论文、官方文档、一线技术博客）验证关键数字；
   - 搜类比案例和反常识事实（钩子和"收获感"都靠它们）；
   - **关键数据必须能溯源**，查不到的写"示意/约"，绝不杜撰精确数字。
4. **原始调研留痕（每个信息来源都要留）**：每处理一条来源（抓取的网页 / 搜索结果 / 用户材料），立即在 `<主题文件夹>/research/` 下建一个 md 文件，命名 `序号-来源标题.md`（如 `01-Tokenization综述.md`），结构统一：

   ```markdown
   # 来源标题
   - URL: https://...（用户本地材料写文件路径）
   - 抓取时间: YYYY-MM-DD
   - 类型: 全文抓取 / 搜索结果 / 用户材料

   ## 摘要
   一段话概括本来源核心内容、可信度判断

   ## 关键原文摘录
   > 被视频采用的关键句、数据、金句，保留原话（短文可全文照存；长综述只摘被采用部分）
   ```

   - 粒度自适应：短文全文照存，长综述存"摘要 + 被采用部分的原文摘录"，避免 research/ 膨胀；
   - 一条 WebSearch 命中多个有用结果时可合并为一个文件，逐条列出 URL 与摘录；
   - research/ 是本地溯源留痕，不随项目分发。
5. 产出调研材料写入 `<主题文件夹>/调研材料.md`（文件夹已按【产物目录约定】创建），结构：核心问题 / 关键概念 / 数据点与案例 / 金句 / 候选叙事线。**数据点、金句须在句末附来源引用**，格式：`（来源：[01-综述](research/01-xxx.md)）`，与 research/ 文件一一对应，形成"成片 → 调研材料 → 原始来源"三层溯源链。

### 阶段 1 · 方向确认（需要时，不省略判断）

出现以下任一情况，**先用 AskUserQuestion 沟通（每个问题给 2-4 个选项，推荐项放第一个）**：

- 主题太大，可讲角度有多个 → 选项：不同切入角度（如"原理科普"vs"避坑指南"vs"行业八卦"）
- 材料太薄，调研后仍撑不起 → 选项：补充方向 A/B/C，或缩短为 90s 快剪版
- 受众/用途不明 → 选项：大众科普 / 职场汇报 / 学生教学

主题明确且材料充分时，直接进入阶段 2 并在动手前用一段话向用户复述叙事线（标题+每幕一句话），确认即可，不要过度打扰。

### 阶段 2 · 分镜脚本

写入 `<主题文件夹>/视频分镜脚本.md`。分镜表每幕一行：时间码 / 章节 / 画面要点 / 字幕金句。

**叙事骨架（8 幕以内，总时长 ≤180s）**：

| 幕   | 时长       | 作用     | 内容                     |
| --- | -------- | ------ | ---------------------- |
| 1   | 12-17s   | **钩子** | 见下方钩子公式                |
| 2   | 20-28s   | 破题     | 解释核心概念（用类比，一次性说透）      |
| 3   | 22-30s   | 原理演示   | 核心机制/过程的分步动画演示         |
| 4-6 | 各 20-24s | 展开     | 2-3 个并列要点（代价/案例/对比/数据） |
| 7   | 15-18s   | 延伸     | 趋势/未来/怎么办              |
| 8   | 10-12s   | 收尾     | 金句 + 呼应开头钩子            |

**钩子公式（四选一）**：

- **AI 也会犯傻**：展示一个"人类秒答、AI/常识翻车"的现场（答题对比、错误演示）
- **反常识断言**："你以为 X，其实 Y"，配视觉冲击
- **灵魂拷问**：直接向观众抛一个答不上来的问题
- **天价数字**：一个具体到离谱的数字（"相差 54.3 倍"）

**通俗化技巧**：类比优先（拼图、切菜、搬砖、盖章）；数字具体化（不说"很多"说"94%"）；每个概念首次出现必须配一句人话解释；字幕口语化短句，避免书面语长句。

### 阶段 3 · 动画制作

**工程搭建**（在 `<主题文件夹>` 内执行，产物全部留在此文件夹）：

```bash
# <主题文件夹> = <项目根>/<主题名>，已在上一步创建
cd <主题文件夹>
cp <skill>/templates/handdrawn.js <skill>/templates/framework.js <skill>/templates/video.html .
cp <skill>/templates/scenes_example.js scenes.js   # 作为改写起点
# 三款手写字体（必须，防豆腐块），两种方式二选一：
#   方式 A · Windows（推荐）：junction 零复制，磁盘只存一份
#     cmd //c "mklink /J assets <skill>/assets"    # Git Bash 语法；PowerShell 用 New-Item -ItemType Junction
#   方式 B · 任意平台：直接 copy（工程自包含，可整体拷走）
#     cp -r <skill>/assets .
```

**然后重写 scenes.js 中的场景函数**（scenes_example.js 是完整参考实现，含 tile/dashLine/stamp 等辅助函数）。改动点只有三个：

1. `scenes.js`：重写 scene1..sceneN（参考示例的场景模式，见下）
2. `framework.js` 顶部 `SCENES` 数组：改场景数与各幕 start/dur
3. `video.html`：`window.VIDEO_HEADER` 页眉文字

**关键约定（违反会出 bug）**：

- **调用任何绘制函数前先核对签名**（见下方速查表 / `handdrawn.js` 顶部签名表）。这些函数参数多、且不少参数带默认值，**少传或错位时 JS 不报错**，只会表现为"文字不见了"或"画面上凭空多了个数字"。这是本库最高频的 bug，写完必须跑阶段 4 的 `precheck.js`。
- 场景函数接收**全局时间 t**，内部所有 `seg(t, a, b)` 的时间点与 SCENES 的 start/dur 一致——不要把场景起始时间当成 0
- 所有随机效果经 `seed` 参数驱动（保证同一帧可复现，逐帧录制不闪烁）；新元素出现时配合 `easeOutBack(seg(...))` 弹跳
- 元素层级顺序：背景 → 场景 → wipe 转场 → 进度条（框架已处理）
- 字体：`ZCOOL KuaiLe`（中文正文）、`Patrick Hand`（英文/数字）、`Caveat`（英文标题），`handText` 内部已对 null 的 color/font 做了兜底
- 构图安全区：x∈[80,1840], y∈[70,1000]（底部 1050 是进度条）；一屏信息量宁可拆两幕不要硬塞
- **在 ctx 已被 translate/scale 的局部坐标系里绘制的元素（价签、徽章、卡片内部文字），传给 handText 的应是【局部坐标】（如 `0,2` / `10,2`），不要传页面绝对坐标**，否则文字会跑到画面外

**API 签名速查表（易错项，完整表见 `handdrawn.js` 顶部注释）**：

| 函数 | 签名 | 易错点 |
|---|---|---|
| `handText` | `(ctx, txt, x, y, size, o)` | 第 2 个是**文本**；x/y 是文本锚点，不是内容 |
| `priceTag`* | `(ctx, x, y, txt, seed, o)` | 项目自定义；内部用局部坐标画字 |
| `badge`* | `(ctx, x, y, s, txt, seed, o)` | **第 4 个是缩放 s**，第 5 个才是文本！漏了 s 就会把 seed 画成数字 |
| `chapterTitle` | `(ctx, txt, t, a, b, seed, sub)` | 第 3 个是**全局时间 t**；`sub` 可传字符串或 `{sub:'..'}` |
| `banner` | `(ctx, y, txt, t, a, b, seed, o)` | **没有 x 参数**！多传一个 x 会让所有参数整体错位 |
| `sticky` | `(ctx, x, y, w, h, seed, o)` | 文本走 `o.label`，不是位置参数 |
| `tokenCard` | `(ctx, x, y, w, h, o)` | 文本走 `o.label` / `o.num` / `o.sub` |
| `jdot` | `(ctx, x, y, r, color, alpha)` | color 是位置参数，不是 o.color |
| `drawMug`* | `(ctx, x, y, s, seed, o)` | 文本走 `o.label` |

> `*` 标记的是**项目自定义辅助函数**（不在库里，需自己写）。`precheck.js` 会把它们一并纳入校验，所以自定义 helper 也要保持"文本靠前、数值靠后、文本配数值位"的签名习惯。

**书写习惯（能天然避免错位）**：把 helper 的签名统一成 `(ctx, x, y, [数值参数...], txt, seed, o={})`，即**文本永远紧跟数值之后、seed 之前**；调用点写完后立刻跑 `precheck.js`。

**视觉风格参数**（handdrawn.js 已内置，直接用）：

- 奶油纸底 `#FBF4E6`、墨色 `#3B3229`；强调色：红 `#E4572E` 黄 `#F5B82E` 蓝 `#2E7DD1` 绿 `#3E9B4F` 紫 `#8A5FB0`
- 手绘抖动每秒 8 次换 seed（boiling lines）；线条用 `jline/jcircle/jrr/strokePts` 系列
- 常用组件：`chapterTitle`（章节贴纸）、`bubble`（对话气泡）、`sticky`（便利贴）、`tokenCard/tile`（卡片）、`drawArrow`（手绘箭头）、`drawCheck/drawCross`（勾叉）、`circled`（红圈标注）、`drawHuman/drawRobot`（角色）、`drawBurst`（火花）

**场景模式库**（套用即可）：

- *对比幕*：左右分栏（人类 vs 机器 / 方案 A vs B），下方各一个角色 + 卡片
- *流程幕*：输入 → 手绘机器/箭头 → 输出（token 掉落、合并动画）
- *数据幕*：手绘条形图生长动画 + 大数字贴纸卡 + 小人搬砖等具象化
- *卡片幕*：3 张竖卡横排依次弹出（并列要点/方案对比）
- *金句幕*：居中大字 + 红色描画下划线 + 小元素呼应开头

### 阶段 4 · 自检（不可跳过）—— 静态查错 → **关键帧视觉审查签收** → 才允许全量渲染

> **这一阶段有硬门禁。** 2026-10-19《AI 逆向一切》两次返工的直接原因就是：静态脚本全绿、随手抽两个时间点看过，
> 就开全量渲染，结果红圈飞到画面右下角、箭头端点啃进卡片——只有把每一幕的帧**当图片看**才发现。
> 于是本 skill 把"审过图"固化成签收记录，`render.js` 全量渲染前会校验它。

#### 第 1 步（必做）：静态自检

```bash
cd <主题文件夹>
node <skill>/scripts/precheck.js scenes.js handdrawn.js framework.js
# 退出码 0 才继续；报 ERROR 必须先修，否则错误会以
# "画面上凭空多个数字 / 某段文字消失"的形式混进成片，肉眼极易误判成设计元素
```

`precheck.js` 检查这些事（用**函数真实签名**校验，不硬编码）：

1. **参数错位**：数值位传了字符串（如漏传 `badge` 的 `s`，`'卖方'` 落到缩放位）、文本位传了数字（seed 被画成文字）——**这一类就是历史高频 bug**
2. **参数个数**：少于必填参数个数
3. `SCENES` 时间轴连续性、`sceneN` 是否都有定义、总时长是否 ≤180s
4. **时间基准**：场景函数是否误用了幕内相对时间（该幕会整段空白）
5. **局部坐标 vs 页面坐标**（新增）：在 `ctx.translate` 块里调用 `circled / banner / chapterTitle` 且传页面级大坐标 → 元素会被再平移一次飞走（实战：红圈跑到右下角）；块内 `handText` 用页面坐标画字 → WARN
6. **字幕表自检**（新增）：`CAPTIONS_LIST` 时间重叠、超出总时长、单条停留 <1.2s、语速 >6.5 字/秒、空档过长
7. **确定性**（新增）：渲染路径里出现 `Math.random()` → ERROR（逐帧录制会闪、抽帧与成片对不上）

排查单个函数时用 `--dump` 看参数绑定：

```bash
node <skill>/scripts/precheck.js scenes.js handdrawn.js framework.js --dump badge
# 打印每个 badge() 调用点，逐参数显示"形参名 <= 实参"
```

#### 第 2 步（必做）：关键帧视觉审查 —— 出图 → **逐张看** → 签收

```bash
cd <主题文件夹>
# ① 自动选点出图（每幕 3 张 + 每条字幕入场后 1 张，双版本工程各跑各的）
node <skill>/scripts/keyframes.js ./video.html ./keyframes --srt ./<字幕>.srt
#    产物：keyframes/kf_<秒>s.jpg（逐帧）、keyframes/_联系表.jpg（一张图看全片）、
#          keyframes/_关键帧审查.video.md（审查表，含机械体检结论）
```

`keyframes.js` 做的事：

- **自动选点**：按 `SCENES`/`TIMELINE` 的幕边界，每幕取 `20% / 55% / 90%`（避开 wipe 转场窗口）；
  有 SRT 时按每条字幕入场后 0.6s 补帧 —— **每一幕都被覆盖**，不靠人拍脑袋挑时间点。
- **机械体检**（拦的是硬伤，不是审美）：空白幕（非底色 <0.6%）、画面被填满、画面最外 8px 有内容（出界/裁切）、
  左右安全区外有内容、底部进度条被压、**同一 t 连渲两次不一致（非确定性）**。
- **联系表**：把 30~40 张帧拼成一张长图，**先 Read 这一张**扫全片节奏，再对可疑幕放大看单帧。

**然后必须逐张 Read 审查帧**（或先看联系表、再放大可疑项），检查清单：

- [ ] 文字无重叠、无被遮挡、无超出卡片/屏幕边界
- [ ] **画面上没有"看不懂的数字/字母"**——凡是无法解释其含义的数字（如凭空出现的 `304`），一律当 bug 追查
- [ ] **每个本该有文字的元素都真的有字**：徽章、价签、卡片、贴纸逐个确认（文字消失也是错位的一种表现）
- [ ] **标注类元素（红圈/箭头/下划线）确实指向它要标的东西**——飞到画面角落、啃进卡片、压在文字上，都算错
- [ ] 同一张卡片里的图标与文字不重叠（图标宽度要按实际绘制范围留白，别只留 60px）
- [ ] 无字体豆腐块（□）；每个场景的关键时间点都有内容（无意外空白帧）
- [ ] 错别字、数字与调研材料一致；场景切换前后 1s 内画面不穿帮
- [ ] 字幕版：字幕条不压主内容、不压进度条、不被大标题遮住

发现问题改代码后，**回到第 1 步重跑 precheck、再重跑 keyframes.js**（帧会重新生成），直到干净。然后签收：

```bash
node <skill>/scripts/keyframes.js ./video.html ./keyframes --approve "逐张看过：8 幕 40 帧，无错位/无多余数字"
# 签收记录 keyframes/_keyframe_review.video.json 里写死了工程指纹（html + js + 字体内容哈希）
```

> **签收 = 对这版画面负责。** 之后只要改任何一个 js/html，指纹就变，签收自动作废，
> `render.js` 会拒绝全量渲染 —— 这是为了逼出"改了又没重看"这种最贵的返工。
> 有机械 WARN 时可用 `--strict` 让签收也拒绝，直到 WARN 清完。

#### 第 3 步（可选）：抽帧速览

`render.js --test` 出的 `testframes/` 只适合**开发中途看问题**，**不能当审查证据**（它不覆盖每一幕，也没有签收机制）：

```bash
cd <主题文件夹>   # 首次需先安装渲染依赖：PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright-core
node <skill>/scripts/render.js ./video.html ./testframes --test "3,8,24,58,80,110,130,150,166"
# 测试帧落在 <主题文件夹>/testframes/，Read 逐张检查
```

### 阶段 5 · 全量渲染与合成（**前置条件：阶段 4 已签收**）

```bash
cd <主题文件夹>
# 全量渲染（4080 帧约 3 分钟，建议 run_in_background）：
# ⚠️ 这一步会被门禁拦住：没有有效的关键帧签收 → 直接拒绝渲染（见阶段 4 第 2 步）
node <skill>/scripts/render.js ./video.html ./frames --fps 24 --dur <总时长> --clean
#   --clean 先清空帧目录：防止上次的旧帧和新帧混在一起（补渲时最容易被坑）
#   确需只补渲一小段（不推荐）：加 --allow-unreviewed 跳过门禁；补渲后仍要重跑 keyframes.js 并重新签收

# 合成（Node 版，Windows 无 bash 也能跑；探测规则与 encode.sh 一致）：
node <skill>/scripts/encode.js ./frames 24 "./<片名>.mp4" 4.5M
#   Linux/macOS 有 bash 也可以用：bash <skill>/scripts/encode.sh ./frames 24 "./<片名>.mp4" 4.5M

# 成片抽帧复核（每幕中段各抽 1 张 → grab/，再和 keyframes/ 的审查帧比对）：
node <skill>/scripts/grab.js "./<片名>.mp4" --acts --html ./video.html
```

`encode.js` 会在编码前验帧（帧号连续、无缺口、mtime 不跨天）并在编码后校验成片（帧数 / 分辨率 / `yuv420p` / 有无音轨）。

**双版本工程（字幕版 + 无字幕版）的纪律**：

1. 两版**必须同源、同批重渲**：改了一处画面就两版都重跑 `keyframes.js` → 都签收 → 都全量渲染，否则一版有修复一版没有。
2. 签收是**按入口 html 名分开**的（`_keyframe_review.video.json` / `_keyframe_review.video_captions.json`），各有各的指纹。
3. 帧目录要分别存在（`frames/` 与 `frames_captions/`）；补渲覆盖前先确认目标目录存在，否则一次覆盖失败会把整版废掉。

### 阶段 6 · 交付

`present_files` 依次给出：`<主题文件夹>/<片名>.mp4` → video.html（互动预览版）→ 视频分镜脚本.md → 调研材料.md → 源码 js。总结里写清：时长/分辨率/每幕一句话/制作方式/如何修改复用；并提示 frames/、testframes/、keyframes/ 可删以释放空间（**但删了 keyframes/ 签收就作废，重新渲染要重新审**）。

## 技术备忘（已踩过的坑）

1. **场景时间轴**：`draw()` 传的是全局 t，场景函数里别再用 `t - scene.start`。
2. **libx264 可能不存在**：encode.sh 已内置 fallback 链，直接用。
3. **字体必须本地可加载**：Google Fonts CDN 在无头浏览器逐帧截图时可能加载不完整；用 `@font-face` 本地 ttf + `document.fonts.load()` 显式等待。字体文件可 copy 进主题文件夹（自包含），Windows 下也可对 `<skill>/assets` 建 NTFS junction 零复制共享（实测 file:// 渲染正常；junction 方案下工程依赖 skill 安装路径存在，拷给他人时需还原为真实 copy）。
4. **圆角矩形路径**：`buildRoundRectPts` 的四角弧必须连续顺时针（库内已修正，不要改回旧写法），否则卡片呈"旗帜状"。
5. **非拉丁文字渲染风险**：生僻文字（缅文、稀有符号）在精简 Linux 字体环境下会变豆腐块，改用中文标签描述。
6. **渲染性能**：约 24 帧/秒（1080p），170s 视频 ≈ 3 分钟渲染；超长任务用 run_in_background。
7. **参数错位（本库最高频 bug，务必理解机理）**：库函数参数多、且大量参数带默认值，例如
   - `handText(ctx, txt, x, y, size, o)`
   - `banner(ctx, y, txt, t, a, b, seed, o)` ← **没有 x**
   - `badge(ctx, x, y, s, txt, seed, o)` ← 第 4 个是缩放 `s`，第 5 个才是文本

   凭直觉调用时极易"少传中间一个参数"，此时 **JS 不抛错**：后面每个实参整体前移，于是
   ① 本该显示的文字落进数值位 → 文字静默消失（看起来像"这个元素没设计文字"）；
   ② 本该是 seed/size 的数字落进文本位 → **画面上凭空多出一个数字**（如 `304`）。
   两个症状都很容易被误判成设计效果而放过，因此：
   - 动手写调用点前先查 `handdrawn.js` 顶部签名表与 SKILL 的《API 签名速查表》；
   - 写完立刻跑 `node <skill>/scripts/precheck.js`（会校验调用点参数个数与位置类型，并覆盖项目自定义 helper）；
   - 自检阶段看到任何"无法解释含义的数字"，一律按 bug 追查，可用 `--dump <函数名>` 看参数绑定；
   - 自定义 helper 统一按 `(ctx, x, y, [数值...], txt, seed, o={})` 的次序写，文本紧跟数值、始终在 seed 之前。
8. **局部坐标 vs 绝对坐标（两个方向都会踩）**：
   - 方向一：凡在 `ctx.translate/scale` 之后绘制的元素（价签、徽章、卡片内文字），传给 `handText` 的必须是**局部坐标**（`0,2`、`10,2` 这类）。混用绝对坐标会让文字跑到画面外或压在别的元素上。
   - 方向二：`circled`（强调圈）、`banner`（横幅）、`chapterTitle`（章节贴纸）语义上就是**页面级组件**，必须在 `ctx.restore()` **之后**用页面坐标调用；写进 translate 块里会被再平移一次 → 元素飞到画面右下角。实战：第 5 幕五步流水线的红圈整个飞到 (1750,750)，静态脚本全绿，只有看图才发现。`precheck.js` 已能静态拦这两类。

9. **关键帧审查是硬门禁，不是走过场（2026-10-19 两次返工的教训）**：
   - 事故链：静态 precheck 全绿 → 随手抽 2~3 个时间点看过 → 全量渲染 + 合成 → 人看片发现红圈错位 / 箭头锚点错 → 改代码 → 重渲 → 重编 → 双版本一起返工。
   - 根因不是"没检查"，而是**检查点选得随意**：恰好看的那几张没覆盖出事的那一幕。
   - 现在的纪律：`keyframes.js` 按幕自动选点（每幕 ≥3 张 + 每幕字幕 1 张）→ **逐张 Read** → `--approve` 签收（写入工程指纹）→ `render.js` 校验签收才肯全量渲染。改任何 js/html 指纹即变，签收自动作废，想跳过只能显式 `--allow-unreviewed`。

10. **别拿"测试帧"当审查证据**：`render.js --test` 只出你点名的几个时间点，**不保证覆盖每一幕**，也没有签收与机械体检。它适合改代码时快速看一眼；出片前的审查必须走 `keyframes.js`。

11. **双版本工程同源同批**：一套工程出「字幕版 + 无字幕版」时，任何画面修复都要两版一起重渲重编。历史教训：只补了无字幕版，字幕版还带着错位红圈；且补渲时若目标帧目录已被清空，`copy` 会抛几百行错而旧帧还在被后台渲染覆盖，最后只能整集重渲。

12. **编码前验帧数**：`帧数 = 总时长 × fps`，且整批帧 mtime 应集中在一个时间簇（一次渲染出来的）。数字不对 / 跨天的旧帧混进来，会让幕序整体错乱，而 ffprobe 一切正常、极难诊断。`encode.js` 现在会自动检查并在失败时报错。

13. **Windows 上别硬凑 bash**：没有 bash 时 `encode.sh` 跑不了，手敲 ffmpeg 容易漏 `-pix_fmt yuv420p` / `-movflags +faststart`。用 `node <skill>/scripts/encode.js`（探测与 fallback 逻辑与 sh 版一致）。同理抽帧别在 PowerShell 里拼 `"$T\vid_$t.jpg"`——`$t` 会被并进路径变成 `路径\97\...`，用 `grab.js`。

14. **编辑含大量中文的源文件时，别用"读出来 → 正则替换 → 写回去"这种管道**（2026-10-19 亲身事故）：PowerShell 在无 BOM 的 UTF-8 文件上会按系统代码页（GBK）解码，再以 UTF-8 写回，**整个文件的中文变成乱码，引号被吃掉一半，JS 直接语法错误**。改中文源码一律用 `edit` 工具（按 UTF-8 精确替换）；必须用脚本批量改时，先 `[System.IO.File]::ReadAllText($p,[System.Text.Encoding]::UTF8)` 读、`WriteAllText($p,$t,(New-Object System.Text.UTF8Encoding($false)))` 写，并先备份。

## 验收清单（交付前逐项过）

- [ ] **`node <skill>/scripts/precheck.js scenes.js handdrawn.js framework.js` 退出码为 0**（无参数错位/无时间轴断裂/无空白幕/无绝对坐标误用/字幕表无重叠）
- [ ] **`keyframes.js` 出过审查帧，且逐张 Read 过**；`keyframes/_keyframe_review.<入口>.json` 的指纹与当前工程一致（`render.js` 门禁能放行）
- [ ] **画面上的每个数字都能说清含义**；每个该有文字的元素都真的有字；红圈/箭头确有所指
- [ ] 时长 ≤ 180s，24fps，1920×1080，H.264，yuv420p，faststart
- [ ] 无任何音轨
- [ ] 第 1 幕 15s 内有明确钩子
- [ ] 每个专业概念都有类比解释；抽查一个初中生能复述大意
- [ ] 关键数据与调研材料一致，无杜撰，且每个数据点都能沿 research/ 引用链回溯到原始来源
- [ ] 结尾有金句且呼应开头
- [ ] 双版本（如出）画面同源、都已重渲重编
- [ ] 调研材料 md + 分镜脚本 md + 互动预览 html 一并交付
- [ ] 所有产物都在 `<项目根>/<主题文件夹>/` 内，项目根目录无散落文件
