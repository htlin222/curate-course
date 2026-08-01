#!/usr/bin/env python3
"""把 data/ 下各章 JSON 合併成 public/course.json，並驗證配額與連結。"""

from __future__ import annotations

import importlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

ROOT = coursepath.ROOT
COURSE = coursepath.course_dir()
DATA = COURSE / "data"
WEB = ROOT / "src" / "web"
DIST = coursepath.dist_dir(COURSE)
OUT = DIST / "course.json"

CFG = json.loads((COURSE / "course.config.json").read_text())

# 章節、配額、別名全部由課程設定決定，框架本身不認識任何主題
CHAPTERS = [(c["code"], c["title"], c["icon"], c["source"]) for c in CFG["chapters"]]
QUOTA = {c["code"]: (c["units"], c.get("drills", 0)) for c in CFG["chapters"]}
EVIDENCE_ALIAS = CFG.get("evidenceAlias", {})
UI = CFG.get("ui") or {}

# 不屬於任何章節的實證條目 = 首頁的立場聲明。前綴可換（預設 concept-），
# 但**不限數量**：寫幾則就出現幾則，多寫的不會被靜靜丟掉。
STANCE_PREFIX = (CFG.get("stance") or {}).get("keyPrefix") or "concept-"

# video-meta.json 是 YouTube 取數的快取，不是課程內容，依名字讀取
VIDEO_META = "video-meta.json"
# 資料檔依「頂層有哪些鍵」判斷用途，不看檔名。任何一個都沒有 = 沒有人會讀它。
DATA_KEYS = ("conditions", "categories", "lessons", "chapters", "chapter", "units")

# 課程可以自帶詞彙模組（肌群、動作類別之類）；沒有就退化成無分面、無分類
sys.path.insert(0, str(COURSE))


def _load_taxonomy(key: str):
    name = (CFG.get("taxonomy") or {}).get(key)
    return importlib.import_module(name) if name else None


facets = _load_taxonomy("facets")
categories = _load_taxonomy("categories")

YT = re.compile(
    r"^https://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}(?:&\S*)?$|^https://youtu\.be/[\w-]{11}"
)


def parse_duration(s: str | None) -> int:
    """'12:34' / '1:02:33' -> 秒。無法解析回 0。"""
    if not s:
        return 0
    parts = s.strip().split(":")
    if not all(p.isdigit() for p in parts):
        return 0
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


def fmt_clock(total: int) -> str:
    """秒數 -> '8:38' / '1:02:33'"""
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else None


HAN = re.compile(r"[一-鿿]")


def detect_lang(text: str | None) -> str:
    return "zh" if HAN.search(text or "") else "en"


def collect_alt_lessons() -> dict:
    """unit_id -> 其他語言的主課影片清單。"""
    out: dict[str, list] = defaultdict(list)
    for _, les in data_rows("lessons"):
        if les.get("unit") and les.get("url"):
            out[les["unit"]].append(les)
    return out


def collect_drill_evidence() -> dict:
    """合併各 agent 產出的類別層級文獻。"""
    out = {}
    for _, cat in data_rows("categories"):
        if cat.get("id"):
            out[cat["id"]] = cat
    return out


def fmt_duration(total: int) -> str:
    h, rem = divmod(total, 3600)
    m = rem // 60
    return f"{h} 小時 {m} 分" if h else f"{m} 分"


_BROKEN: list[str] = []


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        # 壞掉的 JSON 曾經只印一行 stderr 就繼續跑：實證整片消失、建置照樣成功。
        # 記下來，最後併進 problems 讓 build 直接失敗。
        print(f"  ✗ {path.name} JSON 解析失敗：{e}", file=sys.stderr)
        _BROKEN.append(f"data/{path.name} 不是合法 JSON：第 {e.lineno} 行 {e.msg}")
        return None


_BLOBS: dict[Path, dict] | None = None


def data_blobs() -> dict[Path, dict]:
    """course/data/*.json 一次全部讀進來（只快取解析成功的物件）。

    刻意**不看檔名**：實證檔叫 oe-*.json 只是「這門課用 OpenEvidence」的歷史，
    而 ui.evidenceSource 是可換的。改成看頂層鍵之後，檔案要叫
    pubmed-ch1.json 或 evidence-頸椎.json 都讀得到。
    """
    global _BLOBS
    if _BLOBS is None:
        _BLOBS = {}
        for path in sorted(DATA.glob("*.json")):
            blob = load_json(path)
            if isinstance(blob, dict):
                _BLOBS[path] = blob
    return _BLOBS


def data_rows(key: str):
    """yield (path, dict)：所有資料檔頂層 `key` 陣列裡的物件節點。"""
    for path, blob in data_blobs().items():
        node = blob.get(key)
        if isinstance(node, list):
            for row in node:
                # agent 分批寫入時檔內可能殘留佔位字串，跳過非物件節點
                if isinstance(row, dict):
                    yield path, row


def unread_data_files() -> list[str]:
    """列出沒有任何一步會讀到的資料檔——鍵名打錯就是這樣靜靜消失的。"""
    return [
        path.name
        for path, blob in data_blobs().items()
        if path.name != VIDEO_META and not any(k in blob for k in DATA_KEYS)
    ]


def collect_evidence() -> dict:
    """把所有帶 conditions 的資料檔攤平成 unit_id -> evidence dict。"""
    ev = {}
    for _, cond in data_rows("conditions"):
        if cond.get("unit"):
            ev[cond["unit"]] = cond
    return ev


def _stance_order(key: str) -> tuple[int, str]:
    """concept-2 要排在 concept-10 前面；非數字尾巴一律排最後、字典序。"""
    tail = key[len(STANCE_PREFIX) :]
    return (int(tail), "") if tail.isdigit() else (10**6, key)


def collect_stance(evidence: dict) -> list:
    """前綴相符的實證條目全部都是立場聲明，不設上限。

    這裡曾經寫死 ("concept-1", "concept-2", "concept-3")，第 4 則之後
    不報錯也不顯示——查得越徹底、丟掉越多。要截斷是版面的事，交給前端。
    """
    keys = sorted((k for k in evidence if k.startswith(STANCE_PREFIX)), key=_stance_order)
    return [evidence[k] for k in keys]


def sync_web() -> None:
    """把框架的前端骨架複製到產物目錄，course/assets 可覆寫同名檔。"""
    DIST.mkdir(parents=True, exist_ok=True)
    for src in WEB.rglob("*"):
        if src.is_dir() or src.name == "og.html":
            continue
        dst = DIST / src.relative_to(WEB)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # 課程可放自己的 favicon、覆寫樣式等
    assets = COURSE / "assets"
    if assets.is_dir():
        for src in assets.rglob("*"):
            if src.is_dir():
                continue
            dst = DIST / src.relative_to(assets)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def main() -> int:
    evidence = collect_evidence()
    chapters, problems = [], []
    unit_total = drill_total = 0
    seconds = 0
    kinds = Counter()
    missing_urls, bad_urls, seen_urls = [], [], Counter()
    within_unit = Counter()  # (unit_id, url) -> 次數，同單元重複才是真問題

    vmeta = load_json(DATA / "video-meta.json") or {}
    drill_ev = collect_drill_evidence()
    alt_lessons = collect_alt_lessons()
    multilang = [0]
    meta_hits, meta_miss = [0], []
    seconds_all = [0]  # 含多語言版本的總長度
    alt_count = [0]
    cat_counts, uncategorised = Counter(), []
    facet_units: dict[str, set] = defaultdict(set)
    facet_count: Counter = Counter()

    # 各章 JSON 可能一檔含多章（ch0-3），先把所有來源讀進來
    sources = {}
    for _, _, _, src in CHAPTERS:
        if src not in sources:
            sources[src] = load_json(DATA / f"{src}.json")

    for code, title, ic, src in CHAPTERS:
        blob = sources.get(src)
        if not blob:
            problems.append(f"{code}: 找不到來源檔 data/{src}.json")
            continue

        # 一個檔可能是單章 {chapter, units} 或多章 {chapters: [...]}
        if blob.get("chapters"):
            node = next((c for c in blob["chapters"] if c.get("chapter") == code), None)
        elif blob.get("chapter") == code:
            node = blob
        else:
            node = None

        if not node:
            problems.append(f"{code}: 來源檔 data/{src}.json 中找不到這一章")
            continue

        units = node.get("units", [])
        want_units, want_drills = QUOTA[code]
        got_drills = sum(len(u.get("drills") or []) for u in units)

        if len(units) != want_units:
            problems.append(f"{code}: 單元數 {len(units)}，應為 {want_units}")
        if got_drills != want_drills:
            problems.append(f"{code}: 跟練影片 {got_drills} 支，應為 {want_drills}")

        for u in units:
            u.setdefault("id", f"{code.lower()}-u{units.index(u) + 1}")
            ev_key = EVIDENCE_ALIAS.get(u["id"], u["id"])
            if ev_key in evidence:
                u["evidence"] = evidence[ev_key]

            # 單元層級的分面：緊繃 + 無力兩側都算涉及
            u["facets"] = facets.extract(*(u.get("tight") or []), *(u.get("weak") or [])) if facets else []

            # 主課可以有多語言版本，第一支為預設
            if u.get("lesson"):
                u["lesson"].setdefault("lang", detect_lang(u["lesson"].get("title")))
                u["lessons"] = [u["lesson"], *alt_lessons.get(u["id"], [])]
                for les in u["lessons"][1:]:
                    les.setdefault("lang", detect_lang(les.get("title")))
                if len(u["lessons"]) > 1:
                    multilang[0] += 1

            # 替代語言版本要驗證與補 metadata，但不計入總時長（同一堂課不重複算）
            primary = {id(x) for x in [u.get("lesson"), *(u.get("drills") or [])] if x}
            vids = list(u.get("lessons") or [u.get("lesson")]) + list(u.get("drills") or [])
            for v in vids:
                if not v:
                    continue
                counts_toward_total = id(v) in primary
                url = v.get("url")
                if not url:
                    missing_urls.append(
                        f"{u['id']} / {v.get('name') or v.get('title') or '主課影片'}"
                    )
                    continue
                if not YT.match(url):
                    bad_urls.append(f"{u['id']}: {url}")
                seen_urls[url] += 1
                within_unit[(u["id"], url)] += 1

                # 時長與頻道以 YouTube 實際 metadata 為準，策展資料僅作後備
                info = vmeta.get(video_id(url) or "")
                if info and info.get("status") == "OK":
                    v["duration"] = fmt_clock(info["seconds"])
                    v["channel"] = info["channel"]
                    v["views"] = info["views"]
                    secs = info["seconds"]
                    meta_hits[0] += 1
                else:
                    secs = parse_duration(v.get("duration"))
                    meta_miss.append(url)
                seconds_all[0] += secs
                if counts_toward_total:
                    seconds += secs
                else:
                    alt_count[0] += 1

            for d in u.get("drills") or []:
                kinds[d.get("kind")] += 1
                d["facets"] = facets.extract(d.get("target"), d.get("name")) if facets else []
                if categories:
                    cid = categories.classify(d)
                    if cid:
                        d["cat"] = cid
                        cat_counts[cid] += 1
                        if cid in drill_ev:
                            d["catName"] = categories.NAMES[cid]
                    else:
                        # 沒設定 categories 時每個項目都「未分類」，那是假警報：
                        # 只在真的有分類維度時才記錄。
                        uncategorised.append(d.get("name"))

                for m in d["facets"]:
                    facet_units[m].add(u["id"])
                    facet_count[m] += 1
            for m in u["facets"]:
                facet_units[m].add(u["id"])
                facet_count[m] += 1

        unit_total += len(units)
        drill_total += got_drills
        chapters.append({"code": code, "title": title, "icon": ic, "units": units})

    dupes = {u: n for u, n in seen_urls.items() if n > 1}

    # 前綴相符的實證條目不屬於任何章節，全部抽出來當首頁的立場聲明
    stance = collect_stance(evidence)

    # 分面索引：依分組排序，數量少的不進篩選器（避免上百個一次性標籤）
    facet_index = [
        {
            "name": m,
            "group": facets.GROUP_OF.get(m, "其他") if facets else "其他",
            "count": facet_count[m],
            "units": sorted(facet_units[m]),
        }
        for m in sorted(facet_count, key=lambda x: -facet_count[x])
        if facet_count[m] >= 2
    ]
    group_order = [*(facets.GROUPS if facets else []), "其他"]
    facet_index.sort(key=lambda x: (group_order.index(x["group"]), -x["count"]))

    ui_keys = (
        "site", "hero", "ui", "kinds", "grades", "languages",
        "nav", "stance", "landing", "footer",
        "discussions", "counter", "paywall",
    )
    course = {
        "config": {k: CFG[k] for k in ui_keys if k in CFG},
        "stance": stance,
        "facets": facet_index,
        "drillEvidence": drill_ev,
        "meta": {
            # 課程結構：371 個單元 = 37 堂主課 + 334 支跟練
            "units": unit_total + drill_total,
            "lesson_units": unit_total,
            "drill_units": drill_total,
            # 影片：課程單元 + 多語言替代版本，去重後才是實際影片支數
            "alt_lessons": alt_count[0],
            "video_slots": unit_total + drill_total + alt_count[0],
            "video_unique": len(seen_urls),
            # 時長分兩個：跑完課程一輪 vs 把每個語言版本都看過
            "duration": fmt_duration(seconds),
            "duration_seconds": seconds,
            "duration_all": fmt_duration(seconds_all[0]),
            "duration_all_seconds": seconds_all[0],
            # 主題單元的型別由 ui.problemType 決定；沒設定就是「這門課沒有這個維度」。
            # 之前退回寫死的 "posture"，換主題後這個數字會莫名其妙地變成 0 或亂數。
            "problem_units": sum(
                1
                for c in chapters
                for u in c["units"]
                if UI.get("problemType") and u.get("type") == UI["problemType"]
            ),
            # 實證有兩層，三個數字都給出來，課程自己決定 ui.stats 要秀哪一個：
            # evidence_checked 只有單元層級（含立場聲明），category_evidence_checked
            # 是類別層級，evidence_total 才是對外可以講的「總查核則數」。
            "evidence_checked": len(evidence),
            "stance_count": len(stance),
            "category_evidence_checked": len(drill_ev),
            "evidence_total": len(evidence) + len(drill_ev),
        },
        "chapters": chapters,
    }

    sync_web()
    # TODO(paywall): 真要收費的話，付費章節的 lesson.url / drill.url 要從這份公開的
    # course.json 抽到 course.paid.json，由 functions/api/entitlement.js 驗證後才回傳。
    # 現在的 paywall 是 0 元的 UX 實驗，硬鎖只在前端，擋不住 F12。見 docs/PAYWALL.md。
    OUT.write_text(json.dumps(course, ensure_ascii=False, indent=1))

    # DIST 可能指到 repo 外（多課程並存時很常見），relative_to 會直接拋例外
    _shown = OUT.relative_to(ROOT) if OUT.is_relative_to(ROOT) else OUT
    print(f"→ {_shown}  ({OUT.stat().st_size / 1024:.0f} KB)")
    print(f"   主課單元 {unit_total} · 跟練影片 {drill_total} · 合計 {unit_total + drill_total}")
    # 統計行迭代設定檔的 kinds。寫死 id 換主題會讓每一類都印 0，看起來像資料壞了。
    print("   " + " / ".join(f"{k['label']} {kinds.get(k['id'], 0)}" for k in CFG["kinds"]))
    print(
        f"   影片 {unit_total + drill_total + alt_count[0]} 個欄位"
        f"（含 {alt_count[0]} 支多語言版本）· 去重後 {len(seen_urls)} 支"
    )
    print(
        f"   課程時長 {fmt_duration(seconds)}"
        f" · 全部語言版本 {fmt_duration(seconds_all[0])}"
    )

    # 輸出的名詞跟著 ui 走，框架本身不認識任何主題（預設一律中性）
    facet_noun = UI.get("facetPrefix") or "分面"
    cat_noun = UI.get("categoryNoun") or "類別"

    if evidence or drill_ev:
        ev_bits = [f"單元層級 {len(evidence)} 則"]
        if stance:
            ev_bits.append(f"其中立場聲明 {len(stance)} 則")
        if drill_ev:
            ev_bits.append(f"{cat_noun}層級 {len(drill_ev)} 則")
            ev_bits.append(f"合計 {len(evidence) + len(drill_ev)} 則")
        print(f"   實證查核 {' · '.join(ev_bits)}")

    bits = [f"YouTube metadata {meta_hits[0]}/{meta_hits[0] + len(meta_miss)} 命中"]
    if facets:
        bits.append(f"{facet_noun}索引 {len(facet_index)} 項")
    if categories:
        bits.append(f"{cat_noun} {len(cat_counts)} 類（文獻 {len(drill_ev)} 類）")
    print("   " + " · ".join(bits))

    # 分類分布：單一類別吃掉一大半通常代表 patterns 寫得太寬（門檻檢查在 audit.py）
    if categories and cat_counts:
        classified = sum(cat_counts.values())
        top = "、".join(
            f"{categories.NAMES.get(cid, cid)} {n}（{n / classified:.0%}）"
            for cid, n in cat_counts.most_common(3)
        )
        print(f"   {cat_noun}分布 前三 {top} · 未分類 {len(uncategorised)}")
    # 沒設定 categories 就不會有 uncategorised，這裡不會再對著一門沒有分類維度的課叫
    if uncategorised:
        print(
            f"   ⚠ 未歸類到任何{cat_noun} {len(uncategorised)} 項："
            f"{'、'.join(x for x in uncategorised[:5] if x)}"
        )

    if missing_urls:
        print(f"\n⚠ 缺影片連結 {len(missing_urls)} 支：")
        for m in missing_urls[:15]:
            print(f"   · {m}")
        if len(missing_urls) > 15:
            print(f"   … 另有 {len(missing_urls) - 15} 支")
    if bad_urls:
        print(f"\n✗ URL 格式不正確 {len(bad_urls)} 支：")
        for b in bad_urls[:10]:
            print(f"   · {b}")
    # 讀不到 / 沒人讀的資料檔一律講出來：靜靜跳過等於整片內容消失卻沒人知道
    if orphan_files := unread_data_files():
        print(f"\n⚠ {len(orphan_files)} 個資料檔沒有任何一步會讀到（頂層鍵打錯了？）：")
        for name in orphan_files:
            print(f"   · data/{name}（可用的頂層鍵：{'、'.join(DATA_KEYS)}）")
    problems.extend(dict.fromkeys(_BROKEN))  # 同一個檔可能被讀兩次，訊息去重

    same_unit_dupes = {k: n for k, n in within_unit.items() if n > 1}
    if same_unit_dupes:
        print(f"\n✗ 同一單元內重複的影片 {len(same_unit_dupes)} 筆：")
        for (uid, url), n in same_unit_dupes.items():
            print(f"   · {uid} 用了 {n} 次 {url}")
        problems.append(f"同單元重複影片 {len(same_unit_dupes)} 筆")
    if dupes:
        print(f"\n· 跨單元共用的影片 {len(dupes)} 支（規格允許的少量重疊）")
    if problems:
        print(f"\n✗ 配額不符 {len(problems)} 項：")
        for p in problems:
            print(f"   · {p}")
        return 1

    print("\n✓ 配額全數符合\n")

    # 結構化資料的數字必須跟著課程走，所以綁在建置流程裡
    import seo

    return seo.main()


if __name__ == "__main__":
    sys.exit(main())
