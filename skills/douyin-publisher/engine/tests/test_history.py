# -*- coding: utf-8 -*-
"""离线单测：发布记录（Markdown + CSV）。"""
import csv
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from douyin_publisher import history


def make_item():
    return {
        "_idx": 1,
        "_series": "人生高性价比指南",
        "file": "D:/videos/Ep11.mp4",
        "text": "标题|带竖线\n正文\n#话题",
        "collection": "人生高性价比指南",
        "visibility": "公开",
        "declaration": "内容由AI生成",
        "cover": "竖.png",
        "cover_h": "横.png",
        "publish_at": "",
    }


def make_result(status="ok"):
    res = {
        "index": 1,
        "status": status,
        "error_code": "",
        "error": "",
        "topics": ["话题A", "话题B"],
        "topic_details": [
            {"name": "话题A", "view_count": 1_200_000_000},
            {"name": "话题B", "view_count": 0},
        ],
    }
    if status == "fail":
        res["error_code"] = "selector_drift"
        res["error"] = "找不到发布按钮"
    return res


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "发布记录.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_markdown_and_csv(self):
        info = history.record([make_item()], [make_result()], "清单.json", self.path)
        self.assertEqual(info["rows"], 1)
        md = self.path.read_text(encoding="utf-8")
        self.assertIn("| 时间 | 状态 |", md)
        self.assertIn("标题\\|带竖线", md)          # Markdown 竖线转义
        self.assertIn("#话题A(12.0亿)", md)         # 话题带热度
        self.assertIn("立即", md)
        self.assertIn("公开 / 内容由AI生成 / 双封面", md)
        self.assertIn("成功", md)

        with self.path.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "时间")
        self.assertEqual(rows[1][3], "标题|带竖线")  # CSV 原样保留
        self.assertEqual(rows[1][10], "清单.json")
        self.assertFalse((self.path.parent / ".gitignore").exists())  # 自定义目录不乱丢 .gitignore

    def test_append_without_duplicate_header(self):
        history.record([make_item()], [make_result()], "清单.json", self.path)
        history.record([make_item()], [make_result()], "清单.json", self.path)
        md = self.path.read_text(encoding="utf-8")
        self.assertEqual(md.count("# 抖音发布记录"), 1)
        self.assertEqual(md.count("| 时间 | 状态 |"), 1)
        self.assertEqual(len(history.read_rows(self.path, 10)), 2)

    def test_failure_row(self):
        history.record([make_item()], [make_result("fail")], "清单.json", self.path)
        md = self.path.read_text(encoding="utf-8")
        self.assertIn("失败：selector_drift 找不到发布按钮", md)
        rows = history.read_rows(self.path, 10)
        self.assertEqual(rows[0]["状态"], "失败")

    def test_read_rows_and_tail(self):
        history.record([make_item()], [make_result()], "清单.json", self.path)
        rows = history.read_rows(self.path, 5)
        self.assertEqual(rows[0]["系列"], "人生高性价比指南")
        self.assertIn("#话题A(12.0亿)", rows[0]["话题（热度）"])
        tail = history.tail_markdown(self.path, 5)
        self.assertIn("| 时间 |", tail)
        self.assertIn("成功", tail)
        self.assertEqual(tail.count("| 时间 |"), 1)  # 行数少于 limit 时不能重复表头

    def test_scheduled_status(self):
        item = make_item()
        item["publish_at"] = "2026-10-19 08:10"
        history.record([item], [make_result()], "清单.json", self.path)
        rows = history.read_rows(self.path, 5)
        self.assertEqual(rows[0]["状态"], "已定时")
        self.assertEqual(rows[0]["结果"], "定时已设置")
        self.assertEqual(rows[0]["发布方式"], "2026-10-19 08:10")

    def test_new_custom_dir_self_ignores(self):
        d = Path(self.tmp.name) / "records"
        info = history.record([make_item()], [make_result()], "清单.json", d)
        self.assertEqual(Path(info["md"]), d / "发布记录.md")
        self.assertTrue((d / ".gitignore").exists())
        self.assertIn("*", (d / ".gitignore").read_text(encoding="utf-8"))

    def test_resolve_path(self):
        d = Path(self.tmp.name) / "记录目录"
        self.assertEqual(history.resolve_path(d), d / "发布记录.md")
        self.assertEqual(history.resolve_path(self.path.with_suffix(".csv")), self.path)

    def test_default_path_uses_project_root(self):
        root = Path(self.tmp.name) / "proj"
        (root / ".git").mkdir(parents=True)
        manifest = root / "tmp" / "publish" / "清单.json"
        manifest.parent.mkdir(parents=True)
        self.assertEqual(
            history.default_md(manifest), root / ".douyin-publisher" / "发布记录.md"
        )
        self.assertEqual(
            history.resolve_path(None, manifest), root / ".douyin-publisher" / "发布记录.md"
        )

    def test_default_path_fallback_to_manifest_dir(self):
        root = Path(self.tmp.name) / "plain"
        root.mkdir()
        manifest = root / "清单.json"
        with unittest.mock.patch.object(history, "find_project_root", return_value=None):
            self.assertEqual(
                history.default_md(manifest), root / ".douyin-publisher" / "发布记录.md"
            )

    def test_record_uses_manifest_project(self):
        root = Path(self.tmp.name) / "proj2"
        (root / ".git").mkdir(parents=True)
        manifest = root / "tmp" / "publish" / "清单.json"
        manifest.parent.mkdir(parents=True)
        info = history.record([make_item()], [make_result()], manifest)
        self.assertEqual(
            Path(info["md"]), root / ".douyin-publisher" / "发布记录.md"
        )
        self.assertTrue(Path(info["csv"]).exists())
        self.assertTrue((root / ".douyin-publisher" / ".gitignore").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
