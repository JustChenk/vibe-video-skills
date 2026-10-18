# douyin-publisher

**Agent-first 的抖音批量发布管线**：扫描系列目录、生成发布清单、自动上传填文案/双封面/合集/定时，批量发布。

## 定位：为什么是 Agent-first，为什么不做 GUI

本工具通过 Playwright 模拟真人操作创作者平台发布页——**它驱动的"界面"就是发布页本身**。给它套 GUI 只会得到一个更难用的发布页复制品，而自动化过程也无法通过简单的 REST 接口暴露给 UI。因此：

- **推荐用法：让 Agent（如 WorkBuddy/Claude Code）接管全流程**——生成清单、从调研/分镜材料提取标题话题、dry-run 校准、用户批准后批量发布。配套的 Agent 工作流 skill 在 [vibe-video-skills](https://github.com/JustChenk/vibe-video-skills) 合集仓库 `skills/douyin-publisher`。
- 人的参与收敛为三个触点：**扫码登录一次、审阅发布清单、批准发布批次**——都是对话和文件，不是图形界面。
- 人工直接用 CLI 也可行（见快速开始），但那是 Agent 路径的手动降级版。

面向场景：知识类/系列类短视频创作者（一个系列十几集，逐集手动上传太痛苦），且工作流里有 AI Agent 辅助。

> English TL;DR: batch-publish your finished videos to the Douyin (Chinese TikTok) Creator Platform
> via Playwright browser automation. QR login once → generate a manifest from your series folder →
> the script uploads each episode and fills title/hashtags, pausing for your confirmation before
> every publish. Dry-run by default.

## 为什么不是官方 API？（调研结论，2025-08 更新）

| 路线 | 结论 |
|---|---|
| 抖音开放平台 OpenAPI | **个人主体不可行**：个人开发者只能创建"小玩法"；网站/移动应用限企业主体，且 2025-08 公告 348 要求企业注册资本 ≥50 万、注册满 1 年，应用类型限创作工具/社区/硬件/游戏类，90 天不调用回收权限 |
| SDK投稿 / H5投稿 | 同样受上述资质限制，且本质是"拉起发布页 + 人工点发布" |
| 第三方矩阵工具 | 底层同为网页自动化，但付费且要交出账号授权 |
| **本项目：创作者中心网页端自动化** | 零资质、零费用；人工扫码一次，脚本排队上传 |

详细依据见 [docs/openapi-research.md](docs/openapi-research.md)。若你有达标企业资质，欢迎基于留档接口补充 OpenAPI 分支（PR welcome）。

## ⚠️ 免责声明

- 本项目通过浏览器自动化操作创作者平台，**非抖音官方背书的方式**，存在触发风控的可能。请自担风险，从 dry-run 开始、控制频率、别拿主力账号蛮干。
- 仅支持**发布你自己原创的内容**。项目内置保守设计（真实浏览器、逐集人工确认、随机间隔），请勿移除或滥用。

## 安装

要求：Python 3.10+、本机已安装 Chrome（自动化直接驱动本机 Chrome，免下载内核）。

```bash
pip install -r requirements.txt
# 或可编辑安装，获得 douyin-publisher 命令：
pip install -e .
```

## 快速开始

### 推荐路径：让 Agent 接管

对着你的 AI 助手说"把 <系列目录> 发布到抖音"即可，Agent 会走完整工作流（生成清单 → 提取标题话题给你过目 → 批准后发布）。Agent 侧的详细操作手册在 vibe-video-skills 合集仓库的 douyin-publisher skill。

### 手动路径：直接用 CLI

```bash
# 0. 自检（Agent 每次会话先跑；--deep 会打开浏览器验证登录态）
douyin-publisher doctor --json
douyin-publisher doctor --deep --json

# 1. 扫码登录（弹窗里用抖音 App 扫码；持久化浏览器档案存 ~/.douyin_publisher/chrome-profile，数周有效）
douyin-publisher login

# 2. 扫描系列目录生成发布清单骨架（优先取 *卡点版*.mp4，可 --prefer 换关键字）
douyin-publisher gen "D:/videos/我的系列" -o 我的系列-清单.json

# 3. 人工补齐清单里的 text（标题+正文+#话题）、cover/cover_h、collection、
#    visibility / declaration / allow_save——或交给 Agent 提取

# 3.5 话题热度筛选（可选）：约 10 个候选词，挑播放量 ≥1亿 且最相关的
douyin-publisher topics --theme "人生高性价比指南" --pin "程序员" `
  --seed 创业 --seed 职场 --seed 合同 --seed 法律 --seed 急救 `
  --seed 医保 --seed 劳动仲裁 --seed 存钱 --seed 理财 --seed 科普 `
  --count 3

# 4. 试跑：默认 dry-run，填好一切但停在发布前；--json 输出机器可读结果
douyin-publisher publish 我的系列-清单.json --json

# 5. 真发布（默认非交互，适合 Agent 批处理；要逐集人工确认加 --interactive）
douyin-publisher publish 我的系列-清单.json --execute

# 6. 定时发布（可选）：`--at` 覆盖清单里的 publish_at，所有集统一时间
douyin-publisher publish 我的系列-清单.json --at "2026-10-18 08:10" --execute

#    或强制立即发布，覆盖清单里的 publish_at
douyin-publisher publish 我的系列-清单.json --now --execute

# 7. 发布设置也可整批覆盖（用户自行抉择）
douyin-publisher publish 我的系列-清单.json `
  --visibility 仅自己可见 `
  --declaration 内容为个人观点或见解 `
  --no-save --no-collection `
  --at "2026-10-18 08:10" --execute

# 8. 查看发布记录（真发布后自动追加 md + csv）
douyin-publisher history --limit 10
```

定时规则：平台要求**至少 2 小时后、14 天内**；同一时间可以排多条（实测 3 条同时排入）。
优先级：`--now` / `--at` > 清单 `publish_at` > 立即发布。

**平台限制**：加入合集/专辑的视频不能设为「好友可见 / 仅自己可见」。脚本会在上传前直接报错，
请二选一：去掉合集（`--no-collection`），或把可见范围设为公开。

## Agent 接口（--json / 错误码）

`publish --json` 时 **stdout 只输出最终 JSON**，过程日志全部走 stderr；`--result-file` 另存一份。

```json
{
  "ok": true,
  "mode": "dryrun",
  "manifest": "D:/.../清单.json",
  "results": [
    {"index": 1, "status": "dryrun", "error_code": "", "error": "",
     "url": "https://creator.douyin.com/creator-micro/content/post/video", "file": "...",
     "topics": ["人生高性价比指南", "程序员", "科普"]}
  ]
}
```

- 状态：`ok` / `dryrun` / `fail` / `unknown` / `skip` / `abort`
- 错误码：`auth_expired`（扫码/登录失效）/ `selector_drift`（页面改版）/ `upload_timeout` /
  `platform_rejected`（平台限制）/ `error`
- 退出码：`0` 全部成功，`1` 有失败或未知

默认**非交互**（Agent 批处理）；`--interactive` 才逐集等回车确认。

其他常用参数：`--interval 180`（集间隔基准秒，实际随机 ×0.8~1.5）、`--only 3,5`（补跑失败集）、
`--at '2026-10-18 08:10'` / `--now`（统一定时/立即）、`--visibility` / `--declaration` /
`--no-save` / `--collection` / `--no-collection`（发布设置覆盖）、`--profile`（多账号浏览器档案目录）、
`--history <文件/目录>`（发布记录路径）、`--no-history`（不写记录）。

## 发布清单格式

```json
{
  "series": "人生高性价比指南",
  "items": [
    {
      "file": "D:/videos/人生高性价比指南/Ep08-示例/Ep08_卡点版_1.5x.mp4",
      "cover": "D:/videos/.../封面_竖版3x4_示例.png",
      "cover_h": "D:/videos/.../封面_横版4x3_示例.png",
      "text": "标题行\n正文第一行\n正文第二行\n#话题1 #话题2",
      "topics": {
        "theme": "人生高性价比指南",
        "pin": ["程序员"],
        "seeds": ["创业", "职场", "合同", "法律", "急救", "医保", "劳动仲裁", "存钱", "理财", "科普"],
        "min_heat": 100000000,
        "count": 3,
        "max_per_seed": 1
      },
      "collection": "人生高性价比指南",
      "visibility": "公开",
      "declaration": "内容由AI生成",
      "allow_save": true,
      "publish_at": ""
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | ✅ | 成片 mp4 路径（≤4GB、≤15 分钟，推荐 1080p） |
| `text` | ✅ | 第一行=作品标题；中间=正文；最后含 `#` 的部分=话题 |
| `topics` | — | 话题热度筛选配置（v0.6+）。配了它就用实时播放量选词并点选绑定，`text` 里的 #话题 只作兜底 |
| `cover` | — | 竖封面 3:4（信息流主封面；设置失败会中止发布） |
| `cover_h` | — | 横封面 4:3（可选；失败只警告，不阻断） |
| `collection` | — | 合集名，按「包含」匹配；找不到会打印候选 |
| `visibility` | — | `公开` / `好友可见` / `仅自己可见`（默认平台值：公开） |
| `declaration` | — | `内容由AI生成` / `内容为个人观点或见解` / `内容为转载信息` / `内容含营销推广信息` / `虚构演绎，仅供娱乐` / `无需添加自主声明` |
| `allow_save` | — | `true`=允许保存，`false`=不允许（默认平台值：允许） |
| `aigc` | — | 旧字段，`true` 等价于 `declaration: 内容由AI生成` |
| `publish_at` | — | 留空=立即发布；`2026-10-17 18:00`=定时发布 |

安全提示：带品牌 logo/水印的视频会大概率命中降权/下架审核，发布前自行处理。

## 话题热度筛选（v0.6+）

抖音发布页输入 `#` 时，联想列表每项都带话题累计播放量（如 `#创业 2583.5亿`）。配置 `topics` 后，工具在发布前实时查询这个数据，按规则选词，并**点选联想项**把话题绑定成真话题实体。

**选词规则**（第 1 个主题名，第 2 个随意，其余热度 ≥1亿、越高越好）：

1. `theme` 作为第 1 个话题，豁免热度（如系列名，哪怕只有几十万播放）；
2. `pin` 里的第 2 个话题同样豁免热度，建议填与当期主题高度相关的词；
3. 其余从 `seeds`（约 10 个）里选：`view_count >= min_heat`、**话题名必须包含 seed**（相关性闸门）、每个 seed 最多 `max_per_seed` 个、按热度降序取 `count` 个；
4. 总话题数上限 5（抖音描述区上限）：`1 + len(pin) + count <= 5`。**`count` 缺省即填满到 5**（v0.8 起，原默认 3），用户可自定义数量、硬钳 ≤5；候选不足（接口失效/热度不达标）时按实际选到的数量出，不报错。

**数据源**：发布页自己的联想接口 `aweme/v1/search/challengesug`，带登录 cookie 直接 GET，无需签名。返回 `cha_name` / `view_count` / `cid`，数字与页面显示一致。

**为什么要有相关性闸门**：联想接口会跑偏——查 `AED` 时最热的是 `#艾尔登法环 131.5亿`（游戏）。只按热度取最大会选出完全无关的话题，所以要求候选名包含 seed。

**dry-run 会打印选词明细**：

```
话题筛选：seed 10 个，阈值 1.0亿，候选 49 条，入选 3 条
  1. #人生高性价比指南        72.4万  置顶（theme）
  2. #程序员                 683.0亿  置顶（pin）
  3. #科普                 11984.4亿  seed=科普
  4. #职场                  4214.8亿  seed=职场
  5. #法律咨询               1688.0亿  seed=法律
话题实体绑定 5/5 个
```

选中/绑定失败（联想项找不到）会自动退化为纯文本 `#话题` 并打印警告；接口完全不可用时回退 `text` 里的话题。

单独查词（不上传、不发布）：

```bash
douyin-publisher topics --theme 主题名 --pin 相关词 --seed 词1 --seed 词2 ... --json
# 或直接从清单某条读 topics 配置：
douyin-publisher topics --manifest 清单.json --index 1
```

## 发布记录（v0.7+）

每次 `--execute` 真发布后，自动把每集结果追加到 **项目目录**（不是用户主目录）：

- `<项目根>/.douyin-publisher/发布记录.md`（人读，Markdown 表格）
- `<项目根>/.douyin-publisher/发布记录.csv`（Excel 直接打开，UTF-8 BOM）

项目根从清单路径向上找 `.git` / `.workbuddy` / `AGENTS.md` / `CLAUDE.md` 判定；找不到就落在清单所在目录。
**不默认写进 skill 仓库**（`engine/` 属于公开仓库，账号数据不应进去）；要换位置用 `--history`。
新建记录目录时工具会自动放一个 `.gitignore`（`*` + `!.gitignore`），所以即使 `--history <skill>/records`
也不会把记录误提交。

dry-run 不写，避免刷屏。路径可用 `--history <文件或目录>` 改（目录则落 `<目录>/发布记录.md`），
`--no-history` 关闭。记录是追加式，多次发布累积在一张表里。

列：时间 / 状态 / 系列 / 标题 / 文件 / 合集 / 话题（含热度）/ 发布方式 / 设置（可见范围·声明·封面）/ 结果 / 清单。
失败也记（带 `error_code`），方便回头 `--only` 补跑。

```bash
douyin-publisher history --limit 10
douyin-publisher history --manifest 清单.json   # 不在项目根目录跑时，按清单定位项目
douyin-publisher history --json                 # 从同名 CSV 读结构化数据
douyin-publisher history --path D:/records      # 指定别的记录目录
```

示例行：

| 时间 | 状态 | 系列 | 标题 | 文件 | 合集 | 话题（热度） | 发布方式 | 设置 | 结果 | 清单 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-19 08:10 | 已定时 | 人生高性价比指南 | 动手前，先问会不会报案 | Ep11.mp4 | 人生高性价比指南 | #人生高性价比指南(72.4万) #程序员(683.0亿) #科普(11984.4亿) #职场(4214.8亿) #法律咨询(1688.0亿) | 2026-10-19 08:10 | 公开 / 内容由AI生成 / 双封面 | 定时已设置 | Ep11-清单.json |

## 首跑校准（重要）

发布页 DOM 选择器是按 creator.douyin.com 已知结构编写的，抖音改版或细节出入时需要微调
[douyin_publisher/config.py](douyin_publisher/config.py) 里的 `SELECTORS`：

1. 每个键（`file_input` / `editor` / `schedule_toggle` / `publish_btn`…）是一组候选，按顺序取第一个可见命中；
2. 每一步都有截图落在 `logs/`，卡在哪一步就对着截图改哪一条；
3. 校准好后欢迎提 PR/Issue 更新选择器，惠及其他人。

已知限制：
- 合集只能选**已存在**的合集，不会自动创建；
- 成功判据以页面跳转/「发布成功」为准，发布后建议在 App 里抽查；
- 平台改版仍可能让选择器失效，先跑 dry-run 看 `logs/` 截图。

## 安全设计

- **dry-run 默认**：不点发布；`--execute` 才真发；
- **逐集人工确认**：每集停在发布前等你回车；
- **随机间隔**：集间 0.8~1.5 倍间隔秒随机，单次建议 ≤10 集；
- **全程截图**：`logs/` 逐步留痕，可回溯；
- **登录态本地保存**：`~/.douyin_publisher/chrome-profile`（完整浏览器档案），等同账号凭证，勿外传。

## Roadmap

- [x] v0.2 封面自动设置（竖 3:4 + 横 4:3）
- [x] v0.2 合集支持（选已有合集）+ 自主声明（内容由 AI 生成）
- [x] v0.3 定时发布（清单 `publish_at` / `--at` 统一时间 / `--now` 强制立即）
- [x] v0.4 发布设置可配置：可见范围 / 保存权限 / 自主声明（含无需声明）/ 合集，清单与 CLI 均可覆盖
- [x] v0.6 话题热度筛选：实时查播放量，主题名 + pin 置顶，其余按 ≥1亿 选最热，点选绑定话题实体
- [x] v0.7 发布记录：真发布后自动追加 Markdown + CSV（含话题热度、失败原因），`history` 命令查看
- [x] v0.8 话题数量默认填满：`count` 缺省即取满到上限 5（原默认 3），可自定义、硬钳 ≤5，候选不足不报错
- [x] **定位决策（2026-10-18）：不做 GUI**——工具的本质是浏览器自动化，"界面"就是发布页本身；
      人的参与收敛为清单审阅 + 批次批准，属于 Agent 对话与文件，不属于图形界面（推荐路径 = Agent 接管）
- [ ] 整系列批量：扫描目录自动匹配 1.5x 成片 + 双封面 + 从调研材料抽正文
- [ ] CSV/Excel 清单格式
- [ ] OpenAPI 分支（企业资质场景，接口调研已留档 docs/openapi-research.md）
- [ ] macOS 兼容测试（当前仅在 Windows + Chrome 实测）

## 实战案例

- [Ep07 抖音首跑（2026-10-17）](docs/CASE-2026-10-17-ep07-douyin.md)：完整输入、命令、页面设置与踩坑。
- [Ep08–Ep10 定时发布（2026-10-18）](docs/CASE-2026-10-18-ep08-10-scheduled.md)：三条同排 08:10 的批量记录。

## License

[MIT](LICENSE)
