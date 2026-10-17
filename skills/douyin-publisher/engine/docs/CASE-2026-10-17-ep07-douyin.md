# 成功案例：Ep07《手头紧，先翻工具箱》抖音首跑

> 2026-10-17 23:55，`douyin-publisher` v0.2 首次端到端跑通并真实发布。
> 本文记录可复现的输入、命令、页面设置与踩坑，供后续整系列批量和视频号复用。

## 1. 结果

| 项 | 值 |
|---|---|
| 视频 | `人生高性价比指南/Ep07-没钱的时候怎么活/手头紧先翻工具箱_Opus5.5_卡点版_1.5x.mp4` |
| 标题 | 手头紧，先翻工具箱 |
| 正文 | 调研材料「核心问题」两条（原文照录） |
| 话题 | `#人生高性价比指南 #省钱 #失业金 #劳动仲裁 #医保` |
| 封面 | 竖版 3:4 + 横版 4:3（本地两张 PNG） |
| 合集 | 人生高性价比指南（页面显示「第8集」，原合集已有 7 个作品） |
| 自主声明 | 内容由 AI 生成 |
| 发布 | 公开、立即发布 |
| 状态 | 发布成功，作品数 29 → 30，审核中 |

发布后截图：`logs/<时间>_published_1.png`；内容管理页确认脚本见 `tmp/check_content.py`（工作区）。

## 2. 前置条件

1. Python 3.10+，`pip install -e .`，本机已装 Chrome。
2. **持久化登录档案**（不是 `storage_state`）：
   ```powershell
   douyin-publisher login
   ```
   扫码后登录态写入 `~/.douyin_publisher/chrome-profile`。之后 `publish` 直接复用，不再扫码；
   只有抖音 session 真正过期时才需要重跑 `login`。
3. `~/.douyin_publisher/chrome-profile` 含完整浏览器状态，**等同账号凭证，禁止提交/外传**。

## 3. 清单格式（新增字段）

```json
{
  "series": "人生高性价比指南",
  "items": [
    {
      "file": "D:/.../手头紧先翻工具箱_Opus5.5_卡点版_1.5x.mp4",
      "cover": "D:/.../封面_竖版3x4_手头紧先翻工具箱.png",
      "cover_h": "D:/.../封面_横版4x3_手头紧先翻工具箱.png",
      "text": "标题行\n正文第一行\n正文第二行\n#话题1 #话题2",
      "collection": "人生高性价比指南",
      "aigc": true,
      "publish_at": ""
    }
  ]
}
```

- `text`：**第一行=作品标题**，中间=正文，最后含 `#` 的部分=话题。
- `cover`：竖封面 3:4（信息流主封面，必设；失败中止发布）。
- `cover_h`：横封面 4:3（可选；失败只警告，不阻断）。
- `collection`：合集名，按「包含」匹配；找不到会打印候选列表并继续。
- `aigc`：`true` 时选「自主声明 → 内容由 AI 生成」；设置失败会中止发布。
- `publish_at`：留空=立即发布，或 `2026-10-18 18:00`。

## 4. 命令

```powershell
cd D:\github\douyin-publisher

# 1) 预检 + dry-run：填完一切、截图、停在发布前
douyin-publisher publish "D:\...\tmp\publish\Ep07-发布清单.json" --non-interactive

# 2) 核对 logs/<时间>_ready_1.png 后真发
douyin-publisher publish "D:\...\tmp\publish\Ep07-发布清单.json" --execute --non-interactive
```

`--non-interactive` 是 Agent 批处理专用：dry-run 自动逐集走完；配合 `--execute` 时等同 `--yes`，
**执行前必须有人批准批次**。

## 5. 这次修掉的坑（都已在代码里）

### 5.1 登录态：storage_state → 持久化 profile
- `storage_state` 每次都在全新临时 profile 里恢复，只有 cookie/localStorage，缺设备指纹
  （IndexedDB/密钥/Service Worker）。抖音会判“新设备”，session 在 20 分钟内被踢。
- 改用 `launch_persistent_context(user_data_dir=~/.douyin_publisher/chrome-profile)` 后稳定。
- 登录检测不能只看 URL：未登录也会停在 `creator-micro/home` 并弹扫码浮层。
  判据 = URL 在 `creator-micro` + 无可见「扫码登录」+ 左侧导航（内容管理/数据中心/作品发布）可见。

### 5.2 发布按钮：精确匹配
`button:has-text('发布')` 会先命中左侧导航「**作品发布**」，点了只会跳回上传页（像“暂存”）。
必须：
```python
button:text-is('发布')
```
成功判据：URL 进入 `content/post/video` 或页面出现「发布成功」；**上传页 URL 不代表成功**。

### 5.3 封面：按结构定位，不能按文字
设置过一张封面后，另一张卡片上的「选择封面」文字会消失（只剩图标）。
结构（2026-10 实测）：
```
div[class^=coverControl-]      ← 横 4:3 在前、竖 3:4 在后
  ├ div[class^=cover-]         ← 可点击卡片
  └ div[class^=cover-tip-]     ← 文案「横封面4:3」/「竖封面3:4」
```
按 tip 里的 `4:3` / `3:4` 找到卡片再点；顺序上先竖后横，横封面失败不阻断。

### 5.4 草稿横幅
失败的尝试会留下「你还有上次未发布的视频」横幅；发布前自动点「放弃」清掉，
否则可能带着旧草稿进入发布流程。

## 6. 复用清单（下一集）

1. 复制清单模板，改 `file` / `cover` / `cover_h` / `text` / `collection`。
2. `text` 的正文从该集 `调研材料.md` 的「核心问题（本集要回答）」抄两条。
3. 先 `--non-interactive` dry-run，看 `logs/*_ready_1.png`：标题、正文、话题、双封面、合集、自主声明、
   发布时间六项都要对。
4. 用户批准后 `--execute --non-interactive`。
5. 发布后用内容管理页核对作品数 +1、标题/封面正确；状态为「审核中」属正常。
