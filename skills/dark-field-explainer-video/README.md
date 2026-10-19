# 暗场发光图文视频生成器

把任意主题制作成 **「黑场发光字 + 数据可视化 + 粒子流场」** 风格的科技感动态图文科普短片，
又称 **Opus5.5 风**（该风格由 Claude Opus 5.5 主导设计）。

风格参照 `assets/「我爱你」说到第 1000 遍，信息量几乎为零.mp4`——
近纯黑底、一层胶片颗粒、单一橙红强调色、衬线大标题、极简数据图、长黑场转场。

---

## 一句话定位

| | |
|---|---|
| **它做什么** | 150~180 秒的暗色系图文科普短片（1080p MP4 + 工程源码 + 分镜脚本） |
| **它不做什么** | 手绘卡通（那是 `handdrawn-explainer-video`）、纯无字幕的纯视觉片、垂直短视频 |
| **最大的区别** | 一屏只讲一件事，大量留白，用一个数字说话 |

---

## 快速开始

```bash
SK=.workbuddy/skills/dark-field-explainer-video

# 1) 从模板起手，改 TIMELINE 与各幕 draw()
cp $SK/templates/video-template.html <项目>/<主题>/video.html

# 2) 渲染前静态自检（必做）
node $SK/scripts/precheck.js <项目>/<主题>/video.html 168

# 3) 关键帧视觉审查（必做，全量渲染的门禁）
node ../handdrawn-explainer-video/scripts/keyframes.js \
  <项目>/<主题>/video.html <项目>/<主题>/keyframes
#    逐张 Read 审查帧（或先看 _联系表.jpg），改完重跑到干净，再签收：
node ../handdrawn-explainer-video/scripts/keyframes.js \
  <项目>/<主题>/video.html <项目>/<主题>/keyframes --approve "逐张看过"

# 4) 全量渲染 + 编码（无签收会被 render.js 拒绝）
node ../handdrawn-explainer-video/scripts/render.js \
  <项目>/<主题>/video.html <项目>/<主题>/frames --fps 30 --dur 168 --clean
node ../handdrawn-explainer-video/scripts/encode.js \
  <项目>/<主题>/frames 30 "<项目>/<主题>/<片名>.mp4" 8M     # 无 bash 用这个；有 bash 也可用 encode.sh
node ../handdrawn-explainer-video/scripts/grab.js \
  "<项目>/<主题>/<片名>.mp4" --acts --html <项目>/<主题>/video.html
```

---

## 文档索引

| 文件 | 内容 | 什么时候看 |
|---|---|---|
| `SKILL.md` | 风格定义八条硬规则、七阶段流程、技术铁律 | **先读这个** |
| `references/style-spec.md` | 色彩/字体/发光/构图/**三层结构**/节奏的**实测数值**，含反面清单 | 动手画每一幕时对照 |
| `references/scene-patterns.md` | 七种分幕套路（数字/对比/公式/数据图/列举/粒子/档案墙）与代码 | 排版时不知道用什么镜头 |
| `references/production-notes.md` | 实测性能、六个已踩的坑、与其他 skill 的边界 | 出问题时查 |
| `templates/video-template.html` | 可直接渲染的工程骨架（含三幕示例） | 起手 |
| `scripts/precheck.js` | 渲染前静态自检 | 每次渲染前 |

---

## 依赖

复用 `handdrawn-explainer-video` 的渲染脚本，**不重复实现**：

| 资源 | 位置 |
|---|---|
| `render.js` / `keyframes.js` / `encode.js` / `encode.sh` / `grab.js` | `../handdrawn-explainer-video/scripts/` |
| `merge-audio.sh` | `<项目根>/scripts/` |
| ffmpeg / ffprobe | `<项目根>/tools/` |

运行时：Node ≥ 18、`playwright-core`、本机 Chromium、ffmpeg。

> 本风格**只用系统字体**，不需要 `assets/fonts/`——这是相对手绘 skill 的一大简化。

---

## 实测性能

| 项目 | 结果 |
|---|---|
| 渲染速度 | ≈ 21 fps（720 帧 / 30fps / 34 秒） |
| 建议码率 | `-b:v 8M`（暗场低码率会出现色带） |
| 24 秒样片成片 | 16.5 MB |

---

## 版本

- **1.1.0**（2026-10-15）三层结构硬纪律（每幕 ≥2 层）+ 组件库（点阵网格 / 微光条目卡）+
  压场渐晕手法 + 新幕式「档案墙幕」；加入别名 **Opus5.5 风**（该风格由 Claude Opus 5.5 主导设计）。
- **1.0.0**（2026-10-14）首个版本，源自参考片抽帧逆向。
  详见 `SKILL.md` frontmatter 的 changelog。
