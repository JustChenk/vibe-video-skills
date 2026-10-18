# -*- coding: utf-8 -*-
"""统一命令行入口（Agent-first，无 GUI）。

  douyin-publisher login   [--profile DIR]
  douyin-publisher gen     <系列目录> [-o 清单.json] [--prefer 关键字]
  douyin-publisher doctor  [--deep] [--json]
  douyin-publisher topics  --seed 创业 --seed 职场 [--theme 主题名] [--json]
  douyin-publisher history [--limit 20] [--json]
  douyin-publisher publish <清单.json> [--execute] [--at 时间] [--json]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, auth, config, history, manifest, topics, uploader


def _profile_path(args) -> Path:
    return Path(getattr(args, "profile", None) or config.PROFILE_DIR).expanduser()


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_login(args):
    auth.login(_profile_path(args))


def cmd_gen(args):
    series_dir = Path(args.series_dir).resolve()
    if not series_dir.is_dir():
        manifest.fail(f"目录不存在: {series_dir}")
    data = manifest.gen_manifest(series_dir, args.prefer)
    if not data["items"]:
        manifest.fail(f"在 {series_dir} 下没找到 mp4")
    out = Path(args.output) if args.output else series_dir / "发布清单.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {out}，共 {len(data['items'])} 集，请逐条补齐 text 后再 publish")


def cmd_doctor(args):
    profile = _profile_path(args)
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": ok, "detail": str(detail)})

    add("version", True, __version__)
    profile_ok = profile.is_dir() and any(profile.iterdir())
    add("profile", profile_ok, profile)
    chrome_candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    found = next((p for p in chrome_candidates if p.exists()), None)
    add("browser", bool(found), found or "未找到 Chrome/Edge")
    if args.deep and profile_ok:
        try:
            ok, url = auth.check_login(profile)
            add("login", ok, url)
        except Exception as e:
            add("login", False, f"{type(e).__name__}: {e}")
    else:
        add("login", None, "未检查（加 --deep 打开浏览器验证）")

    ok = all(c["ok"] for c in checks if c["ok"] is not None)
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            flag = "OK" if c["ok"] else ("--" if c["ok"] is None else "!!")
            print(f"[{flag}] {c['name']}: {c['detail']}")
    sys.exit(0 if ok else 1)


def cmd_topics(args):
    """只查话题热度并出选词结果，不上传、不改发布状态。"""
    profile = _profile_path(args)
    if not profile.is_dir():
        manifest.fail(f"未找到浏览器登录档案 {profile}，请先跑: douyin-publisher login")

    theme = args.theme
    pin = list(args.pin or [])
    seeds = list(args.seed or [])
    if args.seeds:
        seeds += [s.strip() for s in args.seeds.split(",") if s.strip()]
    count = args.count
    min_heat = args.min_heat
    max_per_seed = args.max_per_seed

    if args.manifest:
        items = manifest.load_manifest(Path(args.manifest))
        idx = args.index - 1
        if idx < 0 or idx >= len(items):
            manifest.fail(f"--index {args.index} 超出范围（清单共 {len(items)} 条）")
        tp = items[idx].get("topics") or {}
        theme = args.theme or tp.get("theme") or items[idx].get("_series", "")
        pin = args.pin or tp.get("pin") or []
        seeds = seeds or tp.get("seeds") or []
        count = count if count is not None else tp.get("count")
        min_heat = min_heat if min_heat is not None else tp.get("min_heat", topics.MIN_HEAT)
        max_per_seed = (
            max_per_seed if max_per_seed is not None else tp.get("max_per_seed", 1)
        )

    if not seeds:
        manifest.fail("至少给一个 --seed，或用 --manifest 读清单里的 topics.seeds")

    cfg = {
        "theme": theme or "",
        "pin": pin,
        "seeds": seeds,
        "min_heat": min_heat if min_heat is not None else topics.MIN_HEAT,
        "count": count,
        "max_per_seed": max_per_seed if max_per_seed is not None else 1,
    }

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), channel="chrome", headless=False,
            viewport={"width": 1440, "height": 900}, locale="zh-CN",
        )
        try:
            page = ctx.new_page()
            page.goto(config.HOME_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            if auth._find_logged_in_page(ctx) is None:
                manifest.fail("登录态失效（未检测到创作者中心导航），请先跑 douyin-publisher login")
            plan = topics.resolve(ctx, cfg, series=theme or "")
        finally:
            ctx.close()

    payload = {
        "ok": plan["api_ok"],
        "theme": plan["theme"],
        "pinned": plan["pinned"],
        "selected": plan["selected"],
        "names": plan["names"],
        "stats": plan["stats"],
        "min_heat": plan["min_heat"],
        "candidates": plan["candidates"],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        topics.print_plan(plan)
        if not plan["api_ok"]:
            print("!! 话题接口没有返回数据（可能登录态失效或接口改版）")
    sys.exit(0 if plan["api_ok"] else 1)


def _record_history(args, items, results):
    """真发布后追加 Markdown/CSV 记录；失败只警告，不阻断。"""
    if args.no_history or not args.execute:
        return
    try:
        info = history.record(items, results, Path(args.manifest), args.history)
    except Exception as e:
        print(f"!! 发布记录写入失败（不影响发布）: {e}", file=sys.stderr)
        return
    if not info:
        return
    stream = sys.stderr if args.json else sys.stdout
    print(f"发布记录已追加：{info['md']}", file=stream)
    print(f"           CSV：{info['csv']}（{info['rows']} 行）", file=stream)


def cmd_history(args):
    md = history.resolve_path(args.path, args.manifest)
    if not md.exists():
        print(f"还没有发布记录：{md}")
        print("真发布一次后会自动生成（或发布时用 --history 指定路径）。")
        return
    if args.json:
        rows = history.read_rows(md, args.limit)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"# {md}\n")
    print(history.tail_markdown(md, args.limit))


def cmd_publish(args):
    real_stdout = sys.stdout
    if args.json:
        # 过程日志全部走 stderr，stdout 只留最终 JSON，方便 Agent 直接解析
        sys.stdout = sys.stderr
    profile = _profile_path(args)
    if not profile.is_dir():
        manifest.fail(f"未找到浏览器登录档案 {profile}，请先跑: douyin-publisher login")
    try:
        items = manifest.load_manifest(Path(args.manifest))
    except manifest.ManifestError as e:
        manifest.fail(str(e))

    for i, it in enumerate(items, 1):
        it["_idx"] = i

    if args.only:
        wanted = {int(x) for x in args.only.split(",")}
        items = [it for it in items if it["_idx"] in wanted]
        print(f"补跑模式：只处理第 {sorted(wanted)} 集，共 {len(items)} 条")

    if args.now and args.at:
        manifest.fail("--now 与 --at 不能同时使用")
    if args.now:
        for it in items:
            it["publish_at"] = ""
        print("已按 --now 强制立即发布（覆盖清单 publish_at）")
    elif args.at:
        try:
            manifest.datetime_from_str(args.at)
        except ValueError:
            manifest.fail(f"--at 格式应为 'YYYY-MM-DD HH:MM'，实际: {args.at}")
        for it in items:
            it["publish_at"] = args.at.strip()
        print(f"已按 --at 统一定时发布: {args.at}")

    if args.visibility:
        for it in items:
            it["visibility"] = args.visibility
        print(f"已按 --visibility 统一设置可见范围: {args.visibility}")
    if args.declaration is not None:
        for it in items:
            it["declaration"] = args.declaration
        print(f"已按 --declaration 统一设置自主声明: {args.declaration or '（不设置）'}")
    if args.no_save:
        for it in items:
            it["allow_save"] = False
        print("已按 --no-save 关闭保存权限")
    if args.no_collection:
        for it in items:
            it["collection"] = ""
        print("已按 --no-collection 取消合集")
    elif args.collection is not None:
        for it in items:
            it["collection"] = args.collection
        print(f"已按 --collection 统一设置合集: {args.collection or '（不设置）'}")

    interactive = bool(args.interactive)
    print(f"预检通过：{len(items)} 集，模式={'执行' if args.execute else 'DRY-RUN'}")
    if args.execute and not interactive:
        print("[非交互] execute 模式将逐集自动发布，请确认你已批准本批次！")

    if args.json:
        results = uploader.run_batch(
            items, profile, args.execute, args.yes, args.interval, interactive
        )
        _record_history(args, items, results)
        payload = {
            "ok": uploader.exit_code(results) == 0,
            "mode": "execute" if args.execute else "dryrun",
            "manifest": str(Path(args.manifest).resolve()),
            "results": results,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.result_file:
            _write_json(args.result_file, payload)
        print(text, file=real_stdout)
        sys.exit(0 if payload["ok"] else 1)

    results = uploader.run_batch(items, profile, args.execute, args.yes, args.interval, interactive)
    _record_history(args, items, results)
    if args.result_file:
        _write_json(args.result_file, {"results": results})
    sys.exit(uploader.summarize(results))


def main():
    ap = argparse.ArgumentParser(
        prog="douyin-publisher",
        description="抖音成品视频批量发布（浏览器自动化，Agent-first，dry-run 默认）",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="扫码登录并保存登录态")
    p_login.add_argument("--profile", default=None, help="浏览器档案目录（默认 ~/.douyin_publisher/chrome-profile）")
    p_login.set_defaults(func=cmd_login)

    p_gen = sub.add_parser("gen", help="扫描系列目录生成发布清单骨架")
    p_gen.add_argument("series_dir")
    p_gen.add_argument("-o", "--output", default=None)
    p_gen.add_argument("--prefer", default="卡点版", help="优先匹配的文件名关键字（默认 卡点版）")
    p_gen.set_defaults(func=cmd_gen)

    p_doc = sub.add_parser("doctor", help="自检：CLI/档案/浏览器/登录态")
    p_doc.add_argument("--deep", action="store_true", help="打开浏览器实际验证登录态（约 10 秒）")
    p_doc.add_argument("--json", action="store_true", help="输出 JSON")
    p_doc.add_argument("--profile", default=None, help="浏览器档案目录")
    p_doc.set_defaults(func=cmd_doctor)

    p_top = sub.add_parser("topics", help="按热度筛选话题（只查询，不上传不发布）")
    p_top.add_argument("--seed", action="append", default=[],
                       help="候选关键词，可重复（约 10 个）")
    p_top.add_argument("--seeds", default=None, help="逗号分隔的候选关键词")
    p_top.add_argument("--theme", default=None, help="第 1 个话题（主题名，豁免热度）")
    p_top.add_argument("--pin", action="append", default=[],
                       help="额外置顶话题（豁免热度），可重复")
    p_top.add_argument("--min-heat", default=None,
                       help="热度阈值，如 1亿 / 100000000（默认 1亿）")
    p_top.add_argument("--count", type=int, default=None, help="按热度选几个（默认填满到 5；可自定义，上限 5）")
    p_top.add_argument("--max-per-seed", type=int, default=None,
                       help="每个 seed 最多入选几个（默认 1，保证分散）")
    p_top.add_argument("--manifest", default=None,
                       help="从清单某条的 topics 配置读取 seed/theme/pin")
    p_top.add_argument("--index", type=int, default=1,
                       help="配合 --manifest 指定第几条（默认 1）")
    p_top.add_argument("--json", action="store_true", help="输出 JSON")
    p_top.add_argument("--profile", default=None, help="浏览器档案目录")
    p_top.set_defaults(func=cmd_topics)

    p_pub = sub.add_parser("publish", help="按清单批量发布")
    p_pub.add_argument("manifest")
    p_pub.add_argument("--execute", action="store_true", help="真发布（默认 dry-run）")
    p_pub.add_argument("--yes", action="store_true", help="execute 模式下免逐集确认（不建议）")
    p_pub.add_argument("--interval", type=int, default=config.DEFAULT_INTERVAL, help="集间隔秒数基准")
    p_pub.add_argument("--only", default=None, help="只跑指定序号，如 --only 3,5（补跑失败集）")
    p_pub.add_argument("--profile", default=None, help="浏览器档案目录")
    p_pub.add_argument("--at", default=None,
                       help="统一定时发布时间，如 '2026-10-18 08:10'（覆盖清单 publish_at）")
    p_pub.add_argument("--now", action="store_true",
                       help="强制立即发布（覆盖清单 publish_at）")
    p_pub.add_argument("--visibility", choices=config.VISIBILITIES, default=None,
                       help="统一设置谁可以看（覆盖清单 visibility）")
    p_pub.add_argument("--declaration", choices=config.DECLARATIONS, default=None,
                       help="统一设置自主声明（覆盖清单 declaration）")
    p_pub.add_argument("--no-save", action="store_true",
                       help="保存权限设为「不允许」")
    p_pub.add_argument("--collection", default=None,
                       help="统一设置合集名（覆盖清单 collection）")
    p_pub.add_argument("--no-collection", action="store_true",
                       help="取消合集（覆盖清单 collection）")
    p_pub.add_argument("--interactive", action="store_true",
                       help="逐集人工确认（默认关闭，适合 Agent 批处理）")
    p_pub.add_argument("--non-interactive", action="store_true", help=argparse.SUPPRESS)
    p_pub.add_argument("--json", action="store_true",
                       help="stdout 只输出结果 JSON（过程日志走 stderr）")
    p_pub.add_argument("--result-file", default=None,
                       help="把结果 JSON 另存到文件")
    p_pub.add_argument("--history", default=None,
                       help="发布记录 md 路径（默认 <项目根>/.douyin-publisher/发布记录.md；同名 CSV 并列）")
    p_pub.add_argument("--no-history", action="store_true", help="不写发布记录")
    p_pub.set_defaults(func=cmd_publish)

    p_his = sub.add_parser("history", help="查看发布记录（最近 N 条）")
    p_his.add_argument("--path", default=None,
                       help="记录 md 路径或目录（默认 <项目根>/.douyin-publisher/发布记录.md）")
    p_his.add_argument("--manifest", default=None,
                       help="按清单定位项目根（不在项目根目录跑时用）")
    p_his.add_argument("--limit", type=int, default=20, help="显示最近几条（默认 20）")
    p_his.add_argument("--json", action="store_true", help="输出 JSON（从同名 CSV 读）")
    p_his.set_defaults(func=cmd_history)

    args = ap.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args.func(args)


if __name__ == "__main__":
    main()
