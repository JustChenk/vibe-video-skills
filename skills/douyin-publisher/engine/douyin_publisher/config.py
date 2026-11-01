# -*- coding: utf-8 -*-
"""全局配置：URL、页面选择器、默认参数。

抖音发布页改版时只需改这里的 SELECTORS（详见 README「首跑校准」）。
"""

UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
HOME_URL = "https://creator.douyin.com/creator-micro/home"

# 登录态：固定 Chrome 用户目录（持久化上下文），比每次复制 storage_state 更稳，
# 不会被抖音当成“新设备”踢下线。可用 --profile 覆盖。
PROFILE_DIR = "~/.douyin_publisher/chrome-profile"

# 旧版 storage_state 路径（仅作迁移备份，不再用于发布）
DEFAULT_STATE = "~/.douyin_publisher/state.json"

# 每个键给一组候选选择器，按顺序取第一个可见命中的。
SELECTORS = {
    # 上传入口的文件选择 input（页面通常只有一个 video 类 file input）
    "file_input": [
        "input[type='file'][accept*='video']",
        "input[type='file']",
    ],
    # 作品标题（新版发布页把「标题」和「描述」拆成了两个控件）
    "title_input": [
        "input[placeholder*='作品标题']",
        "input[placeholder*='标题']",
    ],
    # 描述/话题编辑器（contenteditable）
    "editor": [
        "div.zone-container",
        "div[contenteditable='true'][data-placeholder*='标题']",
        "div.notranslate[contenteditable='true']",
        "div[contenteditable='true']",
    ],
    # 上传/转码完成的标志（出现「重新上传」即就绪）
    "upload_done": [
        "[class^='long-card'] div:has-text('重新上传')",
        "text=重新上传",
    ],
    # 定时发布开关
    "schedule_toggle": [
        "text=定时发布",
        "span:has-text('定时发布')",
        "label:has-text('定时发布')",
    ],
    # 定时时间输入框
    "schedule_input": [
        "input[placeholder*='日期']",
        "input[placeholder*='时间']",
        "input[placeholder*='日期和时间']",
        "input[type='text'][class*='date']",
    ],
    # 发布按钮（精确匹配；定时发布时按钮文案变成「定时发布」）
    "publish_btn": [
        "button:text-is('发布')",
        "button:text-is('定时发布')",
        "button:has-text('发布'):not(:has-text('作品发布')):not(:has-text('暂存'))",
    ],
}

# 封面编辑器（点击「选择封面」后弹出的 modal）。抖音改版时改这里。
COVER_SELECTORS = {
    "entry_text": "选择封面",
    "modal": [
        "div.dy-creator-content-modal",
        "div[role='dialog'][aria-modal='true']",
    ],
    "vertical_tab": [
        "text=设置竖封面",
        "text=竖封面",
    ],
    "horizontal_tab": [
        "text=设置横封面",
        "text=横封面",
    ],
    "file_input": [
        "div[class^='semi-upload upload'] input.semi-upload-hidden-input",
        "div[class^='semi-upload'] input[type='file']",
        "input[type='file'][accept*='image']",
    ],
    "done_btn": [
        "div#tooltip-container button:visible:has-text('完成')",
        "div[class^='footer'] button:has-text('完成')",
        "button:has-text('完成')",
    ],
    "footer": "div.extractFooter",
}

# 发布设置里可选的枚举值（2026-10 页面实测）
VISIBILITIES = ("公开", "好友可见", "仅自己可见")
DECLARATIONS = (
    "内容由AI生成",
    "内容为个人观点或见解",
    "内容为转载信息",
    "内容含营销推广信息",
    "虚构演绎，仅供娱乐",
    "无需添加自主声明",
)

# 关联热点黑名单：命中即拒绝绑定。
# 实测教训（2026-10-24）：关键词「日本」在热点搜索里翻出
# 「日本挑衅台湾问题打错算盘」「高市上台一年日本正变成危险邻居」——
# 政治时事、涉台涉政、灾害、政务人事、明星八卦一律不绑，宁可不绑。
HOT_DENY = (
    "台湾", "台独", "挑衅", "一国两制", "朝鲜", "金正恩", "丹东", "俄乌", "俄罗斯",
    "乌克兰", "停火", "战争", "导弹", "军事", "南海", "高市", "首相", "内阁",
    "书记", "省委", "市委", "省政府", "市政府", "党组书记", "当选", "罢免",
    "地震", "台风", "遇难", "救援", "失联", "事故", "火灾", "坠",
    "演唱会", "红毯", "男篮", "中超", "苏超", "LPL", "游戏", "手游", "皮肤",
)

# 上传/转码等待上限（秒）
UPLOAD_TIMEOUT = 600

# 登录等待上限（秒）
LOGIN_TIMEOUT = 300

# 集间随机间隔基准（实际取 0.8~1.5 倍），防风控
DEFAULT_INTERVAL = 120
