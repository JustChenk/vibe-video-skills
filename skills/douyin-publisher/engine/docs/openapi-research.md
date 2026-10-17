# 抖音开放平台 OpenAPI 路线调研留档（2026-10-16）

本文档记录"为什么不走官方 API"的调研依据，以及若未来有企业资质时的接入要点。
信息有时效性，使用前请核对官方最新文档。

## 1. 资质门槛（对个人基本堵死）

- **个人开发者**入驻抖音开放平台仅支持创建"小玩法"（小游戏）；
  小程序 / 移动应用 / 网站应用仅支持企业主体
  （官方帮助中心：developer.open-douyin.com/helpCenter/home/detail/94/819）。
- 「发布内容至抖音」能力申请规范（2025-08 公告 348，developer.open-douyin.com/announcement/348）：
  - 主体：不再向个体工商户开放；企业需**注册资本 ≥50 万且注册时间 ≥1 年**；
  - 应用状态：必须是**正式应用**（需上线转正）；
  - 应用类型：仅对**创作工具、社区、硬件配套、游戏类**开放；
  - 使用场景：仅对 C 端用户创作内容后的分享场景开放；企业宣传/营销类不开放；
  - 90 天无实际调用的应用会被**回收**投稿能力。

## 2. 接入要点（有资质时）

### OAuth 授权
- 网页授权：`https://open.douyin.com/platform/oauth/connect/?client_key=...&response_type=code&scope=video.create&redirect_uri=...`
- 换 token：`POST https://open.douyin.com/oauth/access_token/`（client_key/client_secret/code/grant_type=authorization_code）
- token 有过期时间，需用 refresh_token 续期。

### 视频上传（分片，三步）
| 步骤 | 接口 | 关键参数 |
|---|---|---|
| 初始化 | `POST /video/upload/init/` | open_id |
| 分片上传 | `POST /video/upload/` | upload_id、part_number、文件体（建议 4MB 分片，天然支持重传） |
| 完成上传 | `POST /video/upload/complete/` | open_id、upload_id → 返回 **video_id** |

### 发布
- `POST /video/create/`，body：`{open_id, video_id, text}`。
- 话题直接写在 text 里 `#话题`；@用户用 `at_users` 传 open_id。
- **陷阱**：video_id 与用户绑定，A 用户上传的 video_id 配 B 用户的 open_id 会被拒。
- 新版接口域名：`developer.open-douyin.com`（`/api/douyin/v1/video/...`），旧域 `open.douyin.com` 部分路径仍在服务；接入时以当期官方文档为准。

### 使用限制
- 视频 ≤4GB、≤15 分钟；推荐 mp4/webm、720p+ 竖版。
- 带 logo/水印大概率命中降权/下架审核。

### 配额
- 各接口有每日免费配额（如 video.list 每日 1000 次），用完次日 8 点恢复；查询路径：管理中心-应用详情-配额管理。

## 3. 结论

对个人创作者：无解，走网页端自动化（本项目主路线）。
对企业创作者：可行，但需先过应用上线 + 能力申请两道审核；届时可在本仓库加 `openapi/` 分支复用同一 manifest 格式。
