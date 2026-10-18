# -*- coding: utf-8 -*-
"""话题热度筛选（纯数据层，不碰页面）。

数据源（2026-10-18 实测）：发布页输入 # 时页面自己调用的联想接口
  GET https://creator.douyin.com/aweme/v1/search/challengesug/
      ?source=challenge_create&aid=2906&keyword=<关键词>&cookie_enabled=true
返回 sug_list: [{"cha_name": "创业", "view_count": 258348101175,
                 "cid": "...", "group_id": "...", "tag": 0}]
其中 view_count = 话题累计播放量，与发布页联想列表显示的数字一致。
带登录态 cookie 直接 GET 即可，无需 a_bogus 签名（用 Playwright 的 context.request）。

选词规则（用户 2026-10-18 定）：
1. 第 1 个话题固定为主题名（theme），豁免热度；
2. 第 2 个可用 pin 指定（豁免热度，"随意"但建议相关）；
3. 其余从 seed（约 10 个）的联想结果里按热度挑：view_count >= min_heat（默认 1 亿）、
   话题名必须包含 seed（相关性闸门，防止 "AED" 选出 "#艾尔登法环"）、
   每个 seed 最多 max_per_seed 个、按热度降序，取 count 个；
4. 总话题数不超过 MAX_TOPICS（抖音描述区上限 5）。
"""

import re
import time
from urllib.parse import quote

MIN_HEAT = 100_000_000
MAX_TOPICS = 5
SUGGEST_URL = (
    "https://creator.douyin.com/aweme/v1/search/challengesug/"
    "?source=challenge_create&aid=2906&keyword={kw}&cookie_enabled=true"
)

_HEAT_UNITS = {"亿": 1e8, "万": 1e4, "千": 1e3, "w": 1e4, "W": 1e4, "k": 1e3, "K": 1e3}


def norm(name) -> str:
    """话题名归一化：去 #、去零宽空格、去首尾空白。"""
    return str(name or "").strip().lstrip("#").replace("\u200b", "").strip()


def parse_heat(value) -> int:
    """热度阈值解析：100000000 / '1e8' / '1亿' / '1.5亿' / '5000万' 都行。"""
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "").replace("_", "")
    try:
        return int(float(s))
    except ValueError:
        pass
    m = re.fullmatch(r"([\d.]+)\s*(亿|万|千|w|W|k|K)", s)
    if not m:
        raise ValueError(f"热度格式无法识别: {value!r}（示例：100000000 / 1e8 / 1亿）")
    return int(float(m.group(1)) * _HEAT_UNITS[m.group(2)])


def format_heat(n) -> str:
    n = int(n or 0)
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def is_relevant(name: str, seed: str) -> bool:
    """相关性闸门：话题名必须包含 seed（英文不区分大小写）。

    联想接口偶尔会跑偏（"AED" -> "艾尔登法环"），纯按热度取最大会选到完全无关的话题。
    """
    seed = norm(seed).casefold()
    return bool(seed) and seed in norm(name).casefold()


def fetch_suggestions(ctx, keyword: str, cache=None, timeout=15000):
    """查一个关键词的联想话题；失败重试一次，仍失败返回 []。"""
    key = norm(keyword)
    if cache is not None and key in cache:
        return cache[key]
    items = []
    for attempt in range(2):
        try:
            resp = ctx.request.get(SUGGEST_URL.format(kw=quote(key, safe="")), timeout=timeout)
            if resp.status == 200:
                data = resp.json()
                if data.get("status_code", 0) == 0:
                    items = data.get("sug_list") or []
                    break
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.6)
    if cache is not None:
        cache[key] = items
    return items


def _pinned_entry(ctx, name, source, cache):
    """置顶话题也查一次，用于展示热度 / 确认它是真话题。"""
    items = fetch_suggestions(ctx, name, cache)
    matched = next(
        (it for it in items if norm(it.get("cha_name")).casefold() == norm(name).casefold()),
        None,
    )
    return {
        "name": norm(name),
        "view_count": int(matched.get("view_count") or 0) if matched else 0,
        "cid": (matched or {}).get("cid", ""),
        "source": source,
    }


def resolve(ctx, cfg, fallback_seeds=(), series="", cache=None):
    """执行选词，返回可直接交给页面填写的计划。

    cfg:
      theme        第 1 个话题（缺省用 series）
      pin          第 2 个起额外置顶的话题（list，豁免热度）
      seeds        约 10 个候选关键词
      min_heat     热度阈值（默认 1 亿）
      count        按热度选几个（默认 3）
      max_per_seed 每个 seed 最多入选几个（默认 1，保证话题分散）
    """
    theme = norm(cfg.get("theme") or series)
    pin = [norm(x) for x in (cfg.get("pin") or []) if norm(x)]
    seeds = [norm(x) for x in (cfg.get("seeds") or fallback_seeds) if norm(x)]
    min_heat = parse_heat(cfg.get("min_heat", MIN_HEAT))
    count = int(cfg.get("count", 3))
    max_per_seed = max(1, int(cfg.get("max_per_seed", 1)))
    if cache is None:
        cache = {}

    pinned, seen = [], set()
    for name, source in [(theme, "theme")] + [(p, "pin") for p in pin]:
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            pinned.append(_pinned_entry(ctx, name, source, cache))
    pinned = pinned[:MAX_TOPICS]
    count = max(0, min(count, MAX_TOPICS - len(pinned)))

    candidates, seen = [], set(p["name"].casefold() for p in pinned)
    fetched = 0
    for seed in seeds:
        items = fetch_suggestions(ctx, seed, cache)
        if items:
            fetched += 1
        for it in items:
            name = norm(it.get("cha_name"))
            if not name or name.casefold() in seen:
                continue
            if not is_relevant(name, seed):
                continue
            heat = int(it.get("view_count") or 0)
            if heat < min_heat:
                continue
            seen.add(name.casefold())
            candidates.append({
                "name": name,
                "view_count": heat,
                "cid": it.get("cid", ""),
                "seed": seed,
            })
        if seeds and seed != seeds[-1]:
            time.sleep(0.4)

    candidates.sort(key=lambda c: -c["view_count"])
    selected, per_seed = [], {}
    for c in candidates:
        if len(selected) >= count:
            break
        if per_seed.get(c["seed"], 0) >= max_per_seed:
            continue
        selected.append(c)
        per_seed[c["seed"]] = per_seed.get(c["seed"], 0) + 1

    names = [p["name"] for p in pinned] + [c["name"] for c in selected]
    return {
        "api_ok": fetched > 0,
        "theme": theme,
        "pinned": pinned,
        "selected": selected,
        "names": names[:MAX_TOPICS],
        "candidates": candidates[:30],
        "min_heat": min_heat,
        "stats": {
            "seeds": len(seeds),
            "fetched": fetched,
            "qualified": len(candidates),
            "selected": len(selected),
        },
    }


def print_plan(plan, stream=None):
    """人读版：置顶 + 入选 + 候选统计。"""
    import sys

    out = stream or sys.stdout
    st = plan.get("stats", {})
    print(
        f"\n  话题筛选：seed {st.get('seeds', 0)} 个，"
        f"阈值 {format_heat(plan.get('min_heat', MIN_HEAT))}，"
        f"候选 {st.get('qualified', 0)} 条，入选 {st.get('selected', 0)} 条",
        file=out,
    )
    for i, p in enumerate(plan.get("pinned", []), 1):
        print(f"    {i}. #{p['name']:<18} {format_heat(p['view_count']):>10}  置顶（{p['source']}）", file=out)
    offset = len(plan.get("pinned", []))
    for j, s in enumerate(plan.get("selected", []), offset + 1):
        print(
            f"    {j}. #{s['name']:<18} {format_heat(s['view_count']):>10}  seed={s['seed']}",
            file=out,
        )
    if not plan.get("selected"):
        print("    （没有达到热度阈值且相关的话题）", file=out)
    total = len(plan.get("names", []))
    if total > MAX_TOPICS:
        print(f"    !! 超过 {MAX_TOPICS} 个话题上限，已截断", file=out)
