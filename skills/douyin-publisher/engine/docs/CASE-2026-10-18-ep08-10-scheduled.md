# 成功案例：Ep08–Ep10 定时发布（同一时间 2026-10-18 08:10）

> 2026-10-18 00:04–00:14 自动排入抖音定时队列，三条同一时间。
> 本文记录批量定时发布的输入、命令、结果与新增的三个坑，供后续系列和视频号复用。

## 1. 结果

| 集 | 标题 | 视频 | 状态 |
|---|---|---|---|
| Ep08 | 搭进去只要一秒钟 | `搭进去只要一秒钟_Opus5.5_卡点版_1.5x.mp4` | 定时发布中，2026-10-18 08:10 |
| Ep09 | 一次手滑，十天拘留 | `一次手滑十天拘留_Opus5.5_卡点版_1.5x.mp4` | 定时发布中，2026-10-18 08:10 |
| Ep10 | 先算账，再领证 | `先算账再领证_Opus5.5_卡点版_1.5x.mp4` | 审核中，日期 2026-10-18 08:10 |

- 作品数：30 → 33（Ep07 已发，Ep08–10 定时）
- 每集均带：竖 3:4 + 横 4:3 封面、合集「人生高性价比指南」、自主声明「内容由 AI 生成」
- 正文：各集 `调研材料.md` 的「核心问题（本集要回答）」两条
- Ep10 显示「审核中」而非「定时发布中」，但发布日期已是 08:10，说明定时已生效，审核通过后会转为定时状态

## 2. 命令

本次用清单内的 `publish_at` 逐条指定：

```powershell
douyin-publisher publish "tmp/publish/Ep08-10-发布清单.json" `
  --execute --non-interactive
```

（第一次批量时第 2/3 条因浏览器退出失败，用补跑完成：）

```powershell
douyin-publisher publish "tmp/publish/Ep08-10-发布清单.json" `
  --only 2,3 --execute --non-interactive
```

另外两种统一控制方式（v0.3 新增）：

```powershell
# 所有集统一定时，覆盖清单里的 publish_at
... --at "2026-10-18 08:10"

# 所有集强制立即发布，覆盖清单
... --now
```

优先级：`--now` / `--at` > 清单 `publish_at` > 立即发布。
平台限制：定时时间需 **≥2 小时、≤14 天**；同一时间可以排多条（本次 3 条同排成功）。

## 3. 新增的坑与修法

### 3.1 「定时发布」单选被 label 拦截
新版是：
```html
<label class="radio-d4zkru" data-checked="false">…<span>定时发布</span></label>
```
点内部 `<span>` 会被 label 拦截，Playwright 报 `element intercepts pointer events`。
**修法**：优先点 `label:has-text('定时发布')` 本身，失败再 `evaluate("el => el.click()")`；
点完用 `data-checked="true"` 验证。

### 3.2 日期选择浮层挡住发布按钮
填完时间后日期面板不会自动收起，会盖住底部按钮。
**修法**：`Escape` + 点空白处收起，再截图确认；发布按钮文案在定时模式下可能仍是「发布」，选择器同时兼容「发布」和「定时发布」。

### 3.3 持久化 context 关掉最后一个页面 = 浏览器退出
`launch_persistent_context` 下 `page.close()` 关掉唯一标签页，Chrome 会直接退出，
下一集报 `Target page, context or browser has been closed`。
**修法**：批量开始前建一个 `about:blank` 保活页；每集结束照常关工作页。

## 4. 验证清单

1. `--non-interactive` dry-run 后看 `logs/*_ready_*.png`：
   - 「定时发布」单选已选中；
   - 时间输入框显示目标时间；
   - 日期浮层已收起；
   - 封面/合集/自主声明/话题齐全。
2. `--execute` 后看 `logs/*_published_*.png` 与内容管理页：
   - 作品数 +N；
   - 目标日期正确；
   - 状态为「定时发布中」或「审核中」。

## 5. 发布设置可配置（v0.4）

| 设置 | 清单字段 | CLI 覆盖 | 可选值 |
|---|---|---|---|
| 谁可以看 | `visibility` | `--visibility` | 公开 / 好友可见 / 仅自己可见 |
| 保存权限 | `allow_save` | `--no-save` | true / false（允许 / 不允许） |
| 自主声明 | `declaration` | `--declaration` | 内容由AI生成 / 内容为个人观点或见解 / 内容为转载信息 / 内容含营销推广信息 / 虚构演绎，仅供娱乐 / 无需添加自主声明 |
| 发布时间 | `publish_at` | `--at` / `--now` | 立即或 `YYYY-MM-DD HH:MM` |
| 合集 | `collection` | `--collection` / `--no-collection` | 已有合集名 |

**平台硬限制**：加入合集或专辑的视频，不能设「好友可见 / 仅自己可见」。
同时给 `collection` 和非公开 `visibility` 时，脚本会在上传前直接报错，要求二选一。

dry-run 验证示例（不选合集）：

```powershell
douyin-publisher publish 清单.json --only 1 --no-collection `
  --visibility 仅自己可见 --declaration 内容为个人观点或见解 --no-save --non-interactive
```

页面结果：谁可以看=仅自己可见、保存权限=不允许、自主声明=内容为个人观点或见解、
发布时间=定时发布 2026-10-18 08:10。
