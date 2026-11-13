#!/usr/bin/env python3
"""og 圖分級計數的單位：一則查核條目，不是一個單元。

為什麼這支測試存在（#63）：meta.evidence_checked 是 len(evidence)，以查核條目為單位、
含立場聲明；grade_counts() 以前只走 chapters → units。只要有一條 concept-* 沒被
evidenceAlias 指到，兩個數字就必然不相等，build 直接失敗——而 evidence.md 寫的正是
「不屬於任何章節的 concept-* 會被抽出來當立場聲明」。

跑法（Makefile 的 test 目標會一起跑）：
    python3 -m unittest discover -s tests -p 'test_*.py'
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "build"))
# seo.py 在 import 時就要解析一門課；grade_counts 本身跟哪門課無關
os.environ.setdefault("COURSE", str(ROOT / "examples" / "body"))

import seo  # noqa: E402


def ev(key: str, grade: str = "moderate") -> dict:
    return {"unit": key, "evidence_grade": grade}


def course(units: list[dict], stance: list[dict]) -> dict:
    return {"chapters": [{"units": units}], "stance": stance}


class GradeCounts(unittest.TestCase):
    def test_standalone_stance_is_counted(self):
        c = course(
            [{"id": "ch1-u1", "evidence": ev("ch1-u1")}, {"id": "ch1-u2"}],
            [ev("concept-1", "weak"), ev("concept-2", "weak")],
        )
        self.assertEqual(seo.grade_counts(c), {"moderate": 1, "weak": 2})

    def test_aliased_stance_counted_once(self):
        stance = ev("concept-1", "weak")
        c = course([{"id": "ch1-u2", "evidence": stance}], [stance])
        self.assertEqual(sum(seo.grade_counts(c).values()), 1)

    def test_shared_alias_counted_once(self):
        shared = ev("ch1-u1")
        c = course(
            [{"id": "ch1-u1", "evidence": shared}, {"id": "ch1-u3", "evidence": shared}],
            [],
        )
        self.assertEqual(sum(seo.grade_counts(c).values()), 1)

    def test_missing_grade_not_counted(self):
        c = course([{"id": "ch1-u1", "evidence": {"unit": "ch1-u1"}}], [])
        self.assertEqual(sum(seo.grade_counts(c).values()), 0)


if __name__ == "__main__":
    unittest.main()
