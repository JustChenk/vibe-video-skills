# -*- coding: utf-8 -*-
"""扫码登录，登录态保存在固定 Chrome 用户目录（持久化 profile）。

为什么不用 storage_state：
- storage_state 只带 cookie/localStorage，每次在新临时 profile 里恢复，缺设备指纹
  （IndexedDB/密钥/Service Worker），抖音会当成“新设备”把 session 踢掉；
- 持久化 profile 保留完整浏览器状态，扫一次可长期复用，也少一次风控判定。

检测策略（2026-10 抖音新版首页）：
- 不能只看 URL：未登录时也会停在 creator-micro/home 并弹「扫码登录」浮层；
- 不能只看「发布视频」文案：新版首页没有；
- 判据 = URL 在 creator-micro、无「扫码登录」可见浮层，且左侧导航至少一个可见。
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import config

NAV_TEXTS = ("内容管理", "数据中心", "作品发布")


def _page_logged_in(pg) -> bool:
    try:
        url = pg.url
    except Exception:
        return False
    if "creator.douyin.com" not in url or "creator-micro" not in url or "login" in url:
        return False
    try:
        if pg.get_by_text("扫码登录").first.is_visible():
            return False
    except Exception:
        pass
    for text in NAV_TEXTS:
        try:
            loc = pg.get_by_text(text)
            if loc.count() > 0 and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


def _find_logged_in_page(ctx):
    for pg in ctx.pages:
        if _page_logged_in(pg):
            return pg
    return None


def check_login(profile_path: Path):
    """打开持久档案访问首页，返回 (是否已登录, 当前URL)。用于 doctor --deep。"""
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile_path),
            channel="chrome",
            headless=False,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(8000)
            page.goto(config.HOME_URL)
            page.wait_for_timeout(6000)
            ok = _find_logged_in_page(ctx) is not None
            return ok, page.url
        finally:
            ctx.close()


def login(profile_path: Path):
    profile_path.mkdir(parents=True, exist_ok=True)
    print(f"[1/3] 启动 Chrome（持久化档案: {profile_path}）...", flush=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile_path),
            channel="chrome",
            headless=False,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(5000)
        page.goto(config.HOME_URL)
        print("[2/3] 请在弹出的浏览器里用抖音 App 扫码登录（已登录会自动跳过）...", flush=True)
        deadline = time.time() + config.LOGIN_TIMEOUT
        logged_in = None
        last_report = 0
        while time.time() < deadline:
            logged_in = _find_logged_in_page(ctx)
            if logged_in:
                break
            now = time.time()
            if now - last_report >= 5:
                last_report = now
                try:
                    urls = " | ".join(pg.url for pg in ctx.pages)
                except Exception:
                    urls = "?"
                print(f"    等待登录... 当前页面: {urls}", flush=True)
            time.sleep(2)
        if not logged_in:
            try:
                Path("logs").mkdir(exist_ok=True)
                shot = Path("logs") / f"{time.strftime('%H%M%S')}_login_timeout.png"
                page.screenshot(path=str(shot), full_page=True)
                print(f"    超时截图: {shot}", flush=True)
            except Exception:
                pass
            print("!! 等待超时未检测到登录成功，退出。请重跑 login。", flush=True)
            ctx.close()
            sys.exit(1)
        time.sleep(3)  # 等 cookie/存储写完
        print(f"[3/3] 登录态已保存在档案目录: {profile_path}", flush=True)
        ctx.close()
    print("完成。下一步：gen 生成发布清单，或直接 publish。")
