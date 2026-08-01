#!/usr/bin/env python3
"""由 public/course.json 產生 SEO 資產。

- 把 Course JSON-LD 注入 index.html 的 <script id="schema">
- 由 src/web/og.html 模板產生 dist/og.html（社群預覽圖的來源）
- 產生 sitemap.xml / robots.txt / llms.txt

數字全部取自 course.json，不手寫，避免結構化資料與實際內容對不上。
"""

from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coursepath  # 框架自己的模組，要先把 src/build 加進路徑

ROOT = coursepath.ROOT
COURSE = coursepath.course_dir()
PUB = coursepath.dist_dir(COURSE)
WEB = ROOT / "src" / "web"

CFG = json.loads((COURSE / "course.config.json").read_text())
SITE_CFG = CFG["site"]
_UI = CFG.get("ui") or {}
# 名詞一律走設定檔。沒設定就只留數字，不要把中文名詞塞進別的語言的課程裡。
UNIT_NOUN = _UI.get("unitNoun", "")
DRILL_NOUN = _UI.get("drillNoun", "")
SITE = SITE_CFG["url"].rstrip("/")
NAME = SITE_CFG["name"]
TITLE = SITE_CFG["title"]
DESC = SITE_CFG["description"]
# 沒設定就不宣告語言。原本這裡預設 "zh-Hant"，等於幫每一門沒設 locale 的課
# 對搜尋引擎宣稱它是繁體中文的——猜錯了照樣是合法的 JSON-LD，不會有人發現。
LOCALE = SITE_CFG.get("locale")
# 語言標記統一從這裡展開，才不會漏掉其中一處
LANG = {"inLanguage": LOCALE} if LOCALE else {}


# ── 文案契約 ──────────────────────────────────────────────────────────────
# 設定檔的文案一律先逸出，然後只認得 `**粗體**`。src/web/js/copy.js 有一份等價
# 實作（執行期用），兩份必須永遠給出同一個字串，由 tests/copy-contract.test.js 比對。
#
# 這裡以前完全不逸出：`site.title` 或 `ui.searchPlaceholder` 裡出現一個雙引號，
# 就直接切斷 <meta content="…"> 或 placeholder="…"，產出壞掉的 HTML——
# 而且 build、audit、測試全部照樣通過。

_BOLD = re.compile(r"\*\*([\s\S]+?)\*\*")


def esc(value) -> str:
    """HTML 逸出。五個字元與 copy.js 的 esc() 完全一致。"""
    return html.escape("" if value is None else str(value), quote=True)


def rich(value) -> str:
    """段落文案（元素內容）：逸出後把 `**粗體**` 展開成 <strong>。"""
    return _BOLD.sub(r"<strong>\1</strong>", esc(value))


def plain(value) -> str:
    """屬性與純文字：標籤在這裡塞不進去，所以把 `**` 記號拿掉只留文字。"""
    return _BOLD.sub(r"\1", esc(value))


def iso_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    return f"PT{h}H{rem // 60}M"


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"   ⚠ {msg}")


def build_schema(course: dict) -> dict:
    meta = course["meta"]
    chapters = course["chapters"]

    # schema.org 的 numberOfLessons 是「課程中的課數」，也就是章節單元數。
    # 這裡曾經餵 meta["units"]（= 主課 + 跟練影片的欄位合計），於是一門 83 堂的課
    # 對 Google 宣稱有 493 堂——頁面上完全看不出來，只有讀 JSON-LD 才會發現。
    # 這是唯一會被搜尋引擎直接消費的數字，寧可在這裡把 build 弄掛也不要靜靜地錯。
    lessons = sum(len(ch["units"]) for ch in chapters)
    if lessons != meta["lesson_units"]:
        die(
            f"JSON-LD：章節單元合計 {lessons} 與 meta.lesson_units {meta['lesson_units']} 不一致，"
            "course.json 自己就對不上，不要餵給搜尋引擎"
        )

    # 主題單元的型別由 ui.problemType 決定。這裡原本寫死 fallback "posture"，
    # 而正上方的註解就寫著「寫死換主題會產出空的 teaches……這種沉默的失敗最難發現」——
    # 註解說對了，程式沒照做。健身課用 movement、語言課用別的，都會挑到空集合或錯的集合。
    # 現在沒設定就不猜：teaches 整個不宣告。寧可不宣告，也不要宣告錯的。
    _ptype = _UI.get("problemType")
    teaches = [u["name"] for ch in chapters for u in ch["units"] if u.get("type") == _ptype] if _ptype else []
    if not _ptype:
        warn("沒有設定 ui.problemType，JSON-LD 不宣告 teaches（設了才知道哪些單元是主題單元）")
    elif not teaches:
        warn(f"ui.problemType 是「{_ptype}」，但沒有任何單元是這個型別，teaches 會是空的——多半是打錯字")

    _unit_noun, _drill_noun = UNIT_NOUN, DRILL_NOUN
    syllabus = [
        {
            "@type": "Syllabus",
            "position": i,
            "name": f"{ch['code']} {ch['title']}",
            "description": (
                f"{len(ch['units'])}{_unit_noun and ' ' + _unit_noun}"
                + (
                    f"：{'、'.join(u['name'] for u in ch['units'])}"
                    if len(ch["units"]) <= 4
                    else ""
                )
                + (
                    f"，附 {sum(len(u.get('drills') or []) for u in ch['units'])} {_drill_noun}".rstrip()
                    if any(u.get("drills") for u in ch["units"])
                    else ""
                )
            ),
        }
        for i, ch in enumerate(chapters, 1)
    ]

    # 立場聲明的引用，讓機器也讀得到這門課的實證基礎
    citations = []
    for s in course.get("stance", []):
        for c in s.get("citations", [])[:3]:
            if c.get("url"):
                citations.append(
                    {
                        "@type": "CreativeWork",
                        "name": c.get("title", ""),
                        "url": c["url"],
                        **({"datePublished": str(c["year"])} if c.get("year") else {}),
                    }
                )

    org = {
        "@type": "Organization",
        "@id": f"{SITE}/#org",
        "name": NAME,
        "url": f"{SITE}/",
    }

    return {
        "@context": "https://schema.org",
        "@graph": [
            org,
            {
                "@type": "WebSite",
                "@id": f"{SITE}/#website",
                "url": f"{SITE}/",
                "name": NAME,
                "description": DESC,
                **LANG,
                "publisher": {"@id": f"{SITE}/#org"},
            },
            {
                "@type": "Course",
                "@id": f"{SITE}/#course",
                "url": f"{SITE}/",
                "name": TITLE,
                "description": DESC,
                "image": f"{SITE}/og.png",
                **LANG,
                "isAccessibleForFree": True,
                "isFamilyFriendly": True,
                "provider": {"@id": f"{SITE}/#org"},
                # 原本寫死 "Beginner"：不管課程實際難度，每一門課都對搜尋引擎宣稱是入門。
                # 改成沒設定就不宣告——這是關於課程的事實陳述，猜不得。
                **(
                    {"educationalLevel": SITE_CFG["educationalLevel"]}
                    if SITE_CFG.get("educationalLevel")
                    else {}
                ),
                "learningResourceType": SITE_CFG.get("learningResourceType", []),
                "timeRequired": iso_duration(meta["duration_seconds"]),
                **({"teaches": teaches} if teaches else {}),
                "about": [{"@type": "Thing", "name": x} for x in SITE_CFG.get("about", [])],
                "audience": {
                    "@type": "Audience",
                    "audienceType": SITE_CFG.get("audience", ""),
                },
                "hasCourseInstance": {
                    "@type": "CourseInstance",
                    "courseMode": "online",
                    "courseWorkload": iso_duration(meta["duration_seconds"]),
                    **LANG,
                    "isAccessibleForFree": True,
                    "location": {"@type": "VirtualLocation", "url": f"{SITE}/"},
                },
                "syllabusSections": syllabus,
                "numberOfLessons": meta["lesson_units"],
                **({"citation": citations} if citations else {}),
            },
        ],
    }


def lookup(dotted: str):
    """依 "a.b.c" 從設定檔取值，任何一段不存在就回 None。"""
    node = CFG
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def is_attr_context(markup: str, pos: int) -> bool:
    """這個位置是不是在某個標籤的屬性值裡面？

    判斷方式是往前找最後一個 `<` 與 `>`：`<` 比較近就代表還在標籤內。
    首屏的 placeholder="{{ui.searchPlaceholder}}" 屬於這一類，展開 <strong>
    會直接把屬性切斷；元素內容（<p>{{hero.lede}}</p>）才允許粗體。
    """
    head = markup[:pos]
    if head.rfind("<") > head.rfind(">"):
        return True
    # <title> 是 RCDATA：塞進去的 <strong> 不會變成標籤，只會出現在分頁標題上
    return head.rfind("<title") > head.rfind("</title")


def render_template(meta: dict) -> list[str]:
    """把 {{a.b}} 換成課程設定裡的值，回傳沒解析掉的佔位符。

    文案在 build 時就寫進 HTML，而不是等 JS 跑完才填——首屏就有真實內容，
    對搜尋引擎與未執行 JS 的爬蟲都友善。
    """
    path = PUB / "index.html"
    markup = path.read_text()

    def sub(m):
        val = lookup(m.group(1))
        if val is None:
            return m.group(0)
        text = fill(val, meta)
        return plain(text) if is_attr_context(m.string, m.start()) else rich(text)

    markup, n = re.subn(r"\{\{([\w.]+)\}\}", sub, markup)
    path.write_text(markup)
    left = sorted(set(re.findall(r"\{\{[\w.]+\}\}", markup)))
    print(f"   index.html  文案注入 {n} 處" + (f"，⚠ 未解析 {left}（make audit 會擋）" if left else ""))
    return left


def inject_schema(schema: dict) -> None:
    """把 JSON-LD 寫進 index.html 的佔位 script。"""
    path = PUB / "index.html"
    markup = path.read_text()
    # JSON 內出現 </script> 會提前結束標籤，必須跳脫
    payload = json.dumps(schema, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    new, n = re.subn(
        r'(<script type="application/ld\+json" id="schema">).*?(</script>)',
        lambda m: m.group(1) + payload + m.group(2),
        markup,
        flags=re.S,
    )
    if n != 1:
        print("✗ index.html 找不到 JSON-LD 佔位 script", file=sys.stderr)
        sys.exit(1)
    path.write_text(new)
    print(f"   index.html  JSON-LD 已注入（{len(payload) / 1024:.1f} KB）")


HEAD_TAGS = """    <link rel="canonical" href="{site}/" />
    <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="{name}" />
{oglocale}    <meta property="og:url" content="{site}/" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="{ogdesc}" />
    <meta property="og:image" content="{site}/og.png" />
    <meta property="og:image:type" content="image/png" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title}" />
    <meta name="twitter:description" content="{ogdesc}" />
    <meta name="twitter:image" content="{site}/og.png" />
    <meta name="description" content="{desc}" />
"""


def inject_meta(course: dict) -> None:
    """用設定重建 head 裡的 SEO 標籤，取代模板中的佔位區塊。

    每一個值都進到 content="…" 或 href="…" 裡，所以一律走 plain()：
    以前是直接字串格式化，`site.title` 裡一個雙引號就會把 <meta> 切成兩半。
    """
    path = PUB / "index.html"
    markup = path.read_text()
    block = HEAD_TAGS.format(
        site=plain(SITE),
        name=plain(NAME),
        title=plain(TITLE),
        desc=plain(DESC),
        ogdesc=plain(SITE_CFG.get("ogDescription", DESC)),
        # 原本預設 "zh_TW"。沒設定就整個標籤不要輸出——社群平台寧可自己猜語言，
        # 也好過被我們斬釘截鐵地告知一個錯的。
        oglocale=(
            f'    <meta property="og:locale" content="{plain(SITE_CFG["ogLocale"])}" />\n'
            if SITE_CFG.get("ogLocale")
            else ""
        ),
    )
    markup, n = re.subn(
        r"<!-- seo:start -->.*?<!-- seo:end -->",
        lambda _: f"<!-- seo:start -->\n{block}    <!-- seo:end -->",
        markup,
        flags=re.S,
    )
    path.write_text(markup)
    print(f"   index.html  SEO 標籤{'已注入' if n else '找不到佔位區塊'}")


def write_sitemap() -> None:
    (PUB / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        "  <url>\n"
        f"    <loc>{SITE}/</loc>\n"
        f"    <lastmod>{date.today().isoformat()}</lastmod>\n"
        "    <changefreq>monthly</changefreq>\n"
        "    <priority>1.0</priority>\n"
        "    <image:image>\n"
        f"      <image:loc>{SITE}/og.png</image:loc>\n"
        # 這一行以前不是 f-string，sitemap 上線後真的印著字面的「{NAME}」。
        # 跟 #28 是同一種病：沒替換掉的佔位符靜靜流進正式產物。
        f"      <image:title>{esc(NAME)}</image:title>\n"
        "    </image:image>\n"
        "  </url>\n"
        "</urlset>\n"
    )
    print("   sitemap.xml")


def write_robots() -> None:
    (PUB / "robots.txt").write_text(
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "# AI 檢索器一律放行 —— 這門課的實證註記正是希望被引用到的內容\n"
        "User-agent: GPTBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: ClaudeBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: PerplexityBot\n"
        "Allow: /\n"
        "\n"
        "User-agent: Google-Extended\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {SITE}/sitemap.xml\n"
    )
    print("   robots.txt")


# 文案佔位符只有這一份定義。之前 HTML 注入與 llms.txt 各有一套替換邏輯，
# 結果 llms.txt 只認得兩個 token，作者在設定檔用了第三個就直接 KeyError。
# 前端曾經還有第三套（只認得兩個 token，且 {videos} 指向另一個數字），
# 現在統一由 src/web/js/copy.js 的 TOKEN_FIELDS 對應，兩份逐項相等。
TOKEN_FIELDS = {
    "units": "units",
    "lessonUnits": "lesson_units",
    "drillUnits": "drill_units",
    "slots": "video_slots",
    "videos": "video_unique",
    "problems": "problem_units",
    "evidence": "evidence_checked",
}


def token_map(meta: dict) -> dict:
    """三個數字互不相同：units 是影片欄位合計，lessonUnits 才是章節單元數。"""
    return {tok: meta.get(field, 0) for tok, field in TOKEN_FIELDS.items()}


def fill(text: str | None, meta: dict) -> str:
    """未知的 token 原樣保留，讓 make audit 抓得到，不要靜靜吞掉。"""
    tokens = token_map(meta)
    return re.sub(
        r"\{(\w+)\}", lambda m: str(tokens.get(m.group(1), m.group(0))), str(text or "")
    )


# ── llms.txt ──────────────────────────────────────────────────────────────────
# 這裡以前是整段寫死的中文句型：「共 X 個單元（X 個影片欄位、去重後 X 支…）」、
# 「## 章節」、「## 免責」、條列的「（分級）：摘要…」。設定檔全部可換之後，
# 就只剩這一份產出物還會用中文對著一門英文課或日文課講話——而且寫死的句型
# 連覆寫的接縫都沒有（fallback 至少還能蓋掉）。
#
# 改法跟 og.html 的 render_og() 同一套：模板 + 一份 build 算好的值。
# 差別只在模板住在 course.config.json 的 llms 區塊，而不是 src/web 的檔案裡——
# llms.txt 的模板本體就是文案，跟課程一起走比較合理。
#
# 值的記號是 [[值]] 而不是 og.html 的 {{值}}，唯一的理由是位置不同：模板住在設定檔裡，
# 而 audit.py 用 \{(\w+)\} 掃設定檔文案裡打錯的數字佔位符，`{{durationHours}}` 會被它
# 讀成 `{durationHours}` 然後報「未定義的佔位符」。等 audit.py 學會跳過 {{…}} 就能統一。
#
# **受限標記在這裡的行為**：不逸出、不展開。llms.txt 是純文字（Markdown 風格），
# 沒有任何 HTML sink——逸出只會讓讀者看到字面的 &amp;，而 `**粗體**` 本來就是
# Markdown 自己的粗體語法，原樣送出正好。這是文案契約裡唯一一個「原樣輸出」的出口，
# 理由是這裡根本沒有需要被防的注入面。詳見 reference/config.md。

LLMS_VALUE = re.compile(r"\[\[(\w+)\]\]")
LLMS_VALUES = "[[course]]、[[url]]、[[durationHours]]、[[durationMinutes]]"
LLMS_STANCE_VALUES = "[[name]]、[[grade]]、[[summary]]、[[summaryShort]]"
LLMS_CHAPTER_VALUES = "[[code]]、[[title]]、[[units]]、[[unitCount]]"

# 立場條目的摘要在 llms.txt 裡要截短，否則整份檔案會被三段長摘要吃掉。
# 截斷後不補任何符號：要不要加「…」由模板自己決定（那是標點，屬於語言）。
STANCE_SUMMARY_CHARS = 180


def write_llms(course: dict) -> None:
    meta, chapters = course["meta"], course["chapters"]
    llm = CFG.get("llms") or {}
    stance = course.get("stance") or []
    left: set[str] = set()

    # 總長刻意拆成「時」與「分」兩個數字：meta["duration"] 是 build.py 組好的
    # 「26 小時 3 分」，把它塞進來等於又從別的檔案漏一次中文進 llms.txt。
    base = {
        "course": NAME,
        "url": f"{SITE}/",
        "durationHours": meta.get("duration_seconds", 0) // 3600,
        "durationMinutes": meta.get("duration_seconds", 0) % 3600 // 60,
    }

    def render(text: str | None, extra: dict | None = None) -> str:
        """設定檔的一段文案 → 最終字串。[[值]] 先填，再填 {數字}。"""
        if not text:
            return ""
        values = base if extra is None else {**base, **extra}
        out = LLMS_VALUE.sub(lambda m: str(values.get(m.group(1), m.group(0))), str(text))
        left.update(LLMS_VALUE.findall(out))
        return fill(out, meta)

    def bullets(template: str, rows: list[dict]) -> str:
        """條列。`- ` 是 Markdown 的結構，一行裡的其他東西全部由模板決定。"""
        return "\n".join(f"- {render(template, row)}" for row in rows)

    def section(title: str | None, *parts: str) -> list[str]:
        """一段內容 + 它的標題。整段都沒東西時連標題一起消失——
        一個底下什麼都沒有的 `## 免責` 比沒有那一段更難看。"""
        body = [p for p in parts if p]
        if not body:
            return []
        return ([f"## {title}"] if title else []) + body

    # 區塊之間一律空一行；沒宣告的文案就整塊不輸出，不要留下空行或半截的段落
    blocks = [f"# {NAME}", f"> {DESC}", render(llm.get("summary"))]

    if stance:
        if item := llm.get("stanceItem"):
            rows = [
                {
                    "name": s.get("name", ""),
                    "grade": s.get("evidence_grade", ""),
                    "summary": s.get("summary", ""),
                    "summaryShort": s.get("summary", "")[:STANCE_SUMMARY_CHARS],
                }
                for s in stance
            ]
        else:
            rows = []
            warn(f"有立場聲明但沒設定 llms.stanceItem，llms.txt 不會列出任何一條（可用 {LLMS_STANCE_VALUES}）")
        # 標題是課程自己的用語，框架不替它發明一個
        title = render(llm.get("stanceTitle")) or (CFG.get("stance") or {}).get("title", "")
        if not title:
            warn("有立場聲明但沒設定 llms.stanceTitle（或 stance.title），llms.txt 這一段不會有標題")
        blocks += section(
            title,
            render(llm.get("stanceIntro")),
            bullets(item, rows) if rows else "",
            render(llm.get("stanceConclusion")),
        )

    if chapter_item := llm.get("chapterItem"):
        sep = llm.get("unitSeparator")
        if sep is None and "[[units]]" in chapter_item:
            sep = ", "
            warn("llms.chapterItem 用了 [[units]] 但沒設定 llms.unitSeparator，先用 \", \" 串（中日韓多半要「、」）")
        blocks += section(
            render(llm.get("chaptersTitle")),
            bullets(
                chapter_item,
                [
                    {
                        "code": ch["code"],
                        "title": ch["title"],
                        "units": (sep or "").join(u["name"] for u in ch["units"]),
                        "unitCount": len(ch["units"]),
                    }
                    for ch in chapters
                ],
            ),
        )
    else:
        warn(f"沒有設定 llms.chapterItem，llms.txt 不會列出章節（可用 {LLMS_CHAPTER_VALUES}）")

    blocks += section(render(llm.get("disclaimerTitle")), render(llm.get("disclaimer")))

    # 沒寫 footer 就只印裸網址：那是這份檔案的功能（讓 LLM 找得到本體），
    # 不是文案；框架可以自己給網址，但不會替課程寫一句中文帶出它。
    blocks.append(render(llm.get("footer")) or f"{SITE}/")

    if left:
        die(
            "llms.txt：文案裡有填不了的值 "
            + "、".join(f"[[{n}]]" for n in sorted(left))
            + f"。每個欄位都能用 {LLMS_VALUES}；stanceItem 另有 {LLMS_STANCE_VALUES}、"
            f"chapterItem 另有 {LLMS_CHAPTER_VALUES}"
        )

    (PUB / "llms.txt").write_text("\n\n".join(b for b in blocks if b) + "\n")
    print(f"   llms.txt   {len(chapters)} 章" + (f"、{len(stance)} 條立場" if stance else ""))


# ── 社群預覽圖 ────────────────────────────────────────────────────────────────
# og.html 以前是純手工的靜態模板：換主題要手改大標、四個統計數字、四個分級的計數
# 與標籤、品牌名、inline 的 icon path、頁尾網域。其中「分級計數」跟「分級標籤」寫在
# 兩個地方，改了標籤忘了改數字，圖上就會留著上一門課的統計，而且沒有任何檢查會發現。
# 這些值 build 全部都算好了，所以改成注入 + 對不上就讓 build 掛掉。

# 這門課線上實際會拿到的那一份 sprite。sync_web() 先複製 src/web、再讓
# $COURSE/assets/ 覆蓋同名檔，所以課程有自己的 icons.js 時，dist 拿到的是
# 課程那一份——og 圖必須看同一份，否則品牌圖示會莫名其妙地留白。
ICONS_JS_CANDIDATES = (COURSE / "assets" / "js" / "icons.js", WEB / "js" / "icons.js")
_SPRITE: dict[str, str] = {}


def sprite() -> dict[str, str]:
    """讀 build_icons.py 產生的 sprite，讓 og.html 不必內嵌寫死的 <path>。"""
    if not _SPRITE:
        for path in ICONS_JS_CANDIDATES:
            if not path.exists():
                continue
            m = re.search(r'ICON_SPRITE\s*=\s*("(?:[^"\\]|\\.)*")', path.read_text(), re.S)
            if m:
                for name, inner in re.findall(
                    r'<symbol id="i-([^"]+)"[^>]*>(.*?)</symbol>', json.loads(m.group(1)), re.S
                ):
                    _SPRITE[name] = inner
                break
    return _SPRITE


def icon_svg(name: str | None, size: int) -> str:
    """圖示缺了只是視覺退化（截圖仍然可用），警告就好，不擋 build。"""
    inner = sprite().get(name or "")
    if not inner:
        if name:
            print(f"   ⚠ og.html 找不到圖示 i-{name}，先留白（跑 make icons 重打包這門課的 sprite）")
        return ""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    )


def grade_counts(course: dict) -> Counter:
    """每個證據分級各有幾個單元——og 圖上的 chip 數字唯一的來源。"""
    counts: Counter = Counter()
    for ch in course["chapters"]:
        for u in ch["units"]:
            if grade := (u.get("evidence") or {}).get("evidence_grade"):
                counts[grade] += 1
    return counts


def og_stat_value(field: str, meta: dict) -> str:
    """og 的數字欄位。多一個 duration_hours 是因為 40px 的字塞不下「26 小時 3 分」。"""
    if field == "duration_hours":
        return f"{round(meta['duration_seconds'] / 3600)} 小時"
    if field not in meta:
        die(
            f"og.stats 的 field「{field}」不是 course.json 的 meta 欄位，"
            f"可用的有：{'、'.join(sorted(meta))}、duration_hours"
        )
    return str(meta[field])


def og_text(text: str | None, meta: dict) -> str:
    """og 圖上的文案。跟站台一樣是「逸出 + **粗體**」，另外多一條：

    真正的換行字元會變成 <br>。og 是一張 1200×630 的固定畫布，斷句位置得由作者決定，
    這是唯一需要它的地方——以前是讓作者直接寫 <br />，代價是整個 og 區塊變成 raw HTML。
    """
    return rich(fill(text, meta)).replace("\n", "<br>")


def render_og(course: dict) -> None:
    meta = course["meta"]
    og = CFG.get("og") or {}
    tpl = WEB / "og.html"
    if not tpl.exists():
        print("   og.html  找不到模板，略過")
        return

    stats = og.get("stats") or (_UI.get("stats") or [])[:4]
    stats_html = "".join(
        f'<div class="stat"><b>{esc(og_stat_value(s["field"], meta))}</b>'
        f"<span>{og_text(s.get('label', ''), meta)}</span></div>"
        for s in stats
    )

    grades = CFG.get("grades") or []
    counts = grade_counts(course)
    if unknown := sorted(set(counts) - {g["id"] for g in grades}):
        die(f"og.html：單元用了設定檔沒有的證據分級 {unknown}，這些單元不會出現在 og 圖上")
    counted = sum(counts.values())
    if grades and counted != meta["evidence_checked"]:
        die(
            f"og.html：分級計數合計 {counted} 與 meta.evidence_checked {meta['evidence_checked']} 不一致。"
            "多半是有 oe-*.json 的條目沒對到任何單元（unit id 打錯或缺 evidenceAlias），"
            "放著不管的話 og 圖上的「查核題數」與分級 chip 會兜不起來"
        )
    chips_html = "".join(
        f'<span class="chip t-{esc(g.get("tone", "neutral"))}">{rich(g["label"])} '
        f'<i>{counts.get(g["id"], 0)}</i></span>'
        for g in grades
    )

    values = {
        # 整個屬性一起給，沒設定 locale 就不要留下 lang=""（更不能是 lang="None"）
        "htmlLang": f' lang="{plain(LOCALE)}"' if LOCALE else "",
        "brandIcon": icon_svg(SITE_CFG.get("brandIcon"), 26),
        "brandName": rich(NAME),
        "title": og_text(og.get("title") or (CFG.get("hero") or {}).get("heading") or TITLE, meta),
        "lede": og_text(og.get("lede") or SITE_CFG.get("ogDescription") or DESC, meta),
        "stats": stats_html,
        "evidenceIcon": icon_svg(og.get("evidenceIcon"), 20),
        # 這句話是課程自己的措辭（連查證來源都不一定是 OpenEvidence），
        # 沒設定就留白，不要由框架代寫一句中文
        "evidenceLabel": og_text(og.get("evidenceLabel", ""), meta),
        "chips": chips_html,
        "url": rich(og.get("url") or re.sub(r"^https?://|/$", "", SITE)),
    }

    markup = re.sub(
        r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), m.group(0))), tpl.read_text()
    )
    if left := sorted(set(re.findall(r"\{\{\w+\}\}", markup))):
        die(f"og.html：模板還有沒填的佔位符 {left}，截出來的圖會直接印出 {{{{…}}}}")
    (PUB / "og.html").write_text(markup)
    print(
        f"   og.html    注入 {len(stats)} 個統計、{len(grades)} 個分級"
        f"（合計 {counted} 題）· make og 由這一份截圖"
    )

    # #11：make og 以前寫進 gitignored 的 dist/，重新 clone 之後 /og.png 就是 404。
    # 現在的正解是輸出到 course/assets/（會進版控，build 時再複製到 dist）。
    if not (COURSE / "assets" / "og.png").exists():
        warn(f"找不到 {COURSE.name}/assets/og.png，社群卡片會破圖。跑 make og 產一張（會進版控）")


def main() -> int:
    course_path = PUB / "course.json"
    if not course_path.exists():
        print("✗ 找不到 public/course.json，請先執行 build.py", file=sys.stderr)
        return 1

    course = json.loads(course_path.read_text())
    print("SEO 資產：")
    if not LOCALE:
        warn("沒有設定 site.locale，JSON-LD 不宣告 inLanguage（猜一個語言比不講更糟）")
    if not SITE_CFG.get("ogLocale"):
        warn("沒有設定 site.ogLocale，不輸出 og:locale")
    render_template(course["meta"])
    inject_meta(course)
    inject_schema(build_schema(course))
    write_sitemap()
    write_robots()
    write_llms(course)
    render_og(course)
    return 0


if __name__ == "__main__":
    sys.exit(main())
