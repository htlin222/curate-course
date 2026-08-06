#!/usr/bin/env python3
"""YouTube Data API 那條路徑的判定邏輯。

為什麼這支測試存在：`--prune` 會把判定為失效的連結**寫成 null**。這條路徑
如果把好影片誤判成死的，一次 make verify 就能清空整門課的影片，而且是在
沒有人盯著的每週排程裡。實際打 API 需要金鑰、也不該在單元測試裡連外網，
所以這裡用假回應把每一種狀態都走一遍。

跑法（Makefile 的 test 目標會一起跑）：
    python3 -m unittest discover -s tests -p 'test_*.py'
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "build"))

import refsources
import verify_links as VL


def item(
    vid: str,
    *,
    upload="processed",
    privacy="public",
    embeddable=True,
    duration="PT8M40S",
    blocked=None,
) -> dict:
    """一筆假的 videos.list item，形狀與真實回應一致。"""
    content: dict = {"duration": duration}
    if blocked:
        content["regionRestriction"] = {"blocked": blocked}
    return {
        "id": vid,
        "status": {"uploadStatus": upload, "privacyStatus": privacy, "embeddable": embeddable},
        "contentDetails": content,
        "snippet": {"channelTitle": "某頻道", "title": "某影片"},
    }


def url_of(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


class FakeAPI:
    """把 refsources.youtube_videos 換成固定回應，測完還原。"""

    def __init__(self, response):
        self.response = response

    def __enter__(self):
        self._real = refsources.youtube_videos
        refsources.youtube_videos = lambda ids: self.response
        return self

    def __exit__(self, *exc):
        refsources.youtube_videos = self._real


class TestCheckViaApi(unittest.TestCase):
    def test_正常影片判定為有效(self):
        with FakeAPI({"aaaaaaaaaaa": item("aaaaaaaaaaa")}):
            results, items = VL.check_via_api([url_of("aaaaaaaaaaa")])
        ok, msg = results[url_of("aaaaaaaaaaa")]
        self.assertTrue(ok)
        self.assertIn("某頻道", msg)
        self.assertIn("aaaaaaaaaaa", items)

    def test_禁止嵌入判定為失效(self):
        """oEmbed 對這種影片會回 200——這正是 API 那條路要補的洞。"""
        with FakeAPI({"bbbbbbbbbbb": item("bbbbbbbbbbb", embeddable=False)}):
            results, _ = VL.check_via_api([url_of("bbbbbbbbbbb")])
        ok, msg = results[url_of("bbbbbbbbbbb")]
        self.assertFalse(ok)
        self.assertIn("禁止嵌入", msg)

    def test_設為私人判定為失效(self):
        with FakeAPI({"ccccccccccc": item("ccccccccccc", privacy="private")}):
            results, _ = VL.check_via_api([url_of("ccccccccccc")])
        ok, msg = results[url_of("ccccccccccc")]
        self.assertFalse(ok)
        self.assertIn("私人", msg)

    def test_回應裡沒有這支代表已刪除(self):
        with FakeAPI({}):
            results, _ = VL.check_via_api([url_of("ddddddddddd")])
        ok, msg = results[url_of("ddddddddddd")]
        self.assertFalse(ok)
        self.assertIn("刪除", msg)

    def test_非_youtube_網址不判失效(self):
        """這條路查不了它，但「查不了」不等於「壞了」——誤判會讓 --prune 清掉它。"""
        other = "https://vimeo.com/123456"
        with FakeAPI({}):
            results, _ = VL.check_via_api([other])
        ok, _ = results[other]
        self.assertTrue(ok)

    def test_缺金鑰時回_None_而不是空結果(self):
        """回 {} 會被當成「全部影片都不存在」，然後 --prune 清空整門課。"""
        with FakeAPI(None):
            self.assertIsNone(VL.check_via_api([url_of("eeeeeeeeeee")]))


class TestDurationAudit(unittest.TestCase):
    def nodes(self, vid: str, duration: str):
        return [("CH1", "u1", "主課", {"url": url_of(vid), "duration": duration})]

    def test_長度相符不報(self):
        items = {"aaaaaaaaaaa": item("aaaaaaaaaaa", duration="PT8M40S")}
        bad, _ = VL.audit_metadata(self.nodes("aaaaaaaaaaa", "8:40"), items)
        self.assertEqual(bad, [])

    def test_差幾秒不報(self):
        """策展時是用眼睛抄的，差幾秒是四捨五入，不是抄錯。"""
        items = {"aaaaaaaaaaa": item("aaaaaaaaaaa", duration="PT8M46S")}
        bad, _ = VL.audit_metadata(self.nodes("aaaaaaaaaaa", "8:40"), items)
        self.assertEqual(bad, [])

    def test_差很多要報(self):
        """8:40 對 23:10 通常代表抄到另一支影片了。"""
        items = {"aaaaaaaaaaa": item("aaaaaaaaaaa", duration="PT23M10S")}
        bad, _ = VL.audit_metadata(self.nodes("aaaaaaaaaaa", "8:40"), items)
        self.assertEqual(len(bad), 1)
        self.assertIn("宣稱 8:40", bad[0])
        self.assertIn("23:10", bad[0])

    def test_長度格式認不出來就不猜(self):
        items = {"aaaaaaaaaaa": item("aaaaaaaaaaa", duration="PT8M40S")}
        bad, _ = VL.audit_metadata(self.nodes("aaaaaaaaaaa", "大約八分鐘"), items)
        self.assertEqual(bad, [])

    def test_地區封鎖會列出來(self):
        items = {"aaaaaaaaaaa": item("aaaaaaaaaaa", blocked=["DE", "JP"])}
        _, blocked = VL.audit_metadata(self.nodes("aaaaaaaaaaa", "8:40"), items)
        self.assertEqual(len(blocked), 1)
        self.assertIn("DE", blocked[0])


class TestHelpers(unittest.TestCase):
    def test_hms_轉秒(self):
        self.assertEqual(VL.hms_to_seconds("8:40"), 520)
        self.assertEqual(VL.hms_to_seconds("1:02:30"), 3750)
        self.assertEqual(VL.hms_to_seconds("45"), 45)
        self.assertIsNone(VL.hms_to_seconds("八分四十秒"))
        self.assertIsNone(VL.hms_to_seconds(""))

    def test_iso_期間轉秒(self):
        self.assertEqual(refsources.duration_seconds("PT4M13S"), 253)
        self.assertEqual(refsources.duration_seconds("PT1H2M3S"), 3723)
        self.assertEqual(refsources.duration_seconds("PT45S"), 45)
        self.assertIsNone(refsources.duration_seconds("nonsense"))

    def test_抽影片_id(self):
        self.assertEqual(refsources.video_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(
            refsources.video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5s"),
            "dQw4w9WgXcQ",
        )
        self.assertIsNone(refsources.video_id("https://vimeo.com/123"))


class TestRetractedTitle(unittest.TestCase):
    """Crossref 標記撤稿最常見的方式就是改標題，見 refsources 裡的實測註解。"""

    def test_認得出前綴(self):
        for title in ("RETRACTED: Something", "Retracted: Something", "WITHDRAWN: Something"):
            self.assertTrue(refsources.RETRACTED_TITLE.match(title), title)

    def test_不誤判正常標題(self):
        for title in ("Retraction rates in surgery journals", "A study of withdrawal symptoms"):
            self.assertIsNone(refsources.RETRACTED_TITLE.match(title), title)


if __name__ == "__main__":
    unittest.main()
