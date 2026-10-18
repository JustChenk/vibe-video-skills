# -*- coding: utf-8 -*-
"""发布记录：把每次真发布的结果追加到 Markdown + CSV（Excel 可直接打开）。

设计：
- 默认落在「项目根目录/.douyin-publisher/发布记录.md」，同名 CSV 并列；
  项目根从清单路径向上找 `.git` / `.workbuddy` / `AGENTS.md` / `CLAUDE.md` 判定，
  找不到就退回清单所在目录。**不写用户主目录**，也不默认写进 skill 仓库（那是公开仓库）。
- 只在 `--execute`（真发布）后记录，dry-run 不写，避免刷屏；
- Markdown 给人看/进项目，CSV（utf-8-sig）给 Excel 看；
- 写失败只警告，绝不影响发布主流程；
- 话题列带热度（来自 topics.resolve 的 topic_details），方便复盘哪种话题组合有效。
"""

import csv
import time
from pathlib import Path

from .topics import format_heat

PROJECT_MARKERS = (".git", ".workbuddy", "AGENTS.md", "CLAUDE.md")

HEADERS = [
    "时间", "状态", "系列", "标题", "文件", "合集",
    "话题（热度）", "发布方式", "设置", "结果", "清单",
]

_STATUS_CN = {
    "ok": "成功",
    "unknown": "结果未知",
    "fail": "失败",
    "abort": "中止",
    "skip": "跳过",
}


def find_project_root(start=None):
    """从 start（文件或目录）向上找项目根；找不到返回 None。"""
    p = Path(start).expanduser().resolve() if start else Path.cwd().resolve()
    if not p.is_dir():
        p = p.parent
    for cand in [p, *p.parents]:
        if any((cand / m).exists() for m in PROJECT_MARKERS):
            return cand
    return None


def default_md(anchor=None) -> Path:
    """默认记录路径：<项目根>/.douyin-publisher/发布记录.md。

    anchor 传清单路径时按清单定位项目；不传则按当前工作目录。
    找不到项目标记时退回 anchor 所在目录（不落到用户主目录）。
    """
    p = Path(anchor).expanduser().resolve() if anchor else Path.cwd().resolve()
    start = p if p.is_dir() else p.parent
    root = find_project_root(start) or start
    return root / ".douyin-publisher" / "发布记录.md"


def resolve_path(path=None, anchor=None) -> Path:
    """--history 可给 .md 文件、.csv 文件或目录；不传则用项目内默认路径。"""
    if not path:
        return default_md(anchor)
    p = Path(path).expanduser()
    if p.suffix.lower() in (".md", ".csv"):
        return p.with_suffix(".md")
    return p / "发布记录.md"


def _md_cell(value) -> str:
    s = str(value if value is not None else "")
    return s.replace("|", "\\|").replace("\n", "<br>").strip()


def _title(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[0] if lines else ""


def _topics_cell(names, details) -> str:
    heat = {}
    for d in details or []:
        heat[str(d.get("name", "")).strip()] = int(d.get("view_count") or 0)
    parts = []
    for name in names or []:
        name = str(name).strip().lstrip("#")
        h = heat.get(name, 0)
        parts.append(f"#{name}({format_heat(h)})" if h else f"#{name}")
    return " ".join(parts)


def _settings_cell(item) -> str:
    vis = item.get("visibility") or "公开"
    decl = item.get("declaration") or ("内容由AI生成" if item.get("aigc") else "无声明")
    if item.get("cover") and item.get("cover_h"):
        cover = "双封面"
    elif item.get("cover"):
        cover = "竖封面"
    else:
        cover = "自动截帧"
    return f"{vis} / {decl} / {cover}"


def _result_cell(res, item=None) -> str:
    text = _STATUS_CN.get(res.get("status"), res.get("status", ""))
    if res.get("status") == "ok" and item and (item.get("publish_at") or "").strip():
        text = "定时已设置"
    if res.get("error"):
        msg = str(res["error"]).replace("\n", " ")
        if len(msg) > 80:
            msg = msg[:77] + "..."
        text += f"：{res.get('error_code') or 'error'} {msg}"
    return text


def build_rows(items, results, manifest_name="") -> list[list[str]]:
    by_idx = {}
    for i, it in enumerate(items, 1):
        by_idx[it.get("_idx", i)] = it
    rows = []
    for res in results:
        item = by_idx.get(res.get("index"), {})
        status = _STATUS_CN.get(res.get("status"), res.get("status", ""))
        if status == "成功" and (item.get("publish_at") or "").strip():
            status = "已定时"
        rows.append([
            time.strftime("%Y-%m-%d %H:%M"),
            status,
            item.get("_series", "") or "",
            _title(item.get("text", "")),
            Path(item.get("file", "")).name if item.get("file") else "",
            item.get("collection", "") or "",
            _topics_cell(res.get("topics"), res.get("topic_details")),
            (item.get("publish_at") or "立即").strip(),
            _settings_cell(item),
            _result_cell(res, item),
            manifest_name,
        ])
    return rows


def _ensure_dir(d: Path):
    """建目录；新建目录（或默认 .douyin-publisher）放自我忽略的 .gitignore。

    只对“本次新建的目录”写，避免把用户已有的通用目录（如 tmp/）整体 ignore。
    """
    existed = d.exists()
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if (d.name == ".douyin-publisher" or not existed) and not gi.exists():
        gi.write_text("*\n!.gitignore\n", encoding="utf-8")


def record(items, results, manifest_path=None, path=None) -> dict | None:
    """追加本次发布结果；没有可记录的行时返回 None。"""
    rows = build_rows(items, results, Path(manifest_path).name if manifest_path else "")
    if not rows:
        return None
    md = resolve_path(path, manifest_path)
    _ensure_dir(md.parent)
    new_md = not md.exists() or md.stat().st_size == 0
    with md.open("a", encoding="utf-8", newline="\n") as f:
        if new_md:
            f.write("# 抖音发布记录\n\n")
            f.write("> 由 douyin-publisher 自动追加；同目录 CSV 可直接用 Excel 打开。\n\n")
            f.write("| " + " | ".join(HEADERS) + " |\n")
            f.write("|" + "|".join(["---"] * len(HEADERS)) + "|\n")
        for row in rows:
            f.write("| " + " | ".join(_md_cell(c) for c in row) + " |\n")

    csv_path = md.with_suffix(".csv")
    new_csv = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if new_csv:
            writer.writerow(HEADERS)
        writer.writerows(rows)
    return {"md": str(md), "csv": str(csv_path), "rows": len(rows)}


def read_rows(path=None, limit=20, anchor=None) -> list[dict]:
    """从 CSV 读结构化记录（没有 CSV 时退回解析 Markdown 表格）。"""
    md = resolve_path(path, anchor)
    csv_path = md.with_suffix(".csv")
    rows = []
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            data = list(reader)
        if data:
            headers = data[0]
            rows = [dict(zip(headers, r)) for r in data[1:] if len(r) >= len(headers)]
    elif md.exists():
        lines = [ln for ln in md.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
        if len(lines) >= 2:
            headers = [c.strip() for c in lines[0].strip("|").split("|")]
            for ln in lines[2:]:
                cells = [c.strip().replace("\\|", "|") for c in ln.strip("|").split("|")]
                if len(cells) == len(headers):
                    rows.append(dict(zip(headers, cells)))
    return rows[-limit:] if limit else rows


def tail_markdown(path=None, limit=20, anchor=None) -> str:
    md = resolve_path(path, anchor)
    if not md.exists():
        return ""
    lines = [ln for ln in md.read_text(encoding="utf-8").splitlines() if ln.startswith("|")]
    if len(lines) <= 2:
        return "\n".join(lines)
    data = lines[2:]
    if len(data) <= limit:
        return "\n".join(lines)
    return "\n".join(lines[:2] + data[-limit:])
