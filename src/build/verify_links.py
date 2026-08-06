#!/usr/bin/env python3
"""獨立驗證 course.json 內所有 YouTube 連結是否真的存在且可播放。

不信任任何上游宣稱，一律重打 YouTube。有兩條路：

**有 YOUTUBE_API_KEY** → `videos.list` 直接回 uploadStatus／privacyStatus／
embeddable／regionRestriction／duration。一次查 50 支算 1 unit 配額，
幾百支影片只要幾次請求。

**沒有金鑰** → 退回 oEmbed，行為與這條路存在之前逐字元相同。oEmbed 只能靠
HTTP 狀態碼反推死因，而且分不出「設為私人」與「禁止嵌入」——那兩件事的處置
完全不同（前者要換片，後者影片還在但站內播放器放不了）。

金鑰申請流程見 .env.example；為什麼缺金鑰不能失敗，見那份檔案開頭。

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
import refsources  # 外部資料庫的憑證與呼叫，全部集中在那裡

ROOT = coursepath.ROOT
COURSE = coursepath.dist_dir(coursepath.course_dir()) / "course.json"
OEMBED = "https://www.youtube.com/oembed?url={}&format=json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"

# 影片長度差多少才值得報。策展時是用眼睛抄的，差個幾秒是四捨五入，不是錯誤；
# 差到下面這個程度通常代表**抄到另一支影片**了。
DURATION_TOLERANCE_S = 15
DURATION_TOLERANCE_PCT = 0.05


def check(url: str) -> tuple[str, bool, str]:
    """oEmbed 路徑：回傳 (url, ok, 說明)。沒有 YOUTUBE_API_KEY 時走這條。

    ok=True 只代表**影片存在且公開**——oEmbed 回 200 並不保證允許嵌入。
    YouTube 的「禁止嵌入」是獨立設定，oEmbed 看不到；那正是 videos.list
    那條路要補的洞。
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


def hms_to_seconds(s: str) -> int | None:
    """課程資料裡的 "8:40" / "1:02:30" → 秒。認不出來回 None，不要猜。"""
    parts = (s or "").strip().split(":")
    if not 1 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total


def check_via_api(urls: list[str]) -> tuple[dict[str, tuple[bool, str]], dict[str, dict]] | None:
    """videos.list 路徑。回 ({url: (ok, 說明)}, {video_id: item})；走不通回 None。

    連 items 一起回傳，是因為長度與地區限制要用**同一批回應**——分兩次拿等於
    白花一倍配額，還可能拿到兩個時間點的不一致結果。

    回 None 與回 ({}, {}) 意義完全不同：後者是「這批影片一支都不存在」，None 是
    「這條路走不通，請退回 oEmbed」。混為一談會讓缺金鑰的環境把每一支影片
    都報成已刪除，然後 --prune 把整門課的連結清空。
    """
    ids = {u: refsources.video_id(u) for u in urls}
    known = sorted({v for v in ids.values() if v})
    items = refsources.youtube_videos(known)
    if items is None:
        return None

    out: dict[str, tuple[bool, str]] = {}
    for url, vid in ids.items():
        if not vid:
            # 不是可辨識的 YouTube 網址。這條路查不了，交給 oEmbed 判斷。
            out[url] = (True, "非 YouTube 網址，未經 API 驗證")
            continue
        item = items.get(vid)
        if not item:
            # 查得到金鑰、查不到這支 id：影片已刪除，或網址本身就是錯的。
            out[url] = (False, "影片已刪除或網址錯誤")
            continue
        status = item.get("status") or {}
        snippet = item.get("snippet") or {}
        who = snippet.get("channelTitle") or "?"
        what = snippet.get("title") or "?"
        if status.get("uploadStatus") in {"deleted", "rejected", "failed"}:
            out[url] = (False, f"YouTube 標記為 {status['uploadStatus']}")
        elif status.get("privacyStatus") == "private":
            out[url] = (False, "已設為私人（要換片）")
        elif status.get("embeddable") is False:
            # oEmbed 完全看不到這件事：影片公開、連結點得開，但站內播放器
            # 放不了。對學習者而言這門課就是壞的，所以算失效。
            out[url] = (False, "上傳者禁止嵌入，站內播放器放不了（連結本身仍可開）")
        else:
            out[url] = (True, f"{who} — {what}")
    return out, items


def region_blocked(item: dict) -> list[str]:
    """這支影片被封鎖的地區。沒有限制回空。"""
    rr = (item.get("contentDetails") or {}).get("regionRestriction") or {}
    return list(rr.get("blocked") or [])


def walk(course: dict):
    """走訪所有影片節點，yield (章節碼, 單元 id, 標籤, 影片 dict)。"""
    for ch in course["chapters"]:
        for u in ch["units"]:
            # lessons 含各語言版本；沒有 lessons 時退回單一 lesson
            for les in u.get("lessons") or ([u["lesson"]] if u.get("lesson") else []):
                yield ch["code"], u["id"], f"主課 {les.get('lang', '')}".strip(), les
            for d in u.get("drills") or []:
                yield ch["code"], u["id"], d.get("name", "?"), d


def audit_metadata(nodes, items: dict[str, dict]) -> tuple[list[str], list[str]]:
    """拿 YouTube 回報的事實去對資料檔的宣稱。回 (長度不符, 地區封鎖)。

    `make audit` 早就在稽核影片長度，但那是拿資料檔裡的數字自己跟自己比——
    被比的那個數字從來沒有被任何人驗證過。這裡把它從「宣稱」變成「可覆核」，
    跟 verify_refs.py 對 design 做的事情完全同構。
    """
    bad_duration, blocked = [], []
    for code, uid, label, v in nodes:
        vid = refsources.video_id(v.get("url") or "")
        item = items.get(vid) if vid else None
        if not item:
            continue

        if regions := region_blocked(item):
            shown = "、".join(regions[:8]) + ("…" if len(regions) > 8 else "")
            blocked.append(f"{code} {uid} · {label} · 封鎖 {len(regions)} 地區：{shown}")

        claimed = hms_to_seconds(v.get("duration") or "")
        actual = refsources.duration_seconds(
            ((item.get("contentDetails") or {}).get("duration")) or ""
        )
        if claimed is None or actual is None:
            continue
        gap = abs(claimed - actual)
        if gap > DURATION_TOLERANCE_S and gap > actual * DURATION_TOLERANCE_PCT:
            bad_duration.append(
                f"{code} {uid} · {label} · 宣稱 {v['duration']}，實際 "
                f"{actual // 60}:{actual % 60:02d}"
            )
    return bad_duration, blocked


def main() -> int:
    prune = "--prune" in sys.argv
    course = json.loads(COURSE.read_text())

    nodes = list(walk(course))
    urls = sorted({v["url"] for *_, v in nodes if v.get("url")})
    print(refsources.credentials_summary())
    print(f"檢查 {len(urls)} 個不重複連結（涵蓋 {len(nodes)} 個影片欄位）…\n")

    items: dict[str, dict] = {}
    if via_api := check_via_api(urls):
        results, items = via_api
    else:
        if refsources.YOUTUBE_API_KEY:
            print("⚠ YouTube Data API 查詢失敗（配額或金鑰問題），退回 oEmbed\n")
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = {u: (ok, msg) for u, ok, msg in pool.map(check, urls)}

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

    # 這兩項只警告，不讓交付失敗：地區封鎖對多數觀眾仍然可播，長度對不上是
    # 資料品質問題而不是連結失效。把它們算成失敗會讓真正的斷鏈被淹掉。
    if items:
        bad_duration, blocked = audit_metadata(nodes, items)
        if blocked:
            print(f"\n⚠ {len(blocked)} 支影片有地區限制：")
            for line in blocked[:10]:
                print(f"   {line}")
        if bad_duration:
            print(f"\n⚠ {len(bad_duration)} 支影片的長度與資料檔不符（可能抄到別支）：")
            for line in bad_duration[:15]:
                print(f"   {line}")
    elif not refsources.YOUTUBE_API_KEY:
        print("\nℹ 沒有 YOUTUBE_API_KEY，略過嵌入權限、地區限制與影片長度的核對")
        print("  （申請流程見 .env.example；沒有它一切照舊，只是少這三項檢查）")

    alive = len(urls) - len(dead)
    print(f"\n有效 {alive} / {len(urls)}（{alive / max(len(urls), 1) * 100:.1f}%）")
    return 1 if dead and not prune else 0


if __name__ == "__main__":
    sys.exit(main())
