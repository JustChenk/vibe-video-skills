# -*- coding: utf-8 -*-
"""发布清单（manifest）的生成、读取与校验。

manifest 格式（JSON）：
{
  "series": "系列名",
  "items": [
    {"file": "成片.mp4 绝对路径",
     "cover": "可选，封面图路径（v0.1 仅提示，不自动设置）",
     "text":  "标题 + #话题 #话题",
     "publish_at": ""            // 留空=立即发布；或 "2026-10-17 18:00"
    }, ...
  ]
}
"""
import json
import sys
from pathlib import Path

from . import config

# 扫描系列目录时跳过的子目录（工程中间产物，不含成片）
SKIP_DIRS = {"frames", "preview", "tmp", "research", "tools", "auth", "logs"}

PLACEHOLDER_MARK = "【待填写"


class ManifestError(Exception):
    pass


def scan_series(series_dir: Path, prefer: str = "卡点版") -> list[dict]:
    """每个子目录（一集）挑一个最合适的 mp4；系列根目录下的 mp4 也收。"""
    results = []
    tops = sorted(series_dir.glob("*.mp4"))
    if tops:
        results.extend(tops)
    for ep_dir in sorted(p for p in series_dir.iterdir() if p.is_dir() and p.name not in SKIP_DIRS):
        mp4s = list(ep_dir.rglob("*.mp4"))
        if not mp4s:
            continue
        hit = [m for m in mp4s if prefer in m.name]
        chosen = hit[0] if hit else mp4s[0]
        results.append(chosen)
    return results


def gen_manifest(series_dir: Path, prefer: str = "卡点版") -> dict:
    items = []
    for v in scan_series(series_dir, prefer):
        ep_name = v.parent.name if v.parent != series_dir else v.stem
        items.append({
            "file": str(v).replace("\\", "/"),
            "cover": "",
            "text": f"【待填写：标题 + #话题，对应 {ep_name}】",
            "publish_at": "",
        })
    return {
        "series": series_dir.name,
        "note": "逐条填写 text（标题+#话题）；publish_at 留空=立即发布，或填 '2026-10-17 18:00'",
        "items": items,
    }


def load_manifest(path: Path, check_texts: bool = True) -> list[dict]:
    """读取并预检清单，返回 items。失败时打印原因并退出。"""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"清单读取失败: {e}")

    items = manifest.get("items")
    if not items:
        raise ManifestError("清单里没有 items（或为空）")

    for i, it in enumerate(items, 1):
        p = Path(it.get("file", ""))
        if not p.exists():
            raise ManifestError(f"第 {i} 集文件不存在: {p}")
        if not it.get("text", "").strip():
            raise ManifestError(f"第 {i} 集 text 为空")
        if check_texts and PLACEHOLDER_MARK in it.get("text", ""):
            raise ManifestError(f"第 {i} 集文案还是占位符，先填 text")
        cover = it.get("cover", "")
        if cover and not Path(cover).exists():
            raise ManifestError(f"第 {i} 集竖封面不存在: {cover}")
        cover_h = it.get("cover_h", "")
        if cover_h and not Path(cover_h).exists():
            raise ManifestError(f"第 {i} 集横封面不存在: {cover_h}")
        vis = it.get("visibility")
        if vis and vis not in config.VISIBILITIES:
            raise ManifestError(f"第 {i} 集 visibility 只能是 {config.VISIBILITIES}，实际: {vis}")
        decl = it.get("declaration")
        if decl and decl not in config.DECLARATIONS:
            raise ManifestError(f"第 {i} 集 declaration 只能是 {config.DECLARATIONS}，实际: {decl}")
        if "allow_save" in it and not isinstance(it["allow_save"], bool):
            raise ManifestError(f"第 {i} 集 allow_save 必须是 true/false")
        pa = it.get("publish_at", "")
        if pa:
            try:
                datetime_from_str(pa)
            except ValueError:
                raise ManifestError(f"第 {i} 集 publish_at 格式应为 'YYYY-MM-DD HH:MM'，实际: {pa}")
    return items


def datetime_from_str(s: str):
    from datetime import datetime
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")


def fail(msg: str):
    print(f"!! {msg}", file=sys.stderr)
    sys.exit(1)
