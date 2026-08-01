#!/usr/bin/env python3
"""獨立驗證 course.json 內所有 YouTube 連結是否真的存在且可播放。

不信任任何上游宣稱，一律重打 YouTube oEmbed 端點。
被刪除／設為私人／地區封鎖的影片會回 401/403/404。
用法：
    python3 verify_links.py            # 驗證並列出失效連結
    python3 verify_links.py --prune    # 額外把失效連結的 url 改成 null 並註記原因
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

ROOT = coursepath.ROOT
COURSE = coursepath.dist_dir(coursepath.course_dir()) / "course.json"
OEMBED = "https://www.youtube.com/oembed?url={}&format=json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"


def check(url: str) -> tuple[str, bool, str]:
    """回傳 (url, ok, 說明)。

    ok=True 只代表**影片存在且公開**——oEmbed 回 200 並不保證允許嵌入。
    YouTube 的「禁止嵌入」是獨立設定，oEmbed 看不到。實測本專案 344 支
    影片全部可嵌入（`yt-dlp --print "%(playable_in_embed)s"`），所以沒有
    為此加一道需要 yt-dlp 的檢查；真的遇到播放器顯示「無法播放」但這裡
    回報正常時，用上面那個指令單獨查。
    """
    endpoint = OEMBED.format(urllib.parse.quote(url, safe=""))
    req = urllib.request.Request(endpoint, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            meta = json.loads(res.read())
            return url, True, f"{meta.get('author_name', '?')} — {meta.get('title', '?')}"
    except urllib.error.HTTPError as e:
        reason = {
            # 401 有兩種成因，處置完全不同：設為私人要換片，
            # 只是禁止嵌入則影片還在、連結仍可用，只是站內播放器放不了
            401: "已設為私人／不公開，或上傳者禁止嵌入（前者要換片，後者可保留連結但站內播放器放不了）",
            403: "受限制",
            404: "影片已刪除或網址錯誤",
        }.get(e.code, f"HTTP {e.code}")
        return url, False, reason
    except Exception as e:  # 逾時、DNS、TLS
        return url, False, f"連線失敗：{type(e).__name__}"


def walk(course: dict):
    """走訪所有影片節點，yield (章節碼, 單元 id, 標籤, 影片 dict)。"""
    for ch in course["chapters"]:
        for u in ch["units"]:
            # lessons 含各語言版本；沒有 lessons 時退回單一 lesson
            for les in u.get("lessons") or ([u["lesson"]] if u.get("lesson") else []):
                yield ch["code"], u["id"], f"主課 {les.get('lang', '')}".strip(), les
            for d in u.get("drills") or []:
                yield ch["code"], u["id"], d.get("name", "?"), d


def main() -> int:
    prune = "--prune" in sys.argv
    course = json.loads(COURSE.read_text())

    nodes = list(walk(course))
    urls = sorted({v["url"] for *_, v in nodes if v.get("url")})
    print(f"檢查 {len(urls)} 個不重複連結（涵蓋 {len(nodes)} 個影片欄位）…\n")

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = dict((u, (ok, msg)) for u, ok, msg in pool.map(check, urls))

    dead = {u: msg for u, (ok, msg) in results.items() if not ok}

    if dead:
        print(f"✗ {len(dead)} 個連結失效：\n")
        for code, uid, label, v in nodes:
            if v.get("url") in dead:
                print(f"   {code} {uid} · {label}")
                print(f"      {v['url']} — {dead[v['url']]}")
                if prune:
                    v["note"] = f"原連結已失效（{dead[v['url']]}），待補"
                    v["url"] = None
        if prune:
            COURSE.write_text(json.dumps(course, ensure_ascii=False, indent=1))
            print(f"\n→ 已將 {len(dead)} 個失效連結標記為 null 並寫回 course.json")
    else:
        print("✓ 全部連結有效")

    alive = len(urls) - len(dead)
    print(f"\n有效 {alive} / {len(urls)}（{alive / len(urls) * 100:.1f}%）")
    return 1 if dead and not prune else 0


if __name__ == "__main__":
    sys.exit(main())
