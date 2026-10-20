# vibe-video-skills

一站式 **AI 视频制作 Agent Skill 合集**：从「大主题拆成系列」→「单集手绘科普短片渲染」→「成片封面」，把整条视频生产链路沉淀成可复用的技能包。

> 纯代码管线（HTML + Canvas + Playwright + ffmpeg），确定性渲染、可复现、零外部生成能力依赖。

## 📦 包含的 Skill

| Skill | 一句话作用 | 触发场景（关键词） |
|---|---|---|
| [**handdrawn-explainer-video**](skills/handdrawn-explainer-video/) | 把任意主题做成 ≤3 分钟手绘卡通风格科普教学短片（JS + Canvas 逐帧渲染 1080p MP4，无配音） | 教学视频、科普短片、手绘动画、讲解视频 |
| [**dark-field-explainer-video**](skills/dark-field-explainer-video/) | 黑场发光字 + 数据可视化 + 粒子流场风格的科技感动态图文短片（又称 Opus5.5 风） | 暗场视频、发光字、科技感、数据可视化、Opus5.5 |
| [**series-video-planner**](skills/series-video-planner/) | 把万字长文 / 大专题拆成 N 集系列视频并做成合集的方法论（拆分逻辑 + 链接强度 + 双线制作） | 系列视频、视频合集、分集、多集视频、大主题拆分 |
| [**qwen-tts-voiceover**](skills/qwen-tts-voiceover/) | 本地 Qwen3-TTS 克隆指定音色给 SRT 逐句配音，并让**字幕/画面/音频严格同步**（三级对齐 + 重渲染） | 音色克隆、配音、配音版、音画同步、Qwen3-TTS、voice clone |
| [**bgm-beat-align**](skills/bgm-beat-align/) | 配乐卡点：量化 BPM/拍网格，把幕边界贴到节拍上，产出 A/B/C 板决策并一键合成 | 配乐、卡点、BGM、节拍、卡点版 |
| [**douyin-cover-generator**](skills/douyin-cover-generator/) | 纯代码生成高点击率封面，默认 **3:4 竖版（1080×1440）+ 4:3 横版（1920×1440）** 一套两张 | 抖音封面、生成封面、视频封面、缩略图、做封面 |
| [**douyin-publisher**](skills/douyin-publisher/) | 抖音成品批量发布：生成清单 → 填标题话题 → 批量上传（dry-run 默认，含风控纪律） | 发布抖音、批量上传、定时发布 |

### 完整链路

```
大主题（万字长文/大部头）
        │
        ▼  ① series-video-planner
   集目清单 + 系列规划.md（拆分逻辑 / 链接强度 / 勘误台账 / 进度表）
        │
        ▼  ② handdrawn-explainer-video 或 dark-field-explainer-video   ← 逐集执行
   调研材料.md + research/ + 分镜脚本 + 动画工程 + 无声成片.mp4
        │
        ├──▶ ③ qwen-tts-voiceover（可选）音色克隆配音 + 音画同步 → 配音版.mp4
        │        └──▶ bgm-beat-align  叠 BGM 卡点 → _卡点版.mp4
        │
        ├──▶ ④ douyin-cover-generator  封面 ×2
        │
        ▼  ⑤ douyin-publisher（可选）批量发布
```

- 单集讲得完的主题：跳过 ①，直接 ②（+ ③④）
- 需要配音：② 产出无声成片 → ③ 重配音并重建时间轴（**会重渲染**）
- 每个 skill 都能**单独使用**，互不依赖，只是串起来最省事

## 📁 目录结构

```
vibe-video-skills/
├── skills/
│   ├── handdrawn-explainer-video/    # 单集手绘科普短片生产（含字体与渲染脚本）
│   ├── dark-field-explainer-video/   # 暗场发光字 / 数据可视化风格
│   ├── series-video-planner/         # 大主题 → 系列视频规划方法论
│   ├── qwen-tts-voiceover/           # 音色克隆配音 + 音画同步
│   ├── bgm-beat-align/               # 配乐卡点分析与合成
│   ├── douyin-cover-generator/       # 封面生成（Canvas 渲染）
│   └── douyin-publisher/             # 抖音批量发布
├── scripts/
│   └── api_push.py                   # 仓库维护：沙箱内走 GitHub REST API 推送
├── docs/
│   └── git-sync-playbook.md          # 沙箱环境 Git/GitHub 同步踩坑与解法
├── LICENSE
└── README.md
```

## 🚀 安装

本仓库是标准的 **Agent Skill 包合集**：`skills/<name>/SKILL.md` 是清单，其余是资源文件。安装 = **把每个 skill 目录放进所用工具的 skill 加载目录**。

**方式 A · 克隆一次 + 链接（推荐，三处共用一份，改一处全局生效）**

```bash
git clone https://github.com/JustChenk/vibe-video-skills.git ~/vibe-video-skills

# 把需要的 skill 链接进加载目录（以 CodeBuddy 用户级为例）
ln -s ~/vibe-video-skills/skills/handdrawn-explainer-video  ~/.codebuddy/skills/handdrawn-explainer-video
ln -s ~/vibe-video-skills/skills/series-video-planner       ~/.codebuddy/skills/series-video-planner
ln -s ~/vibe-video-skills/skills/douyin-cover-generator     ~/.codebuddy/skills/douyin-cover-generator
```

Windows（零复制，无需管理员权限）：

```cmd
mklink /J "%USERPROFILE%\.codebuddy\skills\handdrawn-explainer-video" "%USERPROFILE%\vibe-video-skills\skills\handdrawn-explainer-video"
```

其他工具只是目录不同（`~/.claude/skills/`、`~/.workbuddy/skills/`、项目级 `.dsh/skills/` 等，以各自文档为准）。

**方式 B · 只装一个 skill（sparse-checkout，不下载其余内容）**

```bash
git clone --filter=blob:none --sparse https://github.com/JustChenk/vibe-video-skills.git ~/.codebuddy/skills/vibe-video-skills
cd ~/.codebuddy/skills/vibe-video-skills
git sparse-checkout set skills/handdrawn-explainer-video
```

装完新开会话即可被自动发现，对 AI 说对应触发词即生效。

## 🧰 运行时依赖（首次使用前装一次）

| 依赖 | 安装 | 谁在用 |
|---|---|---|
| Node.js ≥ 18 | 官网安装 | 全部（渲染脚本） |
| playwright-core | `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i -g playwright-core` | handdrawn-explainer-video、douyin-cover-generator |
| Chromium / Chrome | 本机已有即可；无则设 `CHROME_PATH` 指向可执行文件 | 同上（脚本自动探测） |
| ffmpeg | `apt install ffmpeg` 或官网安装 | handdrawn-explainer-video（帧序列合成 MP4） |

## 📄 License

MIT
