---
name: douyin-publisher
description: "抖音成品视频批量发布：把一个系列的成片 mp4 批量上传到抖音创作者平台并逐集填标题话题/定时发布。引导 Agent 用 douyin-publisher CLI（login 扫码 / gen 生成清单 / publish 批量发布，dry-run 默认）完成发布全流程，包括：从分镜脚本提取每集标题话题填清单、首跑校准页面选择器、非交互批处理模式、失败集补跑、风控纪律与合集处理建议。触发词：发布抖音、批量上传、上传抖音、发布视频到抖音、抖音发布清单、douyin publisher、发抖音、系列视频发布"
version: "1.5.0"

author: "CodeBuddy AI"

created: "2026-10-16"

changelog: "1.0.0 首个版本。源自 douyin-publisher 项目实战立项：调研确认抖音开放平台 OpenAPI 对个人主体不可行，故走创作者中心网页端 + Playwright 浏览器自动化路线。1.1.0（2026-10-18）对齐工具 v0.3 实战（Ep07 首跑 + Ep08-10 定时发布）：登录改持久化 Chrome 档案；封面自动化；manifest 新增 collection/aigc；--at/--now 统一定时；发布按钮精确匹配；keepalive。1.2.0（2026-10-18）Agent-first：工具并入本 skill 的 engine/ 统一管理；新增 doctor 自检、publish --json（stdout 纯 JSON + 错误码）、默认非交互（--interactive 才逐集确认）；manifest 新增 visibility/declaration/allow_save；合集与非公开可见互斥。1.3.0（2026-10-18）话题热度筛选：manifest 新增 topics（theme/pin/seeds/min_heat/count），实时查 challengesug 播放量、按 ≥1亿 选最热、点选绑定话题实体；新增 topics 子命令；总话题数上限 5。1.4.0（2026-10-18）发布记录：真发布后自动追加 Markdown + CSV（默认 <项目根>/.douyin-publisher/发布记录.md，话题带热度、失败带 error_code），新增 history 子命令与 --history/--no-history。1.4.1（2026-10-18）发布记录默认改为项目根 `.douyin-publisher/`（按清单向上找 .git/.workbuddy/AGENTS.md，不写用户主目录），新增 history --manifest 定位；新建记录目录自动 .gitignore。1.5.0（2026-10-18）话题数量默认填满：count 缺省即取满到上限 5（原默认 3），用户仍可自定义数量，硬钳 ≤5；候选不足不报错。"
---

# 抖音成品视频批量发布（douyin-publisher）

> **Goal**：用户说"把这批视频发到抖音"时，Agent 能独立走完：确认范围 → 生成清单 → 提取标题话题 → dry-run 校准 → 批量发布 → 验收补跑。不逐集手动操作，但**每一步有截图留痕、批次发布必须用户明确批准**。

## 概述

- **工具本体**：本 skill 目录下的 `engine/`（douyin-publisher v0.8，独立 Python 包）。**Agent-first 管线，不做 GUI**：工具本质是浏览器自动化，"界面"就是发布页本身；人的参与收敛为扫码一次、审清单、批准批次三个触点。
- **本 skill**：Agent 视角的调用手册。引擎改 `engine/`，工作流经验沉淀在这里。
- **原理**：Playwright 驱动本机 Chrome（launch_persistent_context 持久化档案）操作 creator.douyin.com 发布页。**官方 OpenAPI 对个人主体不可行**（详见 `engine/docs/openapi-research.md`），别再往 API 路线上浪费时间。

## 前置条件（每次会话先检查）

1. **CLI 可用**：`douyin-publisher --version`（应为 0.8.x）。不可用则
   `"C:/Users/yangck/.workbuddy/binaries/python/envs/default/Scripts/pip.exe" install -e "<本skill目录>/engine"`。
   未安装也可用 `python -m douyin_publisher`（在 `engine/` 目录下）。
2. **登录档案存在**：`~/.douyin_publisher/chrome-profile/`（持久化 Chrome 档案）。不存在 → 提醒用户在场，跑
   `douyin-publisher login` 后**用户用手机扫码**（Agent 无法代扫，这一步必须等用户）。
   ⚠️ 已弃用 storage_state 方案：cookie 在新临时 profile 恢复会被抖音判"新设备"踢下线（实测 20 分钟内失效），持久档案扫一次长期复用。
3. **每次会话先自检**：`douyin-publisher doctor --json`；要确认登录态加 `--deep`（会打开浏览器约 10 秒）。
   `login` 为 `false` 或报跳转登录页 → 重跑 `login`。

## 工作流

### 第 1 步：确认发布范围

向用户确认：哪个系列、哪几集（默认整个系列目录）、立即发还是定时、是否已建合集。
**不要自作主张全发**——新号/主力号单次批量 ≤10 集，先问。

### 第 2 步：生成清单骨架

```bash
douyin-publisher gen "<系列目录>" -o <系列目录>/发布清单.json
```

生成后**Agent 主动填 text 与各字段**（这是 Agent 比 CLI 强的地方，也是用户最省事的环节）：
- `text` 格式：第一行=作品标题，中间=正文若干行，末尾=话题。标题来源优先级：该集 `分镜脚本-Opus5.5版.md` 的钩子文案 / `变更记录.md` 的集名与一句话主旨 / 集目录名。
- `topics`（可选，v0.6+，推荐）：话题热度筛选。`theme`=第 1 个（主题名，豁免热度）；`pin`=第 2 个起相关词（list，豁免热度）；`seeds` 填约 10 个当期候选词；其余按 `view_count >= min_heat`（默认 1 亿）、话题名包含 seed、每个 seed 最多 1 个，取最热的 `count` 个。**`count` 缺省即填满到 5 个**（抖音描述区上限 5），用户可自定义数量、上限 5；候选不足时按实际选到的数量出，不报错。总数上限 `1 + len(pin) + count ≤ 5`。
  - 种子怎么来：从该集分镜/调研里抽约 10 个"观众真会搜"的词（现象词、人群词、场景词），别只填宽泛大词。
  - 配了 `topics` 后，`text` 里的 `#话题` 只作兜底（接口挂掉时用）；dry-run 会打印选中话题与热度明细。
- `cover`（竖版 3:4，设置失败会**中止发布**）与 `cover_h`（横版 4:3，失败仅警告不阻断）：直接填每集交付的封面路径。
- `collection`：合集名按「包含」匹配，须为**已存在**的合集（找不到会打印候选）。
- `visibility`（公开/好友可见/仅自己可见）、`declaration`（6 种自主声明，含「无需添加自主声明」）、
  `allow_save`（true/false）：用户自行抉择的发布设置，不填则用平台默认（公开/允许/无声明）。
  **平台硬限制：进合集的视频不能设好友/仅自己可见**，同时给两者会直接报错，二选一。
- `publish_at` 留空=立即；或批量跑时用 `--at 'YYYY-MM-DD HH:MM'` / `--now` 统一覆盖清单。
- 填完把完整清单展示给用户过目一遍再进第 3 步。

### 第 3 步：dry-run 校准（首跑或抖音改版后必做）

```bash
douyin-publisher publish <清单> --only 1 --non-interactive
```

跑一集 dry-run（**不会真发**，自动走完上传+填文案后关页）：
- 全程截图在 `logs/`，`ready_1.png` 能看到填好的发布页即为通过。
- 配了 `topics` 时，输出里会有"话题筛选"明细（每个话题的热度与来源 seed）和"话题实体绑定 N/N 个"；核对这 5 个话题是否相关、顺序对不对。
- 若报"找不到 file input / 编辑器 / 发布按钮"：打开对应 `err_*.png` 截图，改
  `engine/douyin_publisher/config.py` 的 `SELECTORS`（每键一组候选，按序取首个可见命中），改完重跑。
- 校准通过后**把选择器改动 commit 进工具仓库**（惠及所有人）。

### 第 4 步：批量发布（必须用户批准）

```bash
# 默认非交互，适合 Agent 批处理；要逐集人工确认加 --interactive
douyin-publisher publish <清单> --execute
# 机器可读结果：stdout 只输出 JSON，过程日志走 stderr
douyin-publisher publish <清单> --execute --json --result-file logs/result.json
```

**纪律（不可违反）**：
- `--execute` **必须先拿到用户对这批内容的明确批准**（展示过清单 + 用户点头），Agent 不得自行决定真发。
- 默认集间隔 120s 基准（实际 0.8~1.5 倍随机），单批 ≤10 集；想更快用 `--interval 60` 但别更低。
- 只用真实浏览器（工具已固化 headless=False），别为省资源改 headless——风控概率大增。
- `--json` 结果里的 `error_code` 用于决策：`auth_expired` 先扫码；`selector_drift` 去校准；
  `platform_rejected` 看平台限制；`upload_timeout` 可 `--only` 补跑。
- 真发布后自动追加发布记录到 `<项目根>/.douyin-publisher/发布记录.md` + 同名 CSV（项目根按清单向上找 `.git`/`.workbuddy`/`AGENTS.md` 判定）；换路径用 `--history`，不写用 `--no-history`。

### 第 5 步：验收与收尾

- 看输出末尾"结果汇总"；失败/未知集用 `--only <序号>` 补跑。
- 发布后 `douyin-publisher history --limit 10` 核对最新记录（状态、话题热度、失败原因）；默认在项目根 `.douyin-publisher/`，同名 CSV 可直接用 Excel 打开；不在项目根跑时加 `--manifest <清单>`。
- 成功判据：页面跳转进入 content/post/video 或出现「发布成功」；发布后在 App 里抽查封面/合集/声明是否符合预期。
- 登录档案等同账号凭证，绝不写进任何入库文件、不外传。

## 坑表

| 坑 | 处理 |
|---|---|
| OpenAPI 路线幻想 | 个人主体建不了网站/移动应用，别再试；有企业资质需求看工具仓库 docs/openapi-research.md |
| Agent 跑 publish 卡住不动 | 默认已是非交互；只在你显式加了 `--interactive` 时才会 `input()` 等回车 |
| 选择器突然全失效 | 抖音改版了，回第 3 步校准，改 config.py 后 commit |
| 带水印/logo 的片源 | 大概率降权/下架，发布前提醒用户 |
| 发布按钮点错位置 | 必须精确匹配 `button:text-is('发布')`；宽匹配会命中左侧导航「作品发布」，表现为「暂存」假成功 |
| 定时时间填不上 | 定时单选要点 label 本身（内部 span 被拦）；填完必须校验 input_value；日期浮层要 Escape 关掉否则挡发布按钮 |
| 定时规则 | 平台要求至少 2 小时后、14 天内；同一时间可排多条（实测 3 条同排成功） |
| 批量中途 Chrome 退出 | 持久化 context 里关掉最后一个页面会杀 Chrome——工具已内置空白页 keepalive，别删 |
| 话题只按热度选会跑偏 | 联想接口有歧义（查 `AED` 最热是 `#艾尔登法环`）；工具已加"话题名必须包含 seed"闸门，种子别用歧义缩写 |
| 话题总数超 5 | 抖音描述区上限 5；`1 + len(pin) + count ≤ 5`，清单预检直接报错，减 count 或 pin |
| 话题热度接口失效 | 打印"话题热度接口不可用"并回退 `text` 话题；先 dry-run 看警告，别盲目 execute |
| 用户语音输入 | "发布清单"可能被识别成别的词，涉及发布操作一律先复述清单内容再执行 |

## 形态（2026-10-18 定稿：engine + skill 单轨）

**引擎 + 说明书，两层，不再做“给人用的应用”**：
- `engine/` = 确定性执行器（Python + Playwright），只暴露 CLI 契约：manifest 进、JSON 出、退出码。
- `SKILL.md` = Agent 的工作流与决策手册（触发词、范围确认、dry-run 判断、失败归因、批次批准、验收）。
- 人只通过对话参与三个触点：**扫码一次 / 审清单 / 批准批次**。不做 GUI——浏览器自动化类工具的界面就是被驱动的网页本身。
- 今后同类工具默认按此单轨沉淀：引擎作为 skill 的 `engine/` 子目录，与 skill 一起版本管理，junction 进 `.workbuddy/skills/`。

