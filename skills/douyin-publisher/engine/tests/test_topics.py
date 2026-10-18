# -*- coding: utf-8 -*-
"""离线单测：话题筛选逻辑（不启动浏览器）。"""
import unittest
from urllib.parse import unquote

from douyin_publisher import topics


class _Resp:
    def __init__(self, data):
        self._data = data
        self.status = 200

    def json(self):
        return self._data


class _Req:
    def __init__(self, table):
        self.table = table
        self.calls = []

    def get(self, url, timeout=0):
        self.calls.append(url)
        kw = unquote(url.split("keyword=")[1].split("&")[0])
        return _Resp({"status_code": 0, "sug_list": self.table.get(kw, [])})


class _Ctx:
    def __init__(self, table):
        self.request = _Req(table)


def item(name, heat, cid="c"):
    return {"cha_name": name, "view_count": heat, "cid": cid}


class TopicsTest(unittest.TestCase):
    def test_parse_heat(self):
        self.assertEqual(topics.parse_heat("1亿"), 100_000_000)
        self.assertEqual(topics.parse_heat("1.5亿"), 150_000_000)
        self.assertEqual(topics.parse_heat("5000万"), 50_000_000)
        self.assertEqual(topics.parse_heat("1e8"), 100_000_000)
        self.assertEqual(topics.parse_heat(123), 123)
        with self.assertRaises(ValueError):
            topics.parse_heat("很多")

    def test_relevance_guard(self):
        table = {
            "AED": [item("AED", 1_540_000_000), item("艾尔登法环", 13_150_000_000)],
        }
        plan = topics.resolve(_Ctx(table), {"seeds": ["AED"], "count": 1}, series="急救")
        self.assertEqual([s["name"] for s in plan["selected"]], ["AED"])
        # 艾尔登法环虽然更热，但名字不含 AED，被相关性闸门挡掉

    def test_min_heat_and_pin(self):
        table = {
            "人生高性价比指南": [item("人生高性价比指南", 723_000)],
            "程序员": [item("程序员", 68_300_000_000)],
            "法律红线": [item("法律红线", 47_378_000)],
            "职场避坑": [item("职场避坑", 570_000_000)],
        }
        cfg = {
            "theme": "人生高性价比指南",
            "pin": ["程序员"],
            "seeds": ["法律红线", "职场避坑"],
            "count": 2,
        }
        plan = topics.resolve(_Ctx(table), cfg)
        self.assertEqual(plan["names"][:2], ["人生高性价比指南", "程序员"])
        self.assertEqual([s["name"] for s in plan["selected"]], ["职场避坑"])
        self.assertEqual(plan["stats"]["qualified"], 1)

    def test_max_per_seed(self):
        table = {
            "创业": [item("创业", 258_348_101_175), item("创业vlog", 30_063_328_250)],
            "职场": [item("职场", 421_471_498_099)],
        }
        cfg = {"seeds": ["创业", "职场"], "count": 2, "max_per_seed": 1}
        plan = topics.resolve(_Ctx(table), cfg)
        self.assertEqual([s["name"] for s in plan["selected"]], ["职场", "创业"])
        # 创业 比 职场 热，但 创业vlog 被 max_per_seed 挡掉

    def test_api_down(self):
        plan = topics.resolve(_Ctx({}), {"theme": "主题", "seeds": ["创业"]})
        self.assertFalse(plan["api_ok"])
        self.assertEqual(plan["names"], ["主题"])

    def test_dedupe(self):
        table = {
            "创业": [item("创业", 258_348_101_175), item("创业", 1)],
            "职场": [item("创业", 258_348_101_175)],
        }
        plan = topics.resolve(_Ctx(table), {"seeds": ["创业", "职场"], "count": 3})
        self.assertEqual([s["name"] for s in plan["selected"]], ["创业"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
