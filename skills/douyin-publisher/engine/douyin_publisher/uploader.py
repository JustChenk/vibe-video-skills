# -*- coding: utf-8 -*-
"""核心发布流程：逐集 上传 → 填标题/文案 → 封面 →（定时）→ 人工确认 → 发布。

安全设计（不要削弱）：
- dry-run 默认：不点发布；
- 每集停在发布前等人工确认（--yes 才跳过，不建议）；
- 真实浏览器（headless=False），headless 会显著提高风控概率；
- 每一步截图落 logs/ 目录，出问题可回溯。
"""
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import config, topics

LOGS = Path(__file__).resolve().parent.parent / "logs"


# ---------------------------------------------------------------- 基础工具

def shot(page, name):
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f"{datetime.now():%H%M%S}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        print(f"    截图: {path}")
    except Exception as e:
        print(f"    截图失败({name}): {e}")


def find_first(page, key):
    """按 SELECTORS[key] 的候选顺序找第一个可见元素。"""
    for sel in config.SELECTORS[key]:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible():
                return loc, sel
        except Exception:
            continue
    return None, None


def locate_any(page, selectors, visible=True, timeout_ms=15000):
    """轮询一组选择器，返回第一个命中的 locator。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                if loc.count() > 0 and (not visible or loc.is_visible()):
                    return loc, sel
            except Exception:
                continue
        time.sleep(0.5)
    return None, None


def split_manifest_text(text: str):
    """manifest 的 text：第一行=标题，最后含 # 的部分=话题，中间=正文。

    兼容旧的一行式「标题 #话题1 #话题2」。
    返回 (title, body, tags)。
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "", "", []
    title = lines[0].strip()
    rest = "\n".join(lines[1:]).strip()
    if not rest and "#" in title:
        idx = title.find("#")
        rest = title[idx:]
        title = title[:idx].strip()
    tags = re.findall(r"#([^\s#]+)", rest)
    body = re.sub(r"#[^\s#]+", "", rest).strip()
    body = re.sub(r"[ \t]+\n", "\n", body).strip()
    return title, body, tags


# ---------------------------------------------------------------- 页面动作

def wait_upload_done(page, timeout=config.UPLOAD_TIMEOUT):
    """等待上传+转码完成：优先看「重新上传」出现，其次看发布按钮可用。"""
    deadline = time.time() + timeout
    last_pct = -1
    while time.time() < deadline:
        done, _ = find_first(page, "upload_done")
        if done:
            print("  上传就绪（检测到「重新上传」）")
            return True
        try:
            pct = page.locator("text=/\\d+%/").first
            if pct.count() > 0:
                txt = pct.inner_text()
                num = int("".join(ch for ch in txt if ch.isdigit()) or 0)
                if num != last_pct and num % 10 == 0:
                    print(f"    上传进度 {num}%")
                    last_pct = num
        except Exception:
            pass
        time.sleep(3)
    return False


def fill_title(page, title: str):
    """填「作品标题」（限 30 字）；找不到就返回 False，由文案区兜底。"""
    loc, sel = find_first(page, "title_input")
    if not loc:
        return False
    loc.click()
    loc.fill("")
    loc.fill(title[:30])
    print(f"  已填标题（{sel}）: {title[:30]}")
    return True


def _topic_items(page):
    """用 JS 直接读下拉里的话题名列表，杜绝 Playwright 的元素等待。

    2026-10-24 计时实测：同一个话题名，`inner_text()` 在下拉刚弹出时可阻塞 25.8s
    （默认超时 30s）并最终判定未命中；换成纯 DOM 读取后耗时 < 50ms。
    """
    try:
        return page.evaluate("""() => {
            const out = [];
            for (const el of document.querySelectorAll(
                    "[class*='mention-suggest'] [class*='tag-hash']")) {
                const t = (el.innerText || '').split('\\n')[0].trim();
                if (t) out.push(t.replace(/^#+/, '').trim());
            }
            return out;
        }""")
    except Exception:
        return []


def _topic_panel_open(page):
    try:
        return page.evaluate(
            """() => document.querySelectorAll("[class*='mention-suggest']").length > 0"""
        )
    except Exception:
        return False


def _find_topic_item(page, name, timeout=4.0):
    """等下拉出现目标话题（用 JS 轮询，不依赖 locator 等待）。返回序号，找不到返回 -1。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        names = _topic_items(page)
        if name in names:
            return names.index(name)
        time.sleep(0.25)
    return -1


def insert_topic(page, name):
    """输入 #话题名；命中联想项就点选（生成真话题节点），否则退化为纯文本。

    点选后的节点结构：<div data-mention="#">…<span>#话题</span>…</div>，
    与纯键盘输入的 #文本 不同，是平台认可的话题实体。

    2026-10-24 事故定论（计时证据）：
      - 症状：某个话题「找项」耗时 25.8s 且未命中，整批像卡死；
      - 真因：`inner_text()` 默认 30s 超时，下拉重建时节点失效被无限重试；
      - 修法：JS 直读 DOM 文本判位 → 用空格确认（高亮项），全程不点元素、不读元素。
    顺序：目标在第 1 位直接空格；在第 k 位先下移 k 次再空格；都失败才退化纯文本。
    单话题 12s 硬预算，绝不拖死整批。
    """
    t0 = time.time()
    page.keyboard.type("#" + name)
    pos = _find_topic_item(page, name, timeout=5.0)
    t1 = time.time()
    print(f"    [话题计时] #{name} 打字0.0s 找项{t1 - t0:.1f}s "
          f"{'命中@' + str(pos) if pos >= 0 else '未命中'}")
    if pos >= 0:
        try:
            for _ in range(pos):
                page.keyboard.press("ArrowDown")
                time.sleep(0.15)
            page.keyboard.press("Space")
            time.sleep(0.45)
            if not _topic_panel_open(page):
                print(f"    [话题] #{name} 用Space选中")
                return True
        except Exception:
            pass
    page.keyboard.press("Escape")
    time.sleep(0.15)
    page.keyboard.press("Space")
    time.sleep(0.2)
    print(f"    [话题] #{name} 未命中实体（{time.time() - t0:.1f}s），退化为纯文本")
    return False


def fill_text(page, body: str, tags, bind=False):
    """描述区：先写正文（多行），再逐个输入 #话题。

    bind=True 时逐个点选联想项（话题实体，带 cid）；False 保持旧行为（纯文本）。
    """
    editor, sel = find_first(page, "editor")
    if not editor:
        raise RuntimeError("找不到文案编辑器（SELECTORS.editor 全部未命中）")
    editor.click()
    time.sleep(0.5)
    body_lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    for i, line in enumerate(body_lines):
        page.keyboard.type(line)
        if i < len(body_lines) - 1:
            page.keyboard.press("Shift+Enter")
            time.sleep(0.2)
    if body_lines and tags:
        page.keyboard.press("Shift+Enter")
        time.sleep(0.2)
    bound = 0
    for tag in tags:
        if bind:
            if insert_topic(page, tag):
                bound += 1
            else:
                print(f"    [警告] 话题 #{tag} 未命中联想项，已按纯文本写入")
        else:
            page.keyboard.type("#" + tag)
            time.sleep(0.3)
            page.keyboard.press("Space")
            time.sleep(0.2)
    print(f"  已填正文 {len(body_lines)} 行 + {len(tags)} 个话题（{sel}）")
    if bind:
        print(f"  话题实体绑定 {bound}/{len(tags)} 个")
    time.sleep(0.5)
    # 收起话题联想浮层，避免挡住后续按钮
    page.keyboard.press("Escape")
    time.sleep(0.3)
    return bound


def _click_cover_entry(page, mode="vertical", timeout=10):
    """点「选择封面」入口。

    封面区结构（2026-10 实测）：
      div[class^=coverControl-]  ← 横 4:3 在前、竖 3:4 在后
        ├ div[class^=cover-]     ← 可点击的封面卡片
        └ div[class^=cover-tip-] ← 文案「横封面4:3」/「竖封面3:4」
    设置过其中一张后，另一张卡片的「选择封面」文字会消失（只剩图标），
    所以必须按结构 + 比例文案定位，不能只按文字。
    """
    want = "4:3" if mode == "horizontal" else "3:4"
    deadline = time.time() + timeout
    while time.time() < deadline:
        controls = page.locator("div[class^='coverControl-']")
        for i in range(controls.count()):
            card = controls.nth(i)
            try:
                text = card.inner_text() or ""
            except Exception:
                continue
            if want not in text:
                continue
            try:
                inner = card.locator("div[class^='cover-']").first
                target = inner if inner.count() > 0 else card
                target.click(timeout=3000)
                return True
            except Exception:
                try:
                    card.evaluate("el => el.click()")
                    return True
                except Exception:
                    continue
        # 兜底：按「选择封面」文字
        try:
            loc = page.get_by_text("选择封面", exact=True)
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible():
                    el.click(timeout=2000)
                    return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    return False


def _hot_rows(page, limit=60):
    """抓「关联热点」下拉里的条目：以「N万在看」为锚点，向上找整行，返回 [(row, text)]。

    抖音这个下拉没有稳定 class（构建哈希会变），但「万在看」这三个字是文案，稳定。
    行结构：缩略图 + 标题 + 热度，热度文字与标题在同一行的不同列。
    """
    rows, seen = [], set()
    anchors = page.get_by_text("万在看", exact=False)
    try:
        n = min(anchors.count(), limit)
    except Exception:
        n = 0
    for i in range(n):
        el = anchors.nth(i)
        for depth in (2, 3, 1):
            try:
                row = el.locator(f"xpath=ancestor::div[{depth}]")
                txt = row.inner_text().strip().replace("\n", " ")
            except Exception:
                continue
            if not txt or "万在看" not in txt or len(txt) > 120:
                continue
            key = txt.split("万在看")[0][-40:]
            if key in seen:
                continue
            seen.add(key)
            rows.append((row, txt))
            break
    return rows


def set_hot_topic(page, keywords, idx=0):
    """关联热点：点开下拉 → 抓全部条目 → 按关键词优先级命中第一条 → 点选。

    keywords 支持字符串或字符串列表（按优先级）。榜单是实时的（每小时滚动），
    命中不了就只落盘清单、不硬凑——乱绑无关热点比不绑更伤推荐。
    全程不阻断发布，异常由调用方兜住。
    """
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k.strip() for k in keywords if k and k.strip()]
    if not keywords:
        return False

    row_label = page.get_by_text("关联热点", exact=False).first
    if row_label.count() == 0:
        print("  [热点] 页面上找不到「关联热点」，跳过")
        return False

    # 这一栏是 Semi Design 的可搜索下拉（div.semi-select-filterable，占位「点击输入热点词」）。
    # label 与控件在栅格里是两列，且 .semi-select 在合集选择器上也有，必须限定到本区块。
    try:
        block = row_label.locator(
            "xpath=ancestor::div[contains(@class,'content-obt4oA')]"
        ).first
        box = block.locator("div.semi-select").first
        box.click()
    except Exception as e:
        print(f"  [热点] 打不开热点下拉: {e}")
        return False
    time.sleep(2.0)
    shot(page, f"hot_open_{idx}")

    def _opts():
        out = []
        try:
            loc = page.locator("div.semi-select-option")
            for i in range(min(loc.count(), 60)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    t = el.inner_text().strip().replace("\n", " ")
                    if t:
                        out.append((el, t))
                except Exception:
                    continue
        except Exception:
            pass
        return out

    rows = _opts()

    # 默认榜只按「在看」排序，可能不含我们要的词；逐个关键词在搜索框里试一遍。
    # Semi 的可搜索下拉：输入即过滤，输入框在下拉容器内。
    # 策略：所有关键词都试完，汇总候选后按「在看」取最热的一条（用户口径：同领域挑热度最高的）。
    tried = [("默认榜", rows)]

    def _heat(txt):
        m = re.search(r"([\d.]+)\s*万在看", txt)
        return float(m.group(1)) if m else 0.0

    def _denied(txt):
        return any(w in txt for w in config.HOT_DENY)

    pool = []
    for kw in keywords:
        try:
            inp = block.locator("input").first
            inp.click()
            inp.fill("")
            time.sleep(0.4)
            inp.fill(kw)
            time.sleep(1.8)
        except Exception as e:
            print(f"  [热点] 搜索「{kw}」失败: {e}")
            continue
        opts = _opts()
        tried.append((kw, opts))
        for pos, (el, txt) in enumerate(opts):
            if kw in txt:
                pool.append((pos, txt, kw, _heat(txt)))
    # 默认榜只作日志留档，不参与候选：它按「在看」排序，会把完全无关的大热点顶进来
    # （实测：「vibe知识大赏」搜索时，默认榜的 Kimi 1031 万把目标挤掉了）。

    dump = LOGS / f"hot_list_{idx}.txt"
    with open(dump, "w", encoding="utf-8") as f:
        f.write(f"抓取时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"关键词: {keywords}\n\n")
        for tag, rs in tried:
            f.write(f"--- {tag}：{len(rs)} 条 ---\n")
            for i, (_, txt) in enumerate(rs[:25], 1):
                mark = " [黑名单]" if _denied(txt) else ""
                f.write(f"[{i:02d}] {txt}{mark}\n")
            f.write("\n")
    print(f"  热点候选已存 {dump.name}（搜索 {len(tried) - 1} 组）")

    # 去重 + 过黑名单 + 排序。排序键：关键词优先级 > 热度。
    # ——因为「随便挑个热度高的」也不能让泛词条目把指定活动/话题挤掉（实测「vibe知识大赏」被
    #   「高中知识点vibe一下全懂了」按 0.4 万热度差挤掉）。
    # 注意：这里只留「干净标题」，不留元素引用——多轮搜索之间 DOM 会重渲染，旧 locator 会失效。
    def _clean(txt):
        t = re.sub(r"[\d.]+\s*万在看", "", txt).strip()
        return re.sub(r"\s+[\d.]+\s*$", "", t).strip()

    def _prio(kw):
        return keywords.index(kw) if kw in keywords else len(keywords)

    cands, seen = [], set()
    for pos, txt, kw, heat in sorted(pool, key=lambda x: (_prio(x[2]), -x[3])):
        title = _clean(txt)
        if not title or title in seen:
            continue
        seen.add(title)
        if _denied(txt):
            print(f"  [热点] 拦截黑名单条目: {txt[:30]}")
            continue
        cands.append((title, heat, kw, pos))

    if not cands:
        print("  [热点] 没有可用条目，本条不关联热点")
        page.keyboard.press("Escape")
        return False

    title, heat, kw, pos = cands[0]
    print(f"  选定热点: {title}（{heat}万在看，候选 {len(cands)} 条）")
    # 二次定位：重放同一个关键词，取同一序号的选项，用 force 点击绕过遮挡检测。
    # （Semi 下拉在多轮搜索后 DOM 会重建，旧 locator 一律失效；按序号重放最稳。）
    try:
        inp = block.locator("input").first
        inp.click()
        inp.fill("")
        time.sleep(0.4)
        inp.fill(kw)
        time.sleep(1.8)
        now = _opts()
        with open(LOGS / f"hot_pick_{idx}.txt", "w", encoding="utf-8") as f:
            f.write(f"目标: {title}\n关键词 {kw} 重放后 {len(now)} 条:\n")
            for i, (_, t) in enumerate(now, 1):
                f.write(f"[{i:02d}] {_clean(t)}\n")
        if pos < len(now):
            el, txt = now[pos]
            print(f"  重放命中: {_clean(txt)}")
            el.click(force=True, timeout=5000)
            time.sleep(1.0)
            page.keyboard.press("Escape")
            time.sleep(0.5)
            print(f"  已关联热点: {title}")
            return True
        print(f"    [警告] 重放后序号越界（{pos} >= {len(now)}）")
    except Exception as e:
        print(f"    [警告] 精确点选失败: {e}")

    page.keyboard.press("Escape")
    time.sleep(0.4)
    print("  [热点] 未能选中，本条不关联热点")
    return False

    box.click()
    time.sleep(2.5)
    shot(page, f"hot_open_{idx}")
    rows = _hot_rows(page)

    # 默认榜没抓到 → 用关键词搜一次（搜索框支持直接搜热点词；用最短的词命中率最高）
    if not rows:
        search_kw = min(keywords, key=len)
        try:
            box.fill(search_kw)
            time.sleep(2.5)
            shot(page, f"hot_search_{idx}")
            rows = _hot_rows(page)
        except Exception as e:
            print(f"  [热点] 搜索「{search_kw}」失败: {e}")

    dump = LOGS / f"hot_list_{idx}.txt"
    with open(dump, "w", encoding="utf-8") as f:
        f.write(f"抓取时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"关键词优先级: {keywords}\n共 {len(rows)} 条\n\n")
        for i, (_, txt) in enumerate(rows, 1):
            f.write(f"[{i:02d}] {txt}\n")
    print(f"  热点候选 {len(rows)} 条，清单已存 {dump.name}")

    for kw in keywords:
        for row, txt in rows:
            if kw in txt:
                try:
                    row.click()
                    time.sleep(0.8)
                    print(f"  已关联热点: {txt[:40]}")
                    return True
                except Exception as e:
                    print(f"    [警告] 命中「{kw}」但点击失败: {e}")
                    break
    print(f"  [热点] 没有命中 {keywords} 的条目，本条不关联热点")
    page.keyboard.press("Escape")
    return False


def set_cover(page, cover_path: str, mode: str = "vertical"):
    """上传自定义封面。

    mode="vertical" → 3:4 竖封面（信息流主封面）
    mode="horizontal" → 4:3 横封面
    失败抛异常，绝不静默裸发。
    """
    if not cover_path:
        return
    if not Path(cover_path).exists():
        raise RuntimeError(f"封面文件不存在: {cover_path}")

    # 关掉可能挡住页面的事件/新手引导
    try:
        guide = page.locator('button.shepherd-button:has-text("我知道了")')
        if guide.count() > 0 and guide.first.is_visible():
            guide.first.click()
            time.sleep(0.5)
    except Exception:
        pass
    page.keyboard.press("Escape")
    time.sleep(0.8)
    page.mouse.click(400, 200)
    time.sleep(0.8)

    clicked = _click_cover_entry(page, mode)
    if not clicked:
        raise RuntimeError("找不到「选择封面」入口")

    modal, _ = locate_any(page, config.COVER_SELECTORS["modal"], timeout_ms=15000)
    if not modal:
        raise RuntimeError("封面弹层未出现（COVER_SELECTORS.modal 未命中）")

    tab_key = "vertical_tab" if mode == "vertical" else "horizontal_tab"
    tab, tab_sel = locate_any(page, config.COVER_SELECTORS[tab_key], timeout_ms=10000)
    if tab:
        tab.click()
        print(f"  已切换到{'竖' if mode == 'vertical' else '横'}封面（{tab_sel}）")
    else:
        print(f"  [提示] 未找到{'竖' if mode == 'vertical' else '横'}封面页签，按当前页签继续")
    time.sleep(2)

    file_inp, file_sel = locate_any(page, config.COVER_SELECTORS["file_input"], visible=False, timeout_ms=10000)
    if not file_inp:
        raise RuntimeError("封面弹层里找不到图片 file input")
    file_inp.set_input_files(cover_path)
    print(f"  已选择{'竖' if mode == 'vertical' else '横'}封面图（{file_sel}）: {Path(cover_path).name}")
    time.sleep(2.5)

    done, done_sel = locate_any(page, config.COVER_SELECTORS["done_btn"], timeout_ms=10000)
    if not done:
        raise RuntimeError("封面弹层里找不到「完成」按钮")
    done.click()
    print(f"  已点封面「完成」（{done_sel}）")

    try:
        page.wait_for_selector(config.COVER_SELECTORS["footer"], state="detached", timeout=15000)
    except Exception:
        print("  [提示] 封面弹层未在 15s 内消失，继续")
    time.sleep(1)


def set_schedule(page, publish_at: str):
    """切「定时发布」并填时间；填不进去直接抛异常，避免误发成立即发布。"""
    # 新版是 <label class="radio-...">定时发布</label>，点内部 span 会被 label 拦截，
    # 所以优先点 label 本身，失败再 JS click。
    toggle = None
    for sel in ("label:has-text('定时发布')", "text=定时发布"):
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                toggle = loc
                break
        except Exception:
            continue
    if not toggle:
        raise RuntimeError("找不到『定时发布』单选/开关")
    toggle.scroll_into_view_if_needed(timeout=3000)
    try:
        toggle.click(timeout=3000)
    except Exception:
        toggle.evaluate("el => el.click()")
    time.sleep(1.2)
    try:
        checked = toggle.get_attribute("data-checked")
        if checked is not None:
            print(f"  定时发布单选 data-checked={checked}")
    except Exception:
        pass

    inp, isel = find_first(page, "schedule_input")
    if not inp:
        raise RuntimeError("找不到定时时间输入框")
    inp.scroll_into_view_if_needed(timeout=3000)
    inp.click()
    inp.fill(publish_at.strip())
    time.sleep(0.6)

    val = ""
    try:
        val = inp.input_value()
    except Exception:
        pass
    if publish_at[:10] not in val:
        inp.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.insert_text(publish_at.strip())
        page.keyboard.press("Enter")
        time.sleep(0.6)
        try:
            val = inp.input_value()
        except Exception:
            pass
    page.keyboard.press("Enter")
    time.sleep(0.8)
    # 关掉日期选择浮层，避免它挡住发布按钮
    try:
        page.keyboard.press("Escape")
        time.sleep(0.4)
        page.mouse.click(400, 200)
        time.sleep(0.4)
    except Exception:
        pass
    print(f"  已设定时发布时间: {publish_at}（输入框: {val or isel}）")
    if publish_at[:10] not in val:
        raise RuntimeError(f"定时时间没填上：期望 {publish_at}，实际 {val!r}")


def _dismiss_guide(page):
    try:
        btn = page.locator('button:has-text("我知道了")')
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            time.sleep(0.4)
    except Exception:
        pass


def set_collection(page, name: str):
    """「添加合集」下拉里选名字包含 name 的合集；找不到只警告，不阻断发布。"""
    if not name:
        return True
    _dismiss_guide(page)
    try:
        entry = page.get_by_text("请选择合集", exact=True).first
        if entry.count() == 0:
            row = page.get_by_text("添加合集").first
            entry = row.locator("xpath=following::div[contains(@class,'semi-select')][1]")
        entry.scroll_into_view_if_needed(timeout=3000)
        entry.click()
        time.sleep(1.2)
        opts = page.locator(".semi-select-option, [role='option']")
        texts = []
        for i in range(opts.count()):
            t = (opts.nth(i).inner_text() or "").strip()
            texts.append(t)
            if name in t:
                opts.nth(i).click()
                print(f"  已加入合集: {t}")
                time.sleep(0.8)
                return True
        print(f"  [警告] 合集下拉里没找到「{name}」，候选: {texts}")
    except Exception as e:
        print(f"  [警告] 选合集失败（不阻断）: {e}")
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    return False


def _set_radio(page, text, timeout=5000):
    """点文字完全匹配的 radio label，并校验 data-checked。"""
    label = page.locator(f"label:text-is('{text}')").first
    if label.count() == 0:
        label = page.locator(f"label:has-text('{text}')").first
    if label.count() == 0:
        return False
    label.scroll_into_view_if_needed(timeout=3000)
    if (label.get_attribute("data-checked") or "") == "true":
        return True
    try:
        label.click(timeout=timeout)
    except Exception:
        label.evaluate("el => el.click()")
    time.sleep(0.5)
    return (label.get_attribute("data-checked") or "") == "true"


def set_visibility(page, value: str):
    if not value:
        return True
    if value not in config.VISIBILITIES:
        raise ValueError(f"visibility 只能是 {config.VISIBILITIES}，实际: {value}")
    if not _set_radio(page, value):
        raise RuntimeError(f"设置可见范围失败: {value}")
    print(f"  谁可以看: {value}")
    return True


def set_save_permission(page, allow: bool = True):
    text = "允许" if allow else "不允许"
    if not _set_radio(page, text):
        raise RuntimeError(f"设置保存权限失败: {text}")
    print(f"  保存权限: {text}")
    return True


def set_declaration(page, text: str):
    """自主声明：单次滚到底 + 可见性等待，去掉固定 sleep 与 4 次平滑滚动。"""
    if not text:
        return True
    if text not in config.DECLARATIONS:
        raise ValueError(f"declaration 只能是 {config.DECLARATIONS}，实际: {text}")
    t0 = time.perf_counter()

    def mark(step):
        print(f"    [decl {time.perf_counter() - t0:.2f}s] {step}", flush=True)

    _dismiss_guide(page)
    mark("guide dismissed")

    # 一次滚到底：替代 4× mouse.wheel（每次 wheel 都会触发平滑滚动动画）
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    mark("scrolled")

    # 已经是目标声明则跳过
    try:
        row = page.get_by_text("自主声明").first.locator("xpath=ancestor::div[1]")
        if row.get_by_text(text, exact=False).count() > 0:
            print(f"  自主声明已是: {text}")
            return True
    except Exception:
        pass

    entry = page.get_by_text("请选择自主声明").first
    if entry.count() == 0:
        entry = page.get_by_text("自主声明").first
    if entry.count() == 0:
        raise RuntimeError("找不到「自主声明」入口")
    entry.wait_for(state="visible", timeout=8000)
    mark("entry visible")
    entry.click()
    mark("entry clicked")

    opt = page.locator(f"label:text-is('{text}')").last
    if opt.count() == 0:
        opt = page.get_by_text(text, exact=True).last
    if opt.count() == 0:
        page.keyboard.press("Escape")
        raise RuntimeError(f"声明面板里没有选项: {text}")
    opt.wait_for(state="visible", timeout=5000)
    mark("option visible")
    # 单选项在弹层动画里，Playwright 的 actionability 等待会卡 15s；
    # 直接派发 DOM click（React 受控组件同样会收到）。
    try:
        opt.evaluate("el => el.click()")
    except Exception:
        opt.click(force=True, timeout=2000)
    mark("option clicked")

    ok = page.get_by_role("button", name="确定").last
    if ok.count() == 0:
        ok = page.locator('button:has-text("确定")').last
    if ok.count() > 0:
        ok.wait_for(state="visible", timeout=3000)
        ok.click()
    mark("confirmed")
    try:
        page.locator("[role='dialog'], .semi-modal").last.wait_for(state="hidden", timeout=2000)
    except Exception:
        pass
    mark("done")
    print(f"  自主声明: {text}")
    return True


def set_aigc(page):
    """兼容旧调用：内容由 AI 生成。"""
    return set_declaration(page, "内容由AI生成")


# ---------------------------------------------------------------- 单集流程

def publish_one(ctx, item, idx, execute, interactive=True):
    vis = item.get("visibility")
    if item.get("collection") and vis not in (None, "", "公开"):
        raise RuntimeError(
            "平台限制：加入合集的视频不能设为「好友可见 / 仅自己可见」；"
            "请去掉 collection，或把 visibility 设为「公开」"
        )
    print(f"\n=== [{idx}] {Path(item['file']).name} ===")
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.goto(config.UPLOAD_URL)
    time.sleep(3)

    # 清掉上次遗留的「未发布视频」草稿横幅，否则会影响本次发布
    try:
        abandon = page.get_by_text("放弃", exact=True)
        if abandon.count() > 0 and abandon.first.is_visible():
            print("  检测到上次未发布草稿，点「放弃」清掉")
            abandon.first.click()
            time.sleep(1.5)
            page.goto(config.UPLOAD_URL)
            time.sleep(2)
    except Exception:
        pass

    # 1. 上传视频
    finp, _ = find_first(page, "file_input")
    if not finp:
        shot(page, "err_no_file_input")
        raise RuntimeError("找不到上传 file input，看截图校准 SELECTORS.file_input")
    finp.set_input_files(item["file"])
    print("  已选文件，等待上传/转码完成...")
    if not wait_upload_done(page):
        shot(page, "err_upload_timeout")
        raise RuntimeError("上传超时未就绪，看截图")
    shot(page, f"uploaded_{idx}")

    # 2. 关联热点（视频传完即可操作，不等其它字段；可选，失败不阻断）
    if item.get("hot_topic"):
        try:
            set_hot_topic(page, item["hot_topic"], idx)
        except Exception as e:
            shot(page, "err_hot_topic")
            print(f"  [警告] 关联热点设置失败（不阻断）: {e}")

    # 3. 标题 + 正文 + 话题
    title, body, tags = split_manifest_text(item["text"])
    has_title_input = fill_title(page, title)

    chosen, bind = tags, False
    topic_details = []
    if item.get("topics"):
        try:
            plan = topics.resolve(
                ctx, item["topics"], fallback_seeds=tags, series=item.get("_series", "")
            )
            topics.print_plan(plan)
            if plan["api_ok"] and plan["names"]:
                chosen, bind = plan["names"], True
                topic_details = plan["pinned"] + plan["selected"]
            elif not plan["api_ok"]:
                print("  [警告] 话题热度接口不可用，回退清单里的 #话题")
            else:
                print("  [警告] 没有可用话题，回退清单里的 #话题")
        except Exception as e:
            print(f"  [警告] 话题热度筛选失败（{e}），回退清单里的 #话题")

    if body or chosen:
        fill_text(page, body, chosen, bind=bind)
    elif not has_title_input:
        # 没有独立标题框且没有正文/话题：整段写进描述区
        fill_text(page, title, [])
    print("  文案填写完成")

    # 3. 封面（竖封面为主，必设；横封面尽力而为）
    if item.get("cover"):
        try:
            set_cover(page, item["cover"], "vertical")
        except Exception as e:
            shot(page, "err_cover")
            raise RuntimeError(f"竖封面上传失败（已中止，未发布）: {e}")
    if item.get("cover_h"):
        try:
            set_cover(page, item["cover_h"], "horizontal")
        except Exception as e:
            shot(page, "err_cover_h")
            print(f"  [警告] 横封面上传失败（不阻断，竖封面已设）: {e}")
    if not item.get("cover_h") and not item.get("cover"):
        print("  [提示] 未指定封面，使用平台自动截帧")

    # 4. 合集 + 声明 + 可见范围 + 保存权限
    if item.get("collection"):
        set_collection(page, item["collection"])
    declaration = item.get("declaration") or ("内容由AI生成" if item.get("aigc") else "")
    if declaration:
        try:
            set_declaration(page, declaration)
        except Exception as e:
            shot(page, "err_declaration")
            raise RuntimeError(f"自主声明设置失败（已中止，未发布）: {e}")
    if item.get("visibility"):
        try:
            set_visibility(page, item["visibility"])
        except Exception as e:
            shot(page, "err_visibility")
            raise RuntimeError(f"可见范围设置失败（已中止，未发布）: {e}")
    if item.get("allow_save") is not None:
        try:
            set_save_permission(page, bool(item["allow_save"]))
        except Exception as e:
            shot(page, "err_save")
            raise RuntimeError(f"保存权限设置失败（已中止，未发布）: {e}")

    # 4. 定时 / 立即
    if item.get("publish_at"):
        set_schedule(page, item["publish_at"])
        print(f"  已设定时: {item['publish_at']}")
    time.sleep(1)
    shot(page, f"ready_{idx}")

    # 5. 人工确认（interactive=False 时跳过：dry-run 直接下一集，execute 视同 --yes）
    if interactive:
        mode = "真发布" if execute else "DRY-RUN（不会点发布）"
        ans = ""
        while True:
            prompt = f"  [{mode}] 浏览器核对第 {idx} 集，回车=继续{'发布' if execute else '下一集'}，s=跳过，q=中止: "
            ans = input(prompt).strip().lower()
            if ans in ("", "s", "q"):
                break
        if ans == "q":
            page.close()
            return {"status": "abort", "url": page.url, "topics": chosen, "topic_details": topic_details}
        if ans == "s":
            page.close()
            return {"status": "skip", "url": page.url, "topics": chosen, "topic_details": topic_details}

    if execute:
        btn, _ = find_first(page, "publish_btn")
        if not btn:
            shot(page, "err_no_publish_btn")
            raise RuntimeError("找不到发布按钮")
        # 等封面检测完成（未完成时点发布可能被拦）
        try:
            page.get_by_text("检测通过").first.wait_for(timeout=30000)
        except Exception:
            pass
        btn.scroll_into_view_if_needed(timeout=5000)
        btn.click()
        ok = False
        for i in range(15):
            time.sleep(1)
            print(f"    发布后 {i + 1}s: {page.url}")
            if "content/manage" in page.url:
                ok = True
                break
            try:
                body = page.inner_text("body")
                if "发布成功" in body:
                    ok = True
                    break
            except Exception:
                pass
        shot(page, f"published_{idx}")
        print(f"  发布{'成功' if ok else '结果未知（看截图）'}")
        page.close()
        return {"status": "ok" if ok else "unknown", "url": page.url,
                "topics": chosen, "topic_details": topic_details}
    else:
        page.close()
        return {"status": "dryrun", "url": page.url,
                "topics": chosen, "topic_details": topic_details}


# ---------------------------------------------------------------- 批量入口

def classify_error(exc) -> str:
    """把异常归类成 Agent 可决策的错误码。"""
    msg = str(exc)
    low = msg.lower()
    if "登录" in msg or "扫码" in msg or "login" in low:
        return "auth_expired"
    if "找不到" in msg or "未找到" in msg or "选择器" in msg or "intercept" in low:
        return "selector_drift"
    if "超时" in msg or "timeout" in low:
        return "upload_timeout"
    if "平台限制" in msg or "不能" in msg:
        return "platform_rejected"
    return "error"


def run_batch(items, profile_path, execute, auto_yes, interval, interactive=False, on_result=None):
    results = []
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(profile_path),
                channel="chrome",
                headless=False,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
        except Exception as e:
            print(f"!! 启动浏览器档案失败（可能上一个 Chrome 还占着 profile）: {e}")
            raise
        # 关掉上次会话恢复出来的标签页，避免干扰
        for pg in list(ctx.pages):
            try:
                pg.close()
            except Exception:
                pass
        # 持久化 context 里关掉最后一个页面会让 Chrome 退出；留一个空白页保活
        try:
            keepalive = ctx.new_page()
            keepalive.goto("about:blank")
        except Exception:
            pass
        for i, it in enumerate(items, 1):
            idx = it.get("_idx", i)
            try:
                res = publish_one(ctx, it, idx, execute, interactive)
            except Exception as e:
                print(f"  !! 第 {idx} 集失败: {e}")
                res = {
                    "status": "fail",
                    "error_code": classify_error(e),
                    "error": str(e),
                    "url": "",
                }
            res["index"] = idx
            res["file"] = it.get("file", "")
            results.append(res)
            if on_result:
                try:
                    on_result(res)
                except Exception as e:
                    print(f"  !! 写入状态文件失败（不阻断）: {e}")
            if res["status"] == "abort":
                break
            if i < len(items):
                import random
                wait = random.randint(int(interval * 0.8), int(interval * 1.5))
                print(f"  间隔 {wait}s 后处理下一集...")
                time.sleep(wait)
        ctx.close()
    return results


def exit_code(results) -> int:
    return 1 if any(r.get("status") in ("fail", "unknown") for r in results) else 0


def summarize(results):
    print("\n==== 结果汇总 ====")
    for r in results:
        code = f" ({r['error_code']})" if r.get("error_code") else ""
        print(f"  [{r['index']}] {r['status']}{code}")
    fails = [r["index"] for r in results if r.get("status") in ("fail", "unknown")]
    if fails:
        print(f"!! 有 {len(fails)} 集未成功：{fails}。看 logs/ 截图定位；修复后可用 --only {','.join(map(str, fails))} 补跑")
        return 1
    return 0
