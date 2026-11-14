# -*- coding: utf-8 -*-
"""回归测试：未解析对局不能崩（extra=None 路径）。"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import dota_blame  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "match_9088224702.json")


class UnparsedMatchTest(unittest.TestCase):
    def test_unparsed_match_payload(self):
        with open(FIXTURE, encoding="utf-8") as f:
            match = json.load(f)
        # 离线：不走网络
        dota_blame.fetch_match = lambda *a, **k: match
        dota_blame.request_parse = lambda *a, **k: None
        dota_blame.load_hero_names = lambda: ({1: "Anti-Mage"}, {1: "敌法师"})

        payload = dota_blame.run(9088224702, 181585714)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["info"]["parsed"])
        self.assertIsNone(payload["suspect"])          # 未解析没有野区数据
        self.assertIsNone(payload["crash"])
        self.assertEqual(len(payload["players"]), 5)
        self.assertTrue(all(p["extra"] is None for p in payload["players"]))
        self.assertIn("分锅判决书", payload["report_md"])
        # JSON 可序列化（服务器要 json.dumps）
        json.dumps(payload, ensure_ascii=False)

    def test_extra_rank_with_none_extra(self):
        rows = [{"p": {"player_slot": 1}, "extra": None},
                {"p": {"player_slot": 2}, "extra": {"neutral_kills": 5}}]
        self.assertEqual(dota_blame.extra_rank(rows, 1, "neutral_kills"), 2)
        self.assertEqual(dota_blame.extra_rank(rows, 2, "neutral_kills"), 1)


if __name__ == "__main__":
    unittest.main()
