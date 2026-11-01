# douyin-cover-generator

抖音封面生成 skill（**夜场光场 v2**）—— 输入视频稿件或主题，产出 **3:4 竖版（1080×1440）+ 4:3 横版（1920×1440）** 两张封面。

纯代码渲染：HTML + Canvas 2D + playwright-core 截图，与 [handdrawn-explainer-video](../handdrawn-explainer-video/) 的 `render.js` 完全同栈、同依赖、同 Chromium 探测逻辑。**零积分、零外部生成能力依赖**（硬性禁止 ImageGen/VideoGen）。

## 视觉语言

暗场 + 分层光 + 超粗中文标题，一张封面只说一件事：

- **暗场不黑**：五段墨色渐变、三层大气光、暗角、胶片颗粒
- **光即隐喻**：一张只允许一个光结构——门槛（路径/期限）、光轮（周期/命运）、光束（情绪）、纯暗场（金句）
- **字是主角**：两行硬碰、吃满 86% 画幅、逐字字距；不用描边，对比靠暗投影与金色光晕
- **双色分层**：冷白常规行 + 金色强调行（双层光晕）
- **一枚印章**：全图唯一高饱和色，歪 3°，压紧迫感
- **编辑暗号**：页眉细条 + EP 徽标 + 细线菱形 + mono 标注 + 四角裁切 + 颗粒

## 快速使用

```bash
# 竖版 3:4（主交付）：门槛场景，两行标题 + 印章
node scripts/render-cover.js \
  --title $'十二条路\n门槛写死了' --subtitle "18 岁之后" --stamp "期限作废" \
  --kicker "人生高性价比指南" --issue "EP.31" --note "12 PATHS · ONE THRESHOLD" \
  --scene threshold --ratio 3:4 --out 封面_竖版3x4_十二条路.png

# 横版 4:3：只换 --ratio，构图自动重排
node scripts/render-cover.js \
  --title $'十二条路\n门槛写死了' --subtitle "18 岁之后" --stamp "期限作废" \
  --kicker "人生高性价比指南" --issue "EP.31" \
  --scene threshold --ratio 4:3 --out 封面_横版4x3_十二条路.png

# 系列化运营：系列名入标题块首行，片名自动降一档（--layout brand）
node scripts/render-cover.js --title "687条建议" --kicker "人生高性价比指南" \
  --issue "EP.34" --layout brand --subtitle "命 · 钱 · 自由 · 时间精力" \
  --stamp "全系列" --scene orbit --ratio 3:4 --out 封面_竖版3x4_总览.png

# 用成片抽帧当背景（会自动冷调压色、压暗、加 scrim）
node scripts/render-cover.js --title $'买球鞋\n先看这三点' --subtitle "实测 30 天的结论" \
  --bg frame.png --darken 0.55 --scene plain --ratio 4:3 --out 封面_横版4x3_球鞋.png
```

`--ratio` 支持 `3:4`（默认）/ `4:3` / `9:16` / `16:9` / `1:1`，也可用 `--size WxH` 自定义。

**竖版是主交付**：竖版吃手机信息流、曝光量远高于横版。渲染完必须缩到 1/4（270×360）看一眼——金色那行还认得出来才算过。

完整方法论（六条风格铁律、版式比例表、场景选型、文案规范、参数表、失败对照表、v1 迁移）见 [SKILL.md](SKILL.md)。

## 结构

```
douyin-cover-generator/
├── SKILL.md                    # 风格内核 + 版式规范 + 执行流程 + 参数表
├── scripts/render-cover.js     # 渲染 CLI（playwright-core 截图 + 旧参数映射）
└── templates/
    ├── cover.html              # 画布页面
    └── cover.js                # 夜场光场引擎（4 种光结构 / 逐字排版 / 印章 / 颗粒）
```

## 版本

- **v2.0（2026-10-18）**：整体重构为夜场光场语言。移除描边/色块/大数字徽章/圆环角标；新增 scene 场景系统、双色标题、印章、编辑暗号层；横版改为同构中轴版式。旧参数 `--tag/--badge/--style` 自动映射。
- v1.x：大字报 + 红块徽章视觉。
