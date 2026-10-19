# handdrawn-explainer-video

把任意主题制作成 **3 分钟以内的手绘卡通风格科普教学短片**（JS + Canvas 逐帧渲染，1080p MP4，无配音）。

> 成品示例主题：《大模型是怎么"认字"的？—— Token 手绘科普》（基于 Google 等机构 154 页 Tokenization 综述）

## 🎬 作品演示

- **《大模型是怎么"认字"的？》**（AI / 科普 / 手绘动画 · 2 分 50 秒 · 无配音）
  抖音观看 👉 [https://v.douyin.com/FLSXm0kx4aQ/](https://v.douyin.com/FLSXm0kx4aQ/)

## ✨ 特性

- 🎨 **纯代码手绘风**：抖动线条（boiling lines）、弹跳入出场、描画动画、纸张擦除转场、便利贴/气泡/手绘角色组件
- ⏱️ **确定性渲染**：同一时刻永远渲染出同一帧，逐帧录制零闪烁
- 🔇 **无配音**：全部信息靠画面与字幕传达，静音也好看
- 🧒 **零门槛**：类比优先 + 大数字 + 每屏一句话，初中生也能看懂
- 🪝 **钩子开场**：认知冲突式开头，让人想看下去
- 🔎 **三层溯源**：research/ 原始来源留痕 → 调研材料（数据点附引用链接）→ 成片，每个数字都能回溯到出处
- 🛡️ **关键帧视觉审查门禁**：按幕自动出帧（每幕 3 张 + 每幕字幕 1 张）、拼一张联系表、跑空白/越界/压条/非确定性机械体检；
  逐张看过 `--approve` 签收（绑定工程指纹）后 `render.js` 才肯全量渲染，改了代码签收自动作废

## 📦 结构

```
handdrawn-explainer-video/
├── SKILL.md                 # 完整工作流手册（调研→分镜→动画→自检→渲染→交付）
├── templates/
│   ├── handdrawn.js         # 手绘工具库（线条/卡片/角色/箭头/贴纸等）
│   ├── framework.js         # 通用主框架（场景调度/转场/进度条）
│   ├── scenes_example.js    # 完整示例场景（Tokenization 主题 8 幕）
│   └── video.html           # 页面模板（支持 ?play 交互预览）
├── assets/fonts/            # 三款手写字体（本地化，离线可渲染）
│   ├── ZCOOLKuaiLe.ttf      # 中文正文
│   ├── PatrickHand.ttf      # 英文/数字
│   └── CaveatBold.ttf       # 英文标题
└── scripts/
    ├── precheck.js          # 静态自检（签名/时间轴/坐标误用/字幕表/确定性）
    ├── keyframes.js         # 关键帧视觉审查：出帧 + 联系表 + 机械体检 + 签收/校验
    ├── render.js            # Playwright 逐帧渲染（全量渲染前校验签收）
    ├── encode.js            # 帧序列 → MP4（Node 版，Windows 无 bash 可用）
    ├── encode.sh            # 同上（bash 版，Linux/macOS）
    ├── grab.js              # 成片精确抽帧复核（--acts 每幕抽 1 张）
    └── _browser.js / _review.js  # 上面几个脚本共用的浏览器探测与签收校验
```

## 📥 安装为 Skill

本 skill 位于 [vibe-video-skills](https://github.com/JustChenk/vibe-video-skills) 合集仓库的 `skills/handdrawn-explainer-video/`，是标准的 **Agent Skill 包**。安装 = 把 skill 目录放进对应工具的 skill 加载目录，下面以 CodeBuddy 为例：

```bash
# 克隆合集一次
git clone https://github.com/JustChenk/vibe-video-skills.git ~/vibe-video-skills

# 方式 A：用户级（所有项目可用，推荐）
ln -s ~/vibe-video-skills/skills/handdrawn-explainer-video ~/.codebuddy/skills/handdrawn-explainer-video
# Windows：mklink /J "%USERPROFILE%\.codebuddy\skills\handdrawn-explainer-video" "%USERPROFILE%\vibe-video-skills\skills\handdrawn-explainer-video"

# 方式 B：项目级（仅当前项目可用）
cd <项目根目录>
ln -s ~/vibe-video-skills/skills/handdrawn-explainer-video .codebuddy/skills/handdrawn-explainer-video

# 方式 C：只取这一个 skill（sparse-checkout）
git clone --filter=blob:none --sparse https://github.com/JustChenk/vibe-video-skills.git ~/.codebuddy/skills/vibe-video-skills
cd ~/.codebuddy/skills/vibe-video-skills && git sparse-checkout set skills/handdrawn-explainer-video
```

其他工具（如 Claude Code、OpenCode、WorkBuddy 等）安装方法相同，只需把路径换成各自的 skill 目录（如 `~/.claude/skills/`、`~/.workbuddy/skills/`、项目级 `.dsh/skills/`）。新开会话后自动生效；对 AI 说 **"把 XX 主题做成教学/科普视频"** 即触发。
运行时依赖：`playwright-core`（`npm i -g playwright-core`）、Chromium/Chrome（自动探测）、`ffmpeg`、Node.js ≥ 18。详见 [SKILL.md 的安装章节](SKILL.md)。

同仓库另两个配套 skill：[`series-video-planner`](../series-video-planner/)（大主题拆成系列）、[`douyin-cover-generator`](../douyin-cover-generator/)（成片封面，默认 3:4 竖版 + 4:3 横版）。

## 🚀 快速开始

**约定：每部视频的全部产物（调研/分镜/工程/帧/成片）统一放在项目根下一个以主题命名的文件夹**，如 `my-video/`。

```
my-video/
├── 调研材料.md          # 提炼稿：核心问题/数据点/金句，数据点附 research/ 引用链接
├── research/            # 原始调研留痕（每条来源一个 md：URL+摘要+原文摘录；仅本地，不随项目分发）
├── 视频分镜脚本.md
├── video.html / scenes.js / framework.js / handdrawn.js
├── keyframes/           # 关键帧审查（逐帧 + 联系表 + 审查表 + 签收记录）
├── frames/  testframes/ # 渲染中间产物，交付后可删
└── my-video.mp4         # 成片
```

```bash
# 1. 搭工程（在主题文件夹内）
mkdir my-video && cd my-video
cp <skill>/templates/handdrawn.js <skill>/templates/framework.js <skill>/templates/video.html .
cp -r <skill>/assets .
cp <skill>/templates/scenes_example.js scenes.js

# 2. 静态自检（退出码 0 才继续）
node <skill>/scripts/precheck.js scenes.js handdrawn.js framework.js

# 3. 关键帧视觉审查：出帧 + 联系表 + 审查表 → 逐张 Read → 签收（必做）
node <skill>/scripts/keyframes.js ./video.html ./keyframes
node <skill>/scripts/keyframes.js ./video.html ./keyframes --approve "逐张看过，无错位"

# 4. 全量渲染 + 合成（无签收会被 render.js 直接拒绝）
node <skill>/scripts/render.js ./video.html ./frames --fps 24 --dur 170 --clean
node <skill>/scripts/encode.js ./frames 24 ./my-video.mp4 4.5M      # 或 bash scripts/encode.sh …
node <skill>/scripts/grab.js ./my-video.mp4 --acts --html ./video.html   # 成片抽帧复核
```

详细制作规范（叙事骨架、钩子公式、场景模式库、踩坑备忘）见 [SKILL.md](SKILL.md)。

## 🎬 制作管线

```
主题/材料 ──调研──► 分镜脚本 ──JS+Canvas──► 确定性动画
     → precheck 静态自检 → keyframes 关键帧审查+签收 → Playwright 逐帧截图（4080 帧）──ffmpeg──► 1080p24 MP4
     → grab 成片抽帧复核    （画面没审过，渲染这一步会被门禁拦下）
```

## 📚 参考文献

示例视频《大模型是怎么"认字"的？》所依据的资料（仅在此列出，不随项目分发）：

1. Datawhale《这是一篇把"Token"讲明白的科普级综述！》 — [mp.weixin.qq.com](https://mp.weixin.qq.com/s/4FANqjqQevlNEaVg7-HqSA)
2. *Tokenization Survey: Modern NLP*（Google 牵头，20+ 机构，32 位作者，154 页综述） — [alphaxiv.org](https://www.alphaxiv.org/zh/abs/2609.tokenization-survey-modern-nlp)
3. Andrej Karpathy, *Let's build the GPT Tokenizer*（2024 教程） — [YouTube](https://www.youtube.com/watch?v=zduSFxRajkE)
4. Sennrich et al., *Neural Machine Translation of Rare Words with Subword Units*（BPE, ACL 2016） — [arXiv:1508.07909](https://arxiv.org/abs/1508.07909)
5. Kudo & Richardson, *SentencePiece*（EMNLP 2018） — [arXiv:1808.06226](https://arxiv.org/abs/1808.06226)
6. Petrov et al., *Language Model Tokenizers Introduce Unfairness Between Languages*（2023） — [arXiv:2305.15425](https://arxiv.org/abs/2305.15425)

## 📄 License

MIT
